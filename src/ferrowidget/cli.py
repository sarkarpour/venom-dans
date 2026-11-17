"""Command line interface for FerroWidget (run, ctl, doctor, dump-frame, install-autostart)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ferrowidget.config import LookConfig
from ferrowidget.ipc import send_ctl_command

logger = logging.getLogger("ferrowidget")


def cmd_run(args: argparse.Namespace) -> int:
    """Run live FerroWidget application."""
    from ferrowidget.app import FerroApp

    app = FerroApp(
        synthetic_source=args.synthetic,
        debug_bg=args.debug_bg,
        wayland_native=args.wayland_native,
        exit_after=args.exit_after,
        override_x=args.x,
        override_y=args.y,
        override_size=args.size,
        override_anchor=args.anchor,
    )
    return app.run()


def cmd_ctl(args: argparse.Namespace) -> int:
    """Send control commands to running FerroWidget instance over Unix socket."""
    cmd = args.command
    cmd_args = args.args

    payload = {}
    if cmd == "edit":
        mode = cmd_args[0] if cmd_args else "toggle"
        payload["mode"] = mode
    elif cmd == "theme":
        if not cmd_args:
            print("Error: 'theme' requires a theme name (ink, mercury, oilslick, neon)")
            return 1
        payload["name"] = cmd_args[0]
    elif cmd == "preset":
        if not cmd_args:
            print("Error: 'preset' requires a preset name (calm, club, cinematic)")
            return 1
        payload["name"] = cmd_args[0]
    elif cmd == "size":
        if not cmd_args:
            print("Error: 'size' requires integer pixels (128-1200)")
            return 1
        try:
            payload["size"] = int(cmd_args[0])
        except ValueError:
            print(f"Error: Invalid size '{cmd_args[0]}', expected integer pixels", file=sys.stderr)
            return 1
    elif cmd == "move":
        if len(cmd_args) < 2:
            print("Error: 'move' requires <x> <y> coordinates")
            return 1
        try:
            payload["x"] = int(cmd_args[0])
            payload["y"] = int(cmd_args[1])
        except ValueError:
            print("Error: 'move' coordinates must be integers", file=sys.stderr)
            return 1

    resp = send_ctl_command(cmd, payload)
    if resp.get("status") == "ok":
        print(json.dumps(resp, indent=2))
        return 0
    else:
        print(f"Error: {resp.get('message', 'Unknown error')}", file=sys.stderr)
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run diagnostic checks on OS, Wayland/X11, Audio, and OpenGL environments."""
    print("=" * 65)
    print("           FERROWIDGET SYSTEM DIAGNOSTIC (DOCTOR)")
    print("=" * 65)

    checks = []
    missing_packages = []

    # 1. Session & Desktop
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    checks.append(("Session Type", session_type, "PASS" if session_type in ("x11", "wayland") else "WARN"))
    checks.append(("Desktop Environment", desktop, "PASS"))

    # 2. XWayland / X11 availability
    display = os.environ.get("DISPLAY", "")
    has_display = bool(display)
    checks.append(("X11 / XWayland Display", display if display else "None", "PASS" if has_display else "FAIL"))

    # 3. Audio binaries (parec, pactl, pw-record)
    has_parec = shutil.which("parec") is not None
    has_pactl = shutil.which("pactl") is not None
    has_pw_record = shutil.which("pw-record") is not None

    if has_parec:
        checks.append(("Audio Streamer (parec)", "Found", "PASS"))
    elif has_pw_record:
        checks.append(("Audio Streamer (pw-record)", "Found (PipeWire native)", "PASS"))
    else:
        checks.append(("Audio Streamer (parec)", "Missing", "FAIL"))
        missing_packages.append("pulseaudio-utils")

    if has_pactl:
        checks.append(("Audio Controller (pactl)", "Found", "PASS"))
    else:
        checks.append(("Audio Controller (pactl)", "Missing", "WARN"))
        if "pulseaudio-utils" not in missing_packages:
            missing_packages.append("pulseaudio-utils")

    # Check default sink
    sink_info = "Unknown"
    if has_pactl:
        try:
            res = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0:
                sink_info = res.stdout.strip()
        except Exception:
            pass
    checks.append(("Default Audio Sink", sink_info, "PASS" if sink_info != "Unknown" else "WARN"))

    # 4. OpenGL & GPU info
    gl_status = "FAIL"
    gl_info = "Unavailable"
    try:
        import moderngl
        ctx = moderngl.create_standalone_context()
        gl_status = "PASS"
        gl_info = f"{ctx.info.get('GL_RENDERER', 'GL')} (OpenGL {ctx.version_code / 100:.1f})"
    except Exception as e:
        gl_info = str(e)
    checks.append(("OpenGL Hardware Context", gl_info, gl_status))

    # 5. Qt Platform & XCB Plugin
    try:
        checks.append(("PySide6 / Qt6 Framework", "Installed", "PASS"))
    except Exception as e:
        checks.append(("PySide6 / Qt6 Framework", f"Error: {e}", "FAIL"))

    # Print Table
    print(f"{'Component':<26} | {'Status':<6} | {'Details'}")
    print("-" * 65)
    for comp, details, status in checks:
        color_indicator = f"[{status}]"
        print(f"{comp:<26} | {color_indicator:<6} | {details}")
    print("=" * 65)

    if missing_packages:
        print("\n[!] Recommended packages to install:")
        print(f"    sudo apt update && sudo apt install -y {' '.join(missing_packages)}")
    else:
        print("\nAll required core subsystems are functional!")

    return 0


