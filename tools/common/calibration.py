"""MiniGauge Shared Calibration Data Store.

Handles loading, validating, and persisting shared gear estimation and algorithm
calibration parameters (tools/gear_calibration.json) interoperating seamlessly
between tuner.py, gear_lab.py, and embedded C header generators.
Zero pip dependencies (Python 3 stdlib only).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CALIBRATION_FILE = Path(__file__).resolve().parent.parent / "gear_calibration.json"


def get_default_calibration() -> Dict[str, Any]:
    """Returns factory default algorithm calibration parameters."""
    return {
        "version": 1,
        "source": "factory_default",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nominal_ratios": [1.018, 1.793, 2.726, 3.763, 4.542],
        "vars": [0.0036, 0.0049, 0.0030, 0.0025, 0.0784],
        "tolerance": 0.18,
        "tolerance_abs": 0.18,
        "latch_ms": 320,
        "latch_time_ms": 320,
        "min_speed_kph": 9.963,
        "min_speed_hz": 4.5,
        "min_rpm": 930,
        "min_rpm_hz": 31,
        "stability_gate": 0.05,
        "ratio_alpha": 0.15,
        "m2_decay": 0.94,
        "m2_inertia": 0.96,
        "m2_conf": 0.38,
        "m2_latch_ms": 200,
        "m3_inertia": 0.97,
        "m3_clutch_decel": -40.0,
    }


def load_calibration(filepath: Optional[Path] = None) -> Dict[str, Any]:
    """Loads calibration parameters from disk with fallback to factory defaults."""
    target = filepath or DEFAULT_CALIBRATION_FILE
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = get_default_calibration()
                merged.update(data)
                return merged
        except Exception:
            pass
    return get_default_calibration()


def save_calibration(
    data: Dict[str, Any],
    filepath: Optional[Path] = None,
    source: str = "shared",
) -> Path:
    """Safely updates and persists calibration parameters to disk."""
    target = filepath or DEFAULT_CALIBRATION_FILE
    current = load_calibration(target)
    current.update(data)

    if "tolerance" in data:
        current["tolerance"] = data["tolerance"]
        current["tolerance_abs"] = data["tolerance"]
    elif "tolerance_abs" in data:
        current["tolerance"] = data["tolerance_abs"]
        current["tolerance_abs"] = data["tolerance_abs"]

    if "latch_ms" in data:
        current["latch_ms"] = data["latch_ms"]
        current["latch_time_ms"] = data["latch_ms"]
    elif "latch_time_ms" in data:
        current["latch_ms"] = data["latch_time_ms"]
        current["latch_time_ms"] = data["latch_time_ms"]

    if "min_speed_hz" in data and "min_speed_kph" not in data:
        current["min_speed_kph"] = round(data["min_speed_hz"] * 2.214, 3)
    elif "min_speed_kph" in data and "min_speed_hz" not in data:
        current["min_speed_hz"] = round(data["min_speed_kph"] / 2.214, 2)

    if "min_rpm_hz" in data and "min_rpm" not in data:
        current["min_rpm"] = round(data["min_rpm_hz"] * 30)
    elif "min_rpm" in data and "min_rpm_hz" not in data:
        current["min_rpm_hz"] = round(data["min_rpm"] / 30.0, 2)

    current["source"] = source
    current["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return target
