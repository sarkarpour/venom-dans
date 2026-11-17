"""Audio capture thread reading from default monitor sink or synthetic generator."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from typing import Optional

import numpy as np

from ferrowidget.audio.analysis import AudioAnalyzer, Features
from ferrowidget.audio.synthetic import generate_synthetic_audio

logger = logging.getLogger(__name__)


def get_default_monitor_source() -> Optional[str]:
    """Query default sink and append .monitor."""
    try:
        proc = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if proc.returncode == 0:
            sink = proc.stdout.strip()
            if sink:
                return f"{sink}.monitor"
    except Exception as e:
        logger.debug("Failed to query default sink via pactl: %s", e)

    # Check for PipeWire default monitor
    return "@DEFAULT_MONITOR@"


class AudioCaptureThread(threading.Thread):
    """Background worker thread capturing system audio and running DSP analysis."""

    def __init__(
        self,
        source: str = "auto",
        sensitivity: float = 1.0,
        visual_delay_ms: int = 0,
        synthetic_source: Optional[str] = None,
    ):
        super().__init__(name="AudioCaptureThread", daemon=True)
        self.source = source
        self.synthetic_source = synthetic_source
        self.analyzer = AudioAnalyzer(sensitivity=sensitivity)
        self.analyzer.set_visual_delay(visual_delay_ms)

        self._running = threading.Event()
        self._running.set()
        self._paused = threading.Event()

        # Atomic reference swap for thread-safe access from GUI thread
        self._latest_features: Features = self.analyzer._make_default_features()

        self._current_sink = ""
        self._parec_proc: Optional[subprocess.Popen] = None

    @property
    def latest_features(self) -> Features:
        """Atomic read of latest immutable feature snapshot."""
        return self._latest_features

    def stop(self) -> None:
        """Signal thread to cleanly terminate."""
        self._running.clear()
        if self._parec_proc:
            try:
                self._parec_proc.terminate()
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

    def run(self) -> None:
        """Main capture loop running at ~93.75 hops/second."""
        if self.synthetic_source:
            self._run_synthetic()
        else:
            self._run_live_capture()

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
                # No audio capture utility available: graceful idle fallback
                feat = self.analyzer.process_hop(zero_chunk)
                self._latest_features = feat
                time.sleep(dt_hop)
                continue

            target_source = self.source
            if target_source == "auto":
                target_source = get_default_monitor_source() or "@DEFAULT_MONITOR@"

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
                cmd = [
                    "pw-record",
                    "--format=f32",
                    "--rate=48000",
                    "--channels=2",
                    "-",
                ]

            try:
                self._parec_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=bytes_per_hop * 4,
                )
                backoff_idx = 0  # reset on successful spawn
                logger.info("Spawned audio capture process: %s", " ".join(cmd))

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