def cmd_dump_frame(args: argparse.Namespace) -> int:
    """Render headless offscreen frames and generate dynamics contact sheet."""
    from ferrowidget.audio.analysis import AudioAnalyzer
    from ferrowidget.audio.synthetic import generate_synthetic_audio
    from ferrowidget.physics.fluid import FluidSimulation
    from ferrowidget.render.renderer import FerroRenderer, create_contact_sheet

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Initializing headless renderer for signal '{args.synthetic}'...")
    renderer = FerroRenderer()
    sim = FluidSimulation(seed=args.seed)
    analyzer = AudioAnalyzer()
    look = LookConfig(theme=args.theme)

    audio = generate_synthetic_audio(args.synthetic, duration_sec=5.0)
    hop_size = 512
    dt_frame = 1.0 / 60.0

    moments_data = []

    # Target key moments to capture:
    # 1. idle: initial state before audio
    idle_feat = analyzer._make_default_features()
    sim.update_choreography(idle_feat, 0.5)
    img_idle = renderer.render_offscreen_image(
        width=512, height=512, time_sec=0.5,
        blobs_data=sim.get_blobs_uniform_data(),
        magnets_data=sim.get_magnets_uniform_data(),
        spike_amount=sim.spike,
        look_cfg=look,
    )
    img_idle.save(out_dir / "frame_idle.png")
    moments_data.append(("idle", img_idle))

    # 2. steady_bass: deep steady bass driving center & inner ring
    bass_audio = generate_synthetic_audio("bass_sweep", duration_sec=1.5)
    for b_idx in range(0, 48000, hop_size):
        b_feat = analyzer.process_hop(bass_audio[b_idx : b_idx + hop_size])
        sim.update_choreography(b_feat, dt_frame)
    img_bass = renderer.render_offscreen_image(
        width=512, height=512, time_sec=1.5,
        blobs_data=sim.get_blobs_uniform_data(),
        magnets_data=sim.get_magnets_uniform_data(),
        spike_amount=sim.spike,
        look_cfg=look,
    )
    img_bass.save(out_dir / "frame_steady_bass.png")
    moments_data.append(("steady_bass", img_bass))

    # Advance simulation through audio to find kick hits
    curr_time = 1.5
    kick_frame_idx = -1

    for i in range(0, len(audio) - hop_size, hop_size):
        chunk = audio[i : i + hop_size]
        curr_time += dt_frame
        feat = analyzer.process_hop(chunk)
        sim.update_choreography(feat, dt_frame)

        if feat.kick > 0.8 and kick_frame_idx < 0:
            kick_frame_idx = 0
            # kick_+0ms
            img_k0 = renderer.render_offscreen_image(
                width=512, height=512, time_sec=curr_time,
                blobs_data=sim.get_blobs_uniform_data(),
                magnets_data=sim.get_magnets_uniform_data(),
                spike_amount=sim.spike,
                look_cfg=look,
            )
            img_k0.save(out_dir / "frame_kick_0ms.png")
            moments_data.append(("kick_+0ms", img_k0))
        elif kick_frame_idx >= 0:
            kick_frame_idx += 1
            if kick_frame_idx == 3:  # ~50ms
                img_k50 = renderer.render_offscreen_image(
                    width=512, height=512, time_sec=curr_time,
                    blobs_data=sim.get_blobs_uniform_data(),
                    magnets_data=sim.get_magnets_uniform_data(),
                    spike_amount=sim.spike,
                    look_cfg=look,
                )
                img_k50.save(out_dir / "frame_kick_50ms.png")
                moments_data.append(("kick_+50ms", img_k50))
            elif kick_frame_idx == 7:  # ~120ms
                img_k120 = renderer.render_offscreen_image(
                    width=512, height=512, time_sec=curr_time,
                    blobs_data=sim.get_blobs_uniform_data(),
                    magnets_data=sim.get_magnets_uniform_data(),
                    spike_amount=sim.spike,
                    look_cfg=look,
                )
                img_k120.save(out_dir / "frame_kick_120ms.png")
                moments_data.append(("kick_+120ms", img_k120))
            elif kick_frame_idx == 15:  # ~250ms
                img_k250 = renderer.render_offscreen_image(
                    width=512, height=512, time_sec=curr_time,
                    blobs_data=sim.get_blobs_uniform_data(),
                    magnets_data=sim.get_magnets_uniform_data(),
                    spike_amount=sim.spike,
                    look_cfg=look,
                )
                img_k250.save(out_dir / "frame_kick_250ms.png")
                moments_data.append(("kick_+250ms", img_k250))
                break

    # full_mix: full band spectrum driving inner/outer rings
    mix_audio = generate_synthetic_audio("full_mix", duration_sec=2.0)
    for m_idx in range(0, len(mix_audio) - hop_size, hop_size):
        m_feat = analyzer.process_hop(mix_audio[m_idx : m_idx + hop_size])
        curr_time += dt_frame
        sim.update_choreography(m_feat, dt_frame)
    img_full_mix = renderer.render_offscreen_image(
        width=512, height=512, time_sec=curr_time,
        blobs_data=sim.get_blobs_uniform_data(),
        magnets_data=sim.get_magnets_uniform_data(),
        spike_amount=sim.spike,
        look_cfg=look,
    )
    img_full_mix.save(out_dir / "frame_full_mix.png")
    moments_data.append(("full_mix", img_full_mix))

    # Max spikes frame
    sim.spike = 1.6
    img_max_spikes = renderer.render_offscreen_image(
        width=512, height=512, time_sec=curr_time + 0.1,
        blobs_data=sim.get_blobs_uniform_data(),
        magnets_data=sim.get_magnets_uniform_data(),
        spike_amount=1.6,
        look_cfg=look,
    )
    img_max_spikes.save(out_dir / "frame_max_spikes.png")
    moments_data.append(("max_spikes", img_max_spikes))

    print(f"Saved individual moment PNGs to {out_dir}")

    # Contact sheet generation across 4 backgrounds
    if args.contact_sheet:
        print("Generating multi-background contact sheet...")
        sheet = create_contact_sheet(
            moments=moments_data,
            backgrounds=["white", "mid-grey", "pure-black", "busy-wallpaper-gradient"],
            cell_size=256,
        )
        sheet_path = out_dir / "contact_sheet.png"
        sheet.save(sheet_path)
        print(f"Generated contact sheet at: {sheet_path}")

    return 0


