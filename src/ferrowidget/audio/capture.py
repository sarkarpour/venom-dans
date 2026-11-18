"""Audio capture thread reading from default monitor sink or synthetic generator."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np

from ferrowidget.audio.analysis import AudioAnalyzer, Features
from ferrowidget.audio.synthetic import generate_synthetic_audio

logger = logging.getLogger(__name__)


def get_default_monitor_source() -> Optional[str]:
    """Query default sink and append .monitor, with PipeWire fallback."""
    # 1. Try pactl
    if shutil.which("pactl"):
        try:
            proc = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.returncode == 0:
                sink = proc.stdout.strip()
                if sink:
                    return f"{sink}.monitor"
        except Exception as e:
            logger.debug("Failed to query default sink via pactl: %s", e)

    # 2. Try wpctl (WirePlumber / PipeWire)
    if shutil.which("wpctl"):
        try:
            proc = subprocess.run(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("node.name ="):
                        node_name = line.split("=", 1)[1].strip().strip('"')
                        if node_name:
                            return f"{node_name}.monitor"
        except Exception as e:
            logger.debug("Failed to query default sink via wpctl: %s", e)

    return "@DEFAULT_MONITOR@"


def get_default_input_source() -> Optional[str]:
    """Query default microphone/input source, with PipeWire fallback."""
    # 1. Try pactl
    if shutil.which("pactl"):
        try:
            proc = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.returncode == 0:
                src = proc.stdout.strip()
                if src:
                    return src
        except Exception as e:
            logger.debug("Failed to query default source via pactl: %s", e)

    # 2. Try wpctl (WirePlumber / PipeWire)
    if shutil.which("wpctl"):
        try:
            proc = subprocess.run(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SOURCE@"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("node.name ="):
                        node_name = line.split("=", 1)[1].strip().strip('"')
                        if node_name:
                            return node_name
        except Exception as e:
            logger.debug("Failed to query default source via wpctl: %s", e)

    return "@DEFAULT_SOURCE@"


class AudioCaptureThread(threading.Thread):
    """Background worker thread capturing system audio and running DSP analysis."""

    def __init__(
        self,
        source: str = "auto",
        sensitivity: float = 1.0,
        visual_delay_ms: int = 0,
        synthetic_source: Optional[str] = None,
        mic_mode: bool = False,
    ):
        super().__init__(name="AudioCaptureThread", daemon=True)
        self.source = source
        self.synthetic_source = synthetic_source
        self.mic_mode = mic_mode
        self.analyzer = AudioAnalyzer(sensitivity=sensitivity)
        self.analyzer.set_visual_delay(visual_delay_ms)

        self._running = threading.Event()
        self._running.set()
        self._paused = threading.Event()

        # Atomic reference swap for thread-safe access from GUI thread
        self._latest_features: Features = self.analyzer._make_default_features()

        self._current_source = ""
        self._parec_proc: Optional[subprocess.Popen] = None
        self._subscribe_proc: Optional[subprocess.Popen] = None
        self._watcher_thread: Optional[threading.Thread] = None

    @property
    def latest_features(self) -> Features:
        """Atomic read of latest immutable feature snapshot."""
        return self._latest_features

    def stop(self) -> None:
        """Signal thread and all child watcher subprocesses to cleanly terminate."""
        self._running.clear()

        # Terminate capture process
        if self._parec_proc:
            try:
                self._parec_proc.terminate()
            except Exception:
                pass

        # Terminate subscriber watcher process
        if self._subscribe_proc:
            try:
                self._subscribe_proc.terminate()
            except Exception:
                pass

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def set_sensitivity(self, sens: float) -> None:
        self.analyzer.sensitivity = max(0.1, float(sens))

    def set_visual_delay(self, delay_ms: int) -> None:
        self.analyzer.set_visual_delay(delay_ms)

    def set_mic_mode(self, enabled: bool) -> None:
        """Toggle between microphone input mode and system monitor playback mode."""
        if self.mic_mode == enabled:
            return
        logger.info("Switching AudioCaptureThread mic_mode: %s -> %s", self.mic_mode, enabled)
        self.mic_mode = enabled
        self.restart_capture()

    def restart_capture(self) -> None:
        """Terminate active capture process/stream so it re-spawns with new source/mode."""
        if self._parec_proc:
            try:
                self._parec_proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        """Main capture loop running at ~93.75 hops/second."""
        if self.synthetic_source:
            self._run_synthetic()
        else:
            # Start background pactl subscribe watcher if source is "auto"
            if self.source == "auto":
                self._start_sink_watcher()
            self._run_live_capture()

    def _start_sink_watcher(self) -> None:
        """Spawn background watcher running pactl subscribe to detect sink changes."""
        self._watcher_thread = threading.Thread(target=self._run_sink_watcher, name="SinkWatcherThread", daemon=True)
        self._watcher_thread.start()

    def _run_sink_watcher(self) -> None:
        """Monitor pactl subscribe events for sink or server changes and restart parec if sink changes."""
        has_pactl = shutil.which("pactl") is not None
        if not has_pactl:
            # Polling fallback via wpctl or pactl if pactl subscribe is unavailable
            while self._running.is_set():
                time.sleep(2.0)
                if not self._running.is_set():
                    break
                new_src = get_default_monitor_source()
                if new_src and self._current_source and new_src != self._current_source:
                    logger.info("Default sink changed (polled): %s -> %s", self._current_source, new_src)
                    if self._parec_proc:
                        try:
                            self._parec_proc.terminate()
                        except Exception:
                            pass
            return

        while self._running.is_set():
            try:
                self._subscribe_proc = subprocess.Popen(
                    ["pactl", "subscribe"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                logger.info("Spawned pactl subscribe sink watcher (pid=%d)", self._subscribe_proc.pid)

                while self._running.is_set():
                    line = self._subscribe_proc.stdout.readline()
                    if not line:
                        break

                    # Check for sink or server change events
                    line_lower = line.lower()
                    if "sink" in line_lower or "server" in line_lower:
                        # Debounce slightly before querying default sink
                        time.sleep(0.15)
                        new_source = get_default_monitor_source()
                        if new_source and self._current_source and new_source != self._current_source:
                            logger.info(
                                "Default sink change detected via pactl subscribe: %s -> %s. Restarting parec...",
                                self._current_source,
                                new_source,
                            )
                            # Terminating parec triggers the capture loop to restart with new source <= 2s
                            if self._parec_proc:
                                try:
                                    self._parec_proc.terminate()
                                except Exception:
                                    pass

            except Exception as e:
                logger.debug("pactl subscribe watcher error: %s", e)
            finally:
                if self._subscribe_proc:
                    try:
                        self._subscribe_proc.terminate()
                        self._subscribe_proc.wait(timeout=0.5)
                    except Exception:
                        try:
                            self._subscribe_proc.kill()
                        except Exception:
                            pass
                    self._subscribe_proc = None

            if self._running.is_set():
                time.sleep(1.0)

    def _run_synthetic(self) -> None:
        """Feed synthetic audio frames deterministically in real-time."""
        audio_data = generate_synthetic_audio(self.synthetic_source or "kick120", duration_sec=10.0)
        num_samples = len(audio_data)
        idx = 0
        hop_size = 512
        dt_hop = hop_size / 48000.0

        logger.info("Running synthetic audio capture: %s", self.synthetic_source)
        next_time = time.perf_counter()

        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue

            end_idx = idx + hop_size
            if end_idx <= num_samples:
                chunk = audio_data[idx:end_idx]
                idx = end_idx % num_samples
            else:
                chunk = np.vstack([audio_data[idx:], audio_data[: end_idx - num_samples]])
                idx = end_idx - num_samples

            feat = self.analyzer.process_hop(chunk)
            self._latest_features = feat

            next_time += dt_hop
            sleep_sec = next_time - time.perf_counter()
            if sleep_sec > 0.001:
                time.sleep(sleep_sec)
            elif sleep_sec < -0.1:
                next_time = time.perf_counter()

    def _run_live_capture(self) -> None:
        """Feed live monitor audio from parec or pw-record subprocess with backoff."""
        hop_size = 512
        bytes_per_hop = hop_size * 2 * 4  # 512 samples * 2 channels * 4 bytes (float32)
        backoff_delays = [0.5, 1.0, 2.0, 5.0]
        backoff_idx = 0

        # Check binary availability
        has_parec = shutil.which("parec") is not None
        has_pw_record = shutil.which("pw-record") is not None

        zero_chunk = np.zeros((hop_size, 2), dtype=np.float32)
        dt_hop = hop_size / 48000.0

        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue

            if not has_parec and not has_pw_record:
                # Try sounddevice if available (e.g. on Windows)
                if self._try_sounddevice_capture(hop_size):
                    continue
                # No audio capture utility available: graceful idle fallback
                feat = self.analyzer.process_hop(zero_chunk)
                self._latest_features = feat
                time.sleep(dt_hop)
                continue

            if self.mic_mode:
                target_source = get_default_input_source() or "@DEFAULT_SOURCE@"
            else:
                target_source = self.source
                if target_source == "auto":
                    target_source = get_default_monitor_source() or "@DEFAULT_MONITOR@"
            self._current_source = target_source

            cmd = []
            if has_parec:
                cmd = [
                    "parec",
                    f"--device={target_source}",
                    "--format=float32le",
                    "--rate=48000",
                    "--channels=2",
                    "--latency-msec=20",
                    "--raw",
                ]
            elif has_pw_record:
                pw_target = "@DEFAULT_AUDIO_SOURCE@" if self.mic_mode else "@DEFAULT_AUDIO_SINK@"
                cmd = [
                    "pw-record",
                    "--target",
                    pw_target,
                ]
                if not self.mic_mode:
                    cmd.extend(["-P", '{"stream.capture.sink":true}'])
                cmd.extend([
                    "--raw",
                    "--format=f32",
                    "--rate=48000",
                    "--channels=2",
                    "-",
                ])

            try:
                self._parec_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=bytes_per_hop * 4,
                )
                backoff_idx = 0  # reset on successful spawn
                logger.info("Spawned audio capture process (pid=%d): %s", self._parec_proc.pid, " ".join(cmd))

                while self._running.is_set() and not self._paused.is_set():
                    if self._parec_proc.poll() is not None:
                        break

                    raw_bytes = self._parec_proc.stdout.read(bytes_per_hop)
                    if len(raw_bytes) < bytes_per_hop:
                        break

                    audio_chunk = np.frombuffer(raw_bytes, dtype=np.float32).reshape(-1, 2)
                    feat = self.analyzer.process_hop(audio_chunk)
                    self._latest_features = feat

            except Exception as e:
                logger.warning("Error in audio capture process: %s", e)
            finally:
                if self._parec_proc:
                    try:
                        self._parec_proc.terminate()
                        self._parec_proc.wait(timeout=0.5)
                    except Exception:
                        try:
                            self._parec_proc.kill()
                        except Exception:
                            pass
                    self._parec_proc = None

            if self._running.is_set():
                delay = backoff_delays[min(backoff_idx, len(backoff_delays) - 1)]
                backoff_idx += 1
                logger.info("Audio capture disconnected, retrying in %.1fs...", delay)
                t_end = time.perf_counter() + delay
                while self._running.is_set() and time.perf_counter() < t_end:
                    feat = self.analyzer.process_hop(zero_chunk)
                    self._latest_features = feat
                    time.sleep(dt_hop)

    def _try_sounddevice_capture(self, hop_size: int) -> bool:
        """Capture via sounddevice on Windows or PortAudio-enabled environments."""
        try:
            import sounddevice as sd
        except Exception:
            return False

        try:
            device_idx = None
            extra_settings = None
            sample_rate = 48000
            channels = 2

            if self.mic_mode:
                device_idx = None  # Default input device
                try:
                    default_input_info = sd.query_devices(kind="input")
                    max_in_ch = int(default_input_info.get("max_input_channels", 2))
                    channels = 1 if max_in_ch == 1 else 2
                    default_sr = int(default_input_info.get("default_samplerate", 48000))
                    if default_sr in (44100, 48000):
                        sample_rate = default_sr
                except Exception as e:
                    logger.debug("Query input device info fallback: %s", e)
                    channels = 1  # Safe mono fallback for mics
            else:
                if sys.platform == "win32":
                    try:
                        wasapi_api_idx = next(
                            (i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api.get("name", "")),
                            None,
                        )
                        if wasapi_api_idx is not None:
                            extra_settings = sd.WasapiSettings(loopback=True)
                            default_output = sd.query_hostapis(wasapi_api_idx).get("default_output_device")
                            if default_output is not None and default_output >= 0:
                                device_idx = default_output
                                dev_info = sd.query_devices(device_idx)
                                dev_sr = int(dev_info.get("default_samplerate", 48000))
                                if dev_sr in (44100, 48000):
                                    sample_rate = dev_sr
                                dev_ch = int(dev_info.get("max_output_channels", 2))
                                if dev_ch >= 2:
                                    channels = 2
                    except Exception as e:
                        logger.debug("WASAPI loopback configuration error: %s", e)

            cur_mode = self.mic_mode
            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                blocksize=hop_size,
                device=device_idx,
                extra_settings=extra_settings,
            ) as stream:
                logger.info("Spawned sounddevice capture stream (mic_mode=%s, channels=%d, rate=%d)", cur_mode, channels, sample_rate)
                while self._running.is_set() and not self._paused.is_set() and self.mic_mode == cur_mode:
                    data, _ = stream.read(hop_size)
                    if data.ndim == 1:
                        chunk = np.column_stack([data, data])
                    elif data.shape[1] == 1:
                        chunk = np.repeat(data, 2, axis=1)
                    else:
                        chunk = data[:, :2]
                    feat = self.analyzer.process_hop(chunk)
                    self._latest_features = feat
            return True
        except Exception as e:
            logger.debug("sounddevice capture error: %s", e)
            return False
