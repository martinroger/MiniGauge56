#!/usr/bin/env python3
"""
MiniGauge CAN Binary Log Trimmer & Slicer
=========================================
A lightweight zero-dependency tool to trim, recut, and extract clean snippets
from MiniGauge 16-byte packed binary CAN logs (*.bin).

Features:
- Slicing by time bounds (--start <sec> --end <sec>) or frame index (--from-frame <N> --to-frame <M>).
- Automatic timestamp zero-rebasing by default (starts at t = 0.0s) with --preserve-timestamps flag.
- Optional CAN arbitration ID filtering (--ids 0x100,0x301).
- Strict non-destructive invariant: Never overwrites the source log file.
- Automatic suffixing with collision prevention (<stem>_cut_<start>s_<end>s.bin).
- Dual interface: Fast CLI utility and interactive browser GUI (--gui / --browser).
"""

import argparse
import glob
import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    CanFrame,
    read_bin_file,
    find_bin_files,
    BaseAppHandler,
    start_server,
    RECORD_STRUCT,
    RECORD_SIZE,
)

# Compatibility aliases
RawCanFrame = CanFrame
read_raw_log = read_bin_file



def generate_safe_output_path(input_path: Path, start_s: float, end_s: float, explicit_out: Optional[Path] = None) -> Path:
    """Generates a safe non-colliding output path ensuring input is NEVER overwritten."""
    input_res = input_path.resolve()
    if explicit_out:
        out_res = explicit_out.resolve()
        if out_res == input_res:
            raise ValueError(f"Safety Violation: Target '{explicit_out}' is the same as source file. Refusing to overwrite original log.")
        return explicit_out

    stem = input_path.stem
    parent = input_path.parent
    base_name = f"{stem}_cut_{start_s:.1f}s_{end_s:.1f}s.bin"
    candidate = parent / base_name

    if candidate.resolve() == input_res:
        candidate = parent / f"{stem}_cut_{start_s:.1f}s_{end_s:.1f}s_01.bin"

    counter = 1
    while candidate.exists():
        if candidate.resolve() == input_res:
            pass
        candidate = parent / f"{stem}_cut_{start_s:.1f}s_{end_s:.1f}s_{counter:02d}.bin"
        counter += 1

    return candidate


def trim_log(
    input_path: Path,
    output_path: Optional[Path] = None,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
    from_frame: Optional[int] = None,
    to_frame: Optional[int] = None,
    rebase_zero: bool = True,
    allowed_ids: Optional[List[int]] = None,
) -> Tuple[Path, int, float]:
    """
    Trims a binary CAN log and writes the cut to disk.
    Returns: (output_path, num_frames_written, duration_s)
    """
    if not input_path.is_file():
        raise FileNotFoundError(f"Input log file not found: {input_path}")

    frames = read_raw_log(input_path)
    if not frames:
        raise ValueError(f"Log file is empty or corrupt: {input_path}")

    total_frames = len(frames)
    max_duration_s = frames[-1].rel_s

    # Resolve frame index boundaries
    start_idx = 0
    end_idx = total_frames - 1

    if from_frame is not None:
        start_idx = max(0, min(total_frames - 1, from_frame))
    elif start_s is not None:
        start_idx = next((i for i, f in enumerate(frames) if f.rel_s >= start_s), total_frames - 1)

    if to_frame is not None:
        end_idx = max(0, min(total_frames - 1, to_frame))
    elif end_s is not None:
        end_idx = next((i for i, f in enumerate(frames) if f.rel_s > end_s), total_frames) - 1
        end_idx = max(start_idx, end_idx)

    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx

    actual_start_s = frames[start_idx].rel_s
    actual_end_s = frames[end_idx].rel_s

    out_file = generate_safe_output_path(input_path, actual_start_s, actual_end_s, output_path)

    # Filter frames
    id_set = set(allowed_ids) if allowed_ids else None
    selected_frames = []
    for i in range(start_idx, end_idx + 1):
        f = frames[i]
        if id_set is not None and f.can_id not in id_set:
            continue
        selected_frames.append(f)

    if not selected_frames:
        raise ValueError("Zero frames matched the requested time/ID criteria.")

    base_ts = selected_frames[0].ts_ms if rebase_zero else 0

    # Pack and write records
    out_bytes = bytearray()
    for f in selected_frames:
        out_ts = (f.ts_ms - base_ts) if rebase_zero else f.ts_ms
        payload = f.data[:8].ljust(8, b"\x00")
        out_bytes.extend(RECORD_STRUCT.pack(out_ts, f.can_id, f.dlc, payload))

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(out_bytes)

    duration_s = (selected_frames[-1].ts_ms - selected_frames[0].ts_ms) / 1000.0
    return out_file, len(selected_frames), duration_s


