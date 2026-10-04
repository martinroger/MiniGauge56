"""MiniGauge Multi-Format CAN Log Ingestion Engine.

Supports:
- MiniGauge 16-byte packed binary (.bin) files (via can_core.py)
- SocketCAN candump (.log) files
- Vector ASCII (.asc) files

Zero pip dependencies (Python 3 stdlib only).
"""

from pathlib import Path
import re
from typing import List, Optional, Sequence, Tuple
from .can_core import CanFrame, natural_sort_key, read_bin_file


CANDUMP_LINE_RE = re.compile(
    r"^\s*(?:\((\d+\.?\d*)\))?\s*([a-zA-Z0-9_-]+)\s+([0-9a-fA-F]{1,8})#([0-9a-fA-F]*)\s*$"
)

VECTOR_ASC_LINE_RE = re.compile(
    r"^\s*(\d+\.?\d*)\s+(\d+)\s+([0-9a-fA-F]+)x?\s+(Rx|Tx)\s+d\s+(\d+)\s+((?:[0-9a-fA-F]{2}\s*)+)"
)


def parse_candump_log(log_path: Path) -> List[CanFrame]:
    """Parses a SocketCAN candump formatted text file into CanFrame objects."""
    frames: List[CanFrame] = []
    first_time_s: Optional[float] = None

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith(";"):
                continue

            match = CANDUMP_LINE_RE.match(line)
            if not match:
                continue

            t_str, _interface, can_id_hex, data_hex = match.groups()
            try:
                can_id = int(can_id_hex, 16)
                data = bytes.fromhex(data_hex)
                dlc = len(data)
                time_s = float(t_str) if t_str else 0.0

                if first_time_s is None:
                    first_time_s = time_s
                rel_s = max(0.0, time_s - first_time_s)
                ts_ms = int(rel_s * 1000.0)

                frames.append(CanFrame(ts_ms, rel_s, can_id, dlc, data))
            except (ValueError, TypeError):
                continue

    return frames


def parse_asc_log(log_path: Path) -> List[CanFrame]:
    """Parses a Vector ASCII (.asc) formatted text file into CanFrame objects."""
    frames: List[CanFrame] = []
    first_time_s: Optional[float] = None

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("date") or line.startswith("base"):
                continue

            match = VECTOR_ASC_LINE_RE.match(line)
            if not match:
                continue

            t_str, _ch, can_id_hex, _dir, dlc_str, bytes_str = match.groups()
            try:
                can_id = int(can_id_hex, 16)
                dlc = int(dlc_str)
                data_tokens = bytes_str.split()
                data = bytes(int(b, 16) for b in data_tokens[:dlc])
                time_s = float(t_str)

                if first_time_s is None:
                    first_time_s = time_s
                rel_s = max(0.0, time_s - first_time_s)
                ts_ms = int(rel_s * 1000.0)

                frames.append(CanFrame(ts_ms, rel_s, can_id, dlc, data))
            except (ValueError, TypeError):
                continue

    return frames


def detect_log_format(log_path: Path) -> str:
    """Detects the log file format: 'bin', 'candump', 'asc', or 'unknown'."""
    suffix = log_path.suffix.lower()
    if suffix == ".bin":
        return "bin"
    if suffix == ".asc":
        return "asc"

    # Inspect first few lines of text file
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(25):
                line = f.readline()
                if not line:
                    break
                if CANDUMP_LINE_RE.match(line.strip()):
                    return "candump"
                if VECTOR_ASC_LINE_RE.match(line.strip()) or "base hex" in line.lower():
                    return "asc"
    except Exception:
        pass

    return "candump" if suffix == ".log" else "unknown"


def load_log_file(log_path: Path) -> List[CanFrame]:
    """Loads CAN frames from any supported log file (.bin, candump .log, .asc)."""
    fmt = detect_log_format(log_path)
    if fmt == "bin":
        return read_bin_file(log_path)
    elif fmt == "asc":
        return parse_asc_log(log_path)
    elif fmt == "candump":
        return parse_candump_log(log_path)
    else:
        # Try candump then asc as fallback
        frames = parse_candump_log(log_path)
        if not frames:
            frames = parse_asc_log(log_path)
        return frames


def find_all_log_files(
    specific: Optional[Path] = None,
    search_dirs: Optional[Sequence[Path]] = None,
) -> List[Path]:
    """Discovers all .bin, .log, and .asc files across search directories."""
    if specific and specific.is_file():
        return [specific]

    tools_dir = Path(__file__).resolve().parent.parent
    cwd = Path(".").resolve()
    fixtures_dir = tools_dir / "fixtures"

    if search_dirs is None:
        dirs = [tools_dir, fixtures_dir]
        if cwd not in dirs:
            dirs.append(cwd)
    else:
        dirs = list(search_dirs)

    seen = set()
    found: List[Path] = []

    for d in dirs:
        if not d.is_dir():
            continue
        for ext in ("*.bin", "*.log", "*.asc"):
            for p in d.glob(ext):
                res = p.resolve()
                if res not in seen and p.is_file() and p.stat().st_size > 0:
                    seen.add(res)
                    found.append(p)

    found.sort(key=natural_sort_key)
    return found
