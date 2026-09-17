"""MiniGauge CAN Ingestion Core.

Provides binary frame layout specifications, frame decoders,
file search functions, and natural alphanumeric sorting routines.
Zero pip dependencies (Python 3 stdlib only).
"""

import re
import struct
from pathlib import Path
from typing import Any, List, Optional, Sequence

RECORD_FORMAT = "<IHB8sx"
RECORD_STRUCT = struct.Struct(RECORD_FORMAT)
RECORD_SIZE = 16
CAN_STRUCT = RECORD_STRUCT


class CanFrame:
    """Represents a 16-byte packed MiniGauge CAN telemetry frame.

    Compatible with both decode.py 5-arg signature and
    gear_lab.py/trim_log.py 4-arg signatures and attribute aliases.
    """

    __slots__ = ("timestamp_ms", "time_rel_s", "can_id", "dlc", "data")

    def __init__(self, timestamp_ms: int, *args, **kwargs):
        self.timestamp_ms = timestamp_ms
        if len(args) == 4:
            # decode.py order: (time_rel_s, can_id, dlc, data)
            self.time_rel_s, self.can_id, self.dlc, self.data = args
        elif len(args) == 3:
            # gear_lab.py order: (can_id, dlc, data)
            self.can_id, self.dlc, self.data = args
            self.time_rel_s = kwargs.get("time_rel_s", kwargs.get("rel_s", 0.0))
        else:
            self.time_rel_s = kwargs.get("time_rel_s", kwargs.get("rel_s", 0.0))
            self.can_id = kwargs.get("can_id", 0)
            self.dlc = kwargs.get("dlc", 0)
            self.data = kwargs.get("data", b"")

    @property
    def ts_ms(self) -> int:
        """Alias for timestamp_ms (used by trim_log.py)."""
        return self.timestamp_ms

    @ts_ms.setter
    def ts_ms(self, val: int) -> None:
        self.timestamp_ms = val

    @property
    def rel_s(self) -> float:
        """Alias for time_rel_s (used by trim_log.py)."""
        return self.time_rel_s

    @rel_s.setter
    def rel_s(self, val: float) -> None:
        self.time_rel_s = val

    def __repr__(self) -> str:
        return (
            f"CanFrame(ts={self.timestamp_ms}ms, rel={self.time_rel_s:.3f}s, "
            f"id=0x{self.can_id:03X}, dlc={self.dlc}, data={self.data.hex()})"
        )


def natural_sort_key(p: Path) -> List[Any]:
    """Generates an alphanumeric natural sort key for Path objects."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", p.name)]


def read_bin_file(filepath: Path) -> List[CanFrame]:
    """Reads and parses a 16-byte packed binary log file into a list of CanFrames."""
    if not filepath.is_file():
        return []

    raw_data = filepath.read_bytes()
    num_frames = len(raw_data) // RECORD_SIZE
    if num_frames == 0:
        return []

    frames: List[CanFrame] = []
    first_ts: Optional[int] = None

    for i in range(num_frames):
        chunk = raw_data[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
        ts, cid, dlc, payload = CAN_STRUCT.unpack(chunk)
        if first_ts is None:
            first_ts = ts
        rel_s = (ts - first_ts) / 1000.0
        frames.append(CanFrame(ts, rel_s, cid, dlc, payload[:dlc]))

    return frames


def find_bin_files(
    specific: Optional[Path] = None,
    search_dirs: Optional[Sequence[Path]] = None,
) -> List[Path]:
    """Finds all *.bin files across search_dirs (defaulting to decoder dir and cwd)."""
    if specific and specific.is_file():
        return [specific]

    decoder_dir = Path(__file__).resolve().parent.parent
    cwd = Path(".").resolve()

    if search_dirs is None:
        dirs = [decoder_dir]
        if cwd != decoder_dir:
            dirs.append(cwd)
    else:
        dirs = list(search_dirs)

    seen = set()
    files: List[Path] = []

    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.bin"):
            res = p.resolve()
            if res not in seen and p.is_file():
                seen.add(res)
                files.append(p)

    files.sort(key=natural_sort_key)
    if not files:
        fixtures_dir = decoder_dir / "fixtures"
        if fixtures_dir.is_dir():
            for p in fixtures_dir.glob("*.bin"):
                res = p.resolve()
                if res not in seen and p.is_file():
                    seen.add(res)
                    files.append(p)
            files.sort(key=natural_sort_key)

    return files


def resolve_bin_file(filename: str, search_dirs: Optional[Sequence[Path]] = None) -> Optional[Path]:
    """Resolves a .bin filename across candidate search dirs, cwd, and fixtures."""
    p = Path(filename)
    if p.is_file():
        return p

    decoder_dir = Path(__file__).resolve().parent.parent
    cwd = Path(".").resolve()
    dirs = list(search_dirs) if search_dirs is not None else [decoder_dir, cwd]

    for d in dirs:
        cand = d / filename
        if cand.is_file():
            return cand

    fixtures_dir = decoder_dir / "fixtures"
    cand_fixture = fixtures_dir / filename
    if cand_fixture.is_file():
        return cand_fixture

    return None