def get_preview_data(filepath: Path, max_samples: int = 400) -> Dict[str, Any]:
    """Extracts decimated waveform summary and GPS telemetry for GUI slider preview."""
    frames = read_raw_log(filepath)
    if not frames:
        return {"duration_s": 0.0, "total_frames": 0, "times": [], "speeds": [], "rpms": [], "gps": []}

    duration_s = frames[-1].rel_s
    total_frames = len(frames)

    raw_gps = []
    times = []
    speeds = []
    rpms = []

    cur_speed = 0.0
    cur_rpm = 0.0

    step = max(1, len(frames) // max_samples)
    for i, f in enumerate(frames):
        # Heuristic decoding of speed/RPM frequencies if present
        if f.can_id == 0x300 and len(f.data) >= 4:
            try:
                cur_speed = struct.unpack("<f", f.data[:4])[0] * 0.2444
            except Exception:
                pass
        elif f.can_id == 0x301 and len(f.data) >= 4:
            try:
                cur_rpm = struct.unpack("<f", f.data[:4])[0] * 30.0
            except Exception:
                pass
        elif f.can_id == 0x601 and len(f.data) >= 8:
            # RaceBox GPS Latitude & Longitude (32-bit signed int, 1e-7 deg scale)
            try:
                lat_raw, lon_raw = struct.unpack("<ii", f.data[:8])
                lat, lon = lat_raw * 1e-7, lon_raw * 1e-7
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                    raw_gps.append({
                        "t": round(f.rel_s, 2),
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                    })
            except Exception:
                pass

        if i % step == 0:
            times.append(round(f.rel_s, 2))
            speeds.append(round(max(0.0, cur_speed), 1))
            rpms.append(round(max(0.0, cur_rpm), 0))

    # Decimate GPS track to at most ~1200 points for smooth map rendering
    if len(raw_gps) > 1200:
        step_gps = max(1, len(raw_gps) // 1200)
        gps_points = raw_gps[::step_gps]
        if raw_gps[-1] != gps_points[-1]:
            gps_points.append(raw_gps[-1])
    else:
        gps_points = raw_gps

    return {
        "filename": filepath.name,
        "duration_s": round(duration_s, 2),
        "total_frames": total_frames,
        "times": times,
        "speeds": speeds,
        "rpms": rpms,
        "gps": gps_points,
    }


# ==============================================================================
# BROWSER GUI HTTP SERVER
# ==============================================================================

class TrimmerHttpHandler(BaseAppHandler):
    def do_GET(self):
        if self.path.startswith("/static/"):
            if self.serve_static(self.path):
                return

        path, query = self.parse_query()
        if path in ("/", "/index.html"):
            self.send_html(build_trimmer_html())

        elif path == "/api/logs":
            logs = [{"filename": p.name, "size": p.stat().st_size} for p in find_bin_files()]
            self.send_json(logs)

        elif path == "/api/preview":
            fn = self.get_query_param("file")
            target = SCRIPT_DIR / fn
            if not target.is_file():
                target = Path(fn)
            if not target.is_file():
                self.send_json({"error": "Log file not found"}, status=404)
                return
            self.send_json(get_preview_data(target))

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        path, _ = self.parse_query()
        if path == "/api/trim":
            try:
                params = self.read_json_body()
                filename = params.get("filename", "")
                start_s = float(params.get("start_s", 0.0))
                end_s = float(params.get("end_s", 0.0))
                rebase_zero = bool(params.get("rebase_zero", True))
                ids_str = params.get("ids", "").strip()

                allowed_ids = None
                if ids_str:
                    allowed_ids = [
                        int(x.strip(), 16) if x.strip().lower().startswith("0x") else int(x.strip())
                        for x in ids_str.split(",")
                        if x.strip()
                    ]

                src_path = SCRIPT_DIR / filename
                if not src_path.is_file():
                    src_path = Path(filename)

                out_path, n_frames, dur = trim_log(
                    src_path,
                    start_s=start_s,
                    end_s=end_s,
                    rebase_zero=rebase_zero,
                    allowed_ids=allowed_ids,
                )

                self.send_json({
                    "status": "ok",
                    "output_file": out_path.name,
                    "output_path": str(out_path),
                    "frames": n_frames,
                    "duration_s": round(dur, 2),
                    "size_bytes": out_path.stat().st_size,
                })
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, status=400)
        else:
            self.send_error(404, "Not Found")


def build_trimmer_html() -> str:
    template_path = SCRIPT_DIR / "web" / "templates" / "trim_log.html"
    return template_path.read_text(encoding="utf-8")


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="MiniGauge CAN Binary Log Trimmer & Slicer")
    parser.add_argument("input", nargs="?", type=Path, help="Input *.bin CAN log file")
    parser.add_argument("--start", "-s", type=float, help="Start time in seconds")
    parser.add_argument("--end", "-e", type=float, help="End time in seconds")
    parser.add_argument("--from-frame", type=int, help="Start frame index (0-based)")
    parser.add_argument("--to-frame", type=int, help="End frame index (inclusive)")
    parser.add_argument("--output", "-o", type=Path, help="Output *.bin file path")
    parser.add_argument("--preserve-timestamps", action="store_true", help="Keep raw hardware timestamps (default: zero-rebase)")
    parser.add_argument("--ids", type=str, help="Comma-separated CAN IDs to include (e.g. 0x100,0x301)")
    parser.add_argument("--gui", "--browser", "--web", action="store_true", help="Launch interactive browser GUI")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--port", "-p", type=int, default=8199, help="GUI HTTP server port (default: 8199)")

    args = parser.parse_args()

    if args.gui or not args.input:
        start_server(
            TrimmerHttpHandler,
            port=args.port,
            open_browser=not args.no_browser,
            server_name="MiniGauge CAN Log Trimmer",
        )
        return


    allowed_ids = None
    if args.ids:
        allowed_ids = [int(x.strip(), 16) if x.strip().lower().startswith("0x") else int(x.strip()) for x in args.ids.split(",") if x.strip()]

    rebase_zero = not args.preserve_timestamps

    try:
        out_path, n_frames, dur = trim_log(
            args.input,
            output_path=args.output,
            start_s=args.start,
            end_s=args.end,
            from_frame=args.from_frame,
            to_frame=args.to_frame,
            rebase_zero=rebase_zero,
            allowed_ids=allowed_ids,
        )
        print(f"✓ Trimmed log successfully created: {out_path}")
        print(f"  Frames: {n_frames} | Duration: {dur:.2f}s | Size: {out_path.stat().st_size / 1024:.1f} KB")
        print(f"  Zero-rebased: {rebase_zero}")
    except Exception as e:
        print(f"Error trimming log: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