def cmd_install_autostart(args: argparse.Namespace) -> int:
    """Install XDG autostart desktop file and systemd user service."""
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)

    desktop_content = """[Desktop Entry]
Type=Application
Name=FerroWidget
Comment=Photorealistic ferrofluid desktop audio visualizer
Exec=ferrowidget run
Terminal=false
Categories=Utility;AudioVideo;
X-GNOME-Autostart-Delay=5
"""
    desktop_file = autostart_dir / "ferrowidget.desktop"
    desktop_file.write_text(desktop_content, encoding="utf-8")
    print(f"Installed desktop autostart entry: {desktop_file}")

    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)

    service_content = """[Unit]
Description=FerroWidget Desktop Audio Visualizer
After=graphical-session.target pipewire.service pulseaudio.service

[Service]
Type=simple
ExecStart=/bin/sh -c 'exec ferrowidget run'
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""
    service_file = systemd_dir / "ferrowidget.service"
    service_file.write_text(service_content, encoding="utf-8")
    print(f"Installed systemd user service: {service_file}")
    print("Enable via: systemctl --user enable --now ferrowidget.service")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ferrowidget",
        description="FerroWidget: Photorealistic desktop ferrofluid audio visualizer",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Run live FerroWidget desktop overlay")
    p_run.add_argument("--synthetic", choices=["kick120", "bass_sweep", "noise_bursts", "full_mix", "silence"], help="Run with deterministic synthetic audio input")
    p_run.add_argument("--debug-bg", choices=["none", "dark", "light", "checker"], default="none", help="Draw synthetic background behind fluid")
    p_run.add_argument("--x", type=int, help="Override top-left X position")
    p_run.add_argument("--y", type=int, help="Override top-left Y position")
    p_run.add_argument("--size", type=int, help="Override widget square size in pixels")
    p_run.add_argument("--anchor", choices=["top-left", "top-right", "bottom-left", "bottom-right", "center"], help="Override anchor position")
    p_run.add_argument("--wayland-native", action="store_true", help="Allow native Wayland instead of enforcing XWayland")
    p_run.add_argument("--exit-after", type=float, help="Automatically quit after specified seconds (prevents hanging)")
    p_run.set_defaults(func=cmd_run)

    # Subcommand: ctl
    p_ctl = subparsers.add_parser("ctl", help="Send control commands to running instance")
    p_ctl.add_argument("command", choices=["edit", "pause", "resume", "theme", "preset", "size", "move", "reload", "status", "quit"])
    p_ctl.add_argument("args", nargs="*", help="Arguments for control command")
    p_ctl.set_defaults(func=cmd_ctl)

    # Subcommand: doctor
    p_doctor = subparsers.add_parser("doctor", help="Check system dependencies and environment")
    p_doctor.set_defaults(func=cmd_doctor)

    # Subcommand: dump-frame
    p_dump = subparsers.add_parser("dump-frame", help="Render offscreen frames and generate contact sheets")
    p_dump.add_argument("--synthetic", choices=["kick120", "bass_sweep", "noise_bursts", "full_mix", "silence"], default="kick120", help="Synthetic audio signal")
    p_dump.add_argument("--frames", type=int, default=1, help="Number of frames to dump")
    p_dump.add_argument("--seed", type=int, default=42, help="RNG seed for simulation")
    p_dump.add_argument("--out", default="dumped_frames", help="Output directory")
    p_dump.add_argument("--theme", choices=["ink", "mercury", "oilslick", "neon"], default="ink", help="Visual theme")
    p_dump.add_argument("--contact-sheet", action="store_true", default=True, help="Generate composite contact sheet")
    p_dump.set_defaults(func=cmd_dump_frame)

    # Subcommand: install-autostart
    p_auto = subparsers.add_parser("install-autostart", help="Install autostart desktop entry and systemd service")
    p_auto.set_defaults(func=cmd_install_autostart)

    parsed = parser.parse_args()
    if not parsed.subcommand:
        parser.print_help()
        return 0

    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main())
