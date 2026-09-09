#!/usr/bin/env python3
"""
MiniGauge - Dedicated Gear Estimator Lab & Embedded Model Trainer
================================================================
A standalone interactive calibration lab and machine learning workbench
specialized in vehicle gear estimation for the MiniGauge ESP32 platform.

Features:
- Multi-log statistical aggregation across all binary logs in folder
- Gaussian Mixture / statistical peak finding (5 forward gears + Neutral)
- Training and side-by-side benchmarking of 3 lightweight models:
  1. Calibrated Gated Heuristic (deterministic baseline)
  2. Recursive Bayesian Classifier (Gaussian likelihoods + prior decay)
  3. Hidden Markov Model (HMM with physical transition matrix & clutch-drop suppression)
- Glitch & stability scorecards (Dropouts, Chatter, Phantom Shifts, Glitch-Free Score %)
- Turnkey C header exporter (`gear_estimator_params.h`) for ESP32 firmware

Zero external pip dependencies (Pure Python 3 standard library).
"""

import argparse
import json
import math
import os
import re
import socket
import struct
import sys
import time
import urllib.parse
import webbrowser
try:
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer as ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
DBC_DEFAULT = SCRIPT_DIR / "binocan.dbc"
CAN_FRAME_STRUCT = struct.Struct("<IHB8sx")

# ==============================================================================
# DBC PARSER & BINARY LOG READER (Pure Python stdlib)
# ==============================================================================

class DbcSignal:
    def __init__(self, name: str, start_bit: int, length: int, is_little: bool,
                 is_signed: bool, factor: float, offset: float, min_val: float,
                 max_val: float, unit: str, value_table: Dict[int, str], valtype: int = 0):
        self.name = name
        self.start_bit = start_bit
        self.length = length
        self.is_little = is_little
        self.is_signed = is_signed
        self.factor = factor
        self.offset = offset
        self.min_val = min_val
        self.max_val = max_val
        self.unit = unit
        self.value_table = value_table
        self.valtype = valtype

    def decode(self, data_bytes: bytes) -> Optional[float]:
        val_int = 0
        if self.is_little:
            data_int = int.from_bytes(data_bytes, byteorder="little")
            mask = (1 << self.length) - 1
            raw = (data_int >> self.start_bit) & mask
            if self.is_signed and not self.valtype and (raw & (1 << (self.length - 1))):
                raw -= (1 << self.length)
            val_int = raw
        else:
            bits = "".join(f"{b:08b}" for b in data_bytes)
            pos = self.start_bit
            extracted = []
            for _ in range(self.length):
                extracted.append(bits[pos])
                if pos % 8 == 7:
                    pos -= 15
                else:
                    pos += 1
            raw = int("".join(extracted), 2)
            if self.is_signed and not self.valtype and (raw & (1 << (self.length - 1))):
                raw -= (1 << self.length)
            val_int = raw

        if self.valtype == 1:
            raw_bytes = (val_int & 0xFFFFFFFF).to_bytes(4, "little")
            raw_float = struct.unpack("<f", raw_bytes)[0]
            return raw_float * self.factor + self.offset
        elif self.valtype == 2:
            raw_bytes = (val_int & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
            raw_double = struct.unpack("<d", raw_bytes)[0]
            return raw_double * self.factor + self.offset

        return val_int * self.factor + self.offset


class DbcMessage:
    def __init__(self, can_id: int, name: str, dlc: int):
        self.can_id = can_id
        self.name = name
        self.dlc = dlc
        self.signals: Dict[str, DbcSignal] = {}

    def decode(self, data: bytes) -> Dict[str, Any]:
        res = {}
        for sig in self.signals.values():
            val = sig.decode(data)
            if val is not None:
                res[sig.name] = {"value": val, "unit": sig.unit}
        return res


class DbcDatabase:
    def __init__(self):
        self.messages: Dict[int, DbcMessage] = {}
        self.value_tables: Dict[str, Dict[int, str]] = {}

    @classmethod
    def parse(cls, filepath: Path) -> "DbcDatabase":
        db = cls()
        if not filepath.is_file():
            return db

        content = filepath.read_text(encoding="utf-8", errors="replace")
        val_table_pattern = re.compile(r"^VAL_TABLE_\s+(\w+)\s+(.*?);", re.MULTILINE | re.DOTALL)
        for match in val_table_pattern.finditer(content):
            tname, tbody = match.group(1), match.group(2)
            mapping = {}
            for entry in re.finditer(r'(\d+)\s+"([^"]*)"', tbody):
                mapping[int(entry.group(1))] = entry.group(2)
            db.value_tables[tname] = mapping

        valtype_re = re.compile(r"^SIG_VALTYPE_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s*;", re.MULTILINE)
        valtypes = {}
        for m in valtype_re.finditer(content):
            valtypes[(int(m.group(1)), m.group(2))] = int(m.group(3))

        msg_pattern = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)", re.MULTILINE)
        sig_pattern = re.compile(
            r'^\s*SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^)]+)\)\s*\[([^|]+)\|([^\]]+)\]\s*"([^"]*)"',
            re.MULTILINE,
        )

        pos = 0
        while True:
            m_match = msg_pattern.search(content, pos)
            if not m_match:
                break
            can_id = int(m_match.group(1)) & 0x1FFFFFFF
            msg_name = m_match.group(2)
            dlc = int(m_match.group(3))
            msg = DbcMessage(can_id, msg_name, dlc)

            next_m = msg_pattern.search(content, m_match.end())
            end_pos = next_m.start() if next_m else len(content)
            body = content[m_match.end():end_pos]

            for s_match in sig_pattern.finditer(body):
                sname = s_match.group(1)
                start_bit = int(s_match.group(2))
                length = int(s_match.group(3))
                is_little = s_match.group(4) == "1"
                is_signed = s_match.group(5) == "-"
                factor = float(s_match.group(6))
                offset = float(s_match.group(7))
                min_v = float(s_match.group(8))
                max_v = float(s_match.group(9))
                unit = s_match.group(10)
                vtype = valtypes.get((can_id, sname), 0)
                msg.signals[sname] = DbcSignal(
                    sname, start_bit, length, is_little, is_signed, factor, offset, min_v, max_v, unit, {}, vtype
                )

            db.messages[can_id] = msg
            pos = end_pos

        return db


class CanFrame:
    __slots__ = ("timestamp_ms", "can_id", "dlc", "data", "time_rel_s")
    def __init__(self, timestamp_ms: int, can_id: int, dlc: int, data: bytes):
        self.timestamp_ms = timestamp_ms
        self.can_id = can_id
        self.dlc = dlc
        self.data = data
        self.time_rel_s = 0.0


def read_bin_file(filepath: Path) -> List[CanFrame]:
    frames = []
    if not filepath.is_file():
        return frames
    raw_data = filepath.read_bytes()
    num_frames = len(raw_data) // 16
    first_ts = None
    for i in range(num_frames):
        chunk = raw_data[i * 16 : (i + 1) * 16]
        ts, cid, dlc, payload = CAN_FRAME_STRUCT.unpack(chunk)
        if first_ts is None:
            first_ts = ts
        f = CanFrame(ts, cid, dlc, payload[:dlc])
        f.time_rel_s = (ts - first_ts) / 1000.0
        frames.append(f)
    return frames


def find_bin_files(specific: Optional[Path] = None) -> List[Path]:
    if specific and specific.is_file():
        return [specific]
    seen = set()
    files: List[Path] = []
    search_dirs = [SCRIPT_DIR]
    cwd = Path(".").resolve()
    if cwd != SCRIPT_DIR.resolve():
        search_dirs.append(cwd)
    for d in search_dirs:
        for p in d.glob("*.bin"):
            if p.is_file() and p.resolve() not in seen:
                seen.add(p.resolve())
                files.append(p)
    files.sort(key=lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', p.name)])
    return files

# Global DBC instance
_GLOBAL_DBC: Optional[DbcDatabase] = None
def get_dbc() -> DbcDatabase:
    global _GLOBAL_DBC
    if _GLOBAL_DBC is None:
        _GLOBAL_DBC = DbcDatabase.parse(DBC_DEFAULT)
    return _GLOBAL_DBC

# ==============================================================================
# MULTI-LOG DATASET EXTRACTION & STATISTICAL CLUSTERING
# ==============================================================================

DATASET_CACHE: Dict[str, Any] = {}

def extract_gear_log(log_path: Path, db: DbcDatabase) -> Dict[str, Any]:
    """Extracts synchronized speed/RPM frequencies and vehicle dynamics from a single .bin log."""
    frames = read_bin_file(log_path)
    if not frames:
        return {"filename": log_path.name, "times": [], "speed_freq": [], "rpm_freq": [], "speed_kph": [], "rpm": [], "ground_truth": []}

    latest_speed_freq = 0.0
    latest_speed_kph = 0.0
    latest_rpm = 0.0
    latest_gt = 0

    times = []
    speed_freq = []
    rpm_freq = []
    speed_kph = []
    rpm = []
    ground_truth = []

    m_100 = db.messages.get(0x100)
    m_300 = db.messages.get(0x300)
    m_301 = db.messages.get(0x301)

    for frame in frames:
        cid = frame.can_id
        t = round(frame.time_rel_s, 4)

        if cid == 0x100 and m_100:
            d = m_100.decode(frame.data)
            if "ITF_speed_kph" in d:
                latest_speed_kph = float(d["ITF_speed_kph"]["value"])
            if "ITF_rpm" in d:
                latest_rpm = float(d["ITF_rpm"]["value"])
            if "ITF_gear_position_ST" in d:
                latest_gt = int(d["ITF_gear_position_ST"]["value"])

        elif cid == 0x300 and m_300:
            d = m_300.decode(frame.data)
            if "DBG_speed_freq" in d:
                latest_speed_freq = float(d["DBG_speed_freq"]["value"])

        elif cid == 0x301 and m_301:
            d = m_301.decode(frame.data)
            if "DBG_RPM_freq" in d:
                rf = float(d["DBG_RPM_freq"]["value"])
                times.append(t)
                speed_freq.append(latest_speed_freq)
                rpm_freq.append(rf)
                speed_kph.append(latest_speed_kph)
                rpm.append(latest_rpm)
                ground_truth.append(latest_gt)

    return {
        "filename": log_path.name,
        "duration_s": round(times[-1] if times else 0.0, 2),
        "total_frames": len(times),
        "times": times,
        "speed_freq": speed_freq,
        "rpm_freq": rpm_freq,
        "speed_kph": speed_kph,
        "rpm": rpm,
        "ground_truth": ground_truth,
    }


def fit_gear_clusters(all_ratios: List[float], initial_seeds: List[float]) -> Dict[str, Any]:
    """Fits 5 Gaussian clusters on driving ratio points using adaptive nearest-cluster partitioning."""
    if not all_ratios:
        return {
            "means": initial_seeds,
            "stds": [0.06, 0.07, 0.055, 0.05, 0.28],
            "vars": [0.0036, 0.0049, 0.0030, 0.0025, 0.0784],
            "counts": [0]*5,
        }

    seeds = list(initial_seeds)
    # 3 iterations of K-Means / Gaussian M-step refinement
    for _ in range(4):
        clusters = [[] for _ in range(5)]
        for r in all_ratios:
            # Pick closest seed with Voronoi partitioning & absolute boundary check
            best_idx = 0
            best_dist = 999.0
            for i, s in enumerate(seeds):
                d = abs(r - s)
                if d < best_dist and d <= 0.35:
                    best_dist = d
                    best_idx = i
            if best_dist <= 0.35:
                clusters[best_idx].append(r)

        for i in range(5):
            if len(clusters[i]) >= 10:
                seeds[i] = sum(clusters[i]) / len(clusters[i])

    means = []
    stds = []
    vars_ = []
    counts = []

    for i in range(5):
        pts = clusters[i]
        c = len(pts)
        counts.append(c)
        if c >= 5:
            m = sum(pts) / c
            v = sum((x - m) ** 2 for x in pts) / c
            s = math.sqrt(max(0.0001, v))
            means.append(round(m, 3))
            stds.append(round(s, 4))
            vars_.append(round(v, 5))
        else:
            means.append(round(initial_seeds[i], 3))
            stds.append(0.06)
            vars_.append(0.0036)

    return {
        "means": means,
        "stds": stds,
        "vars": vars_,
        "counts": counts,
        "total_samples": len(all_ratios),
    }


def compute_empirical_transition_matrix(all_logs_data: List[Dict[str, Any]], means: List[float]) -> List[List[float]]:
    """Calculates empirical 6x6 transition matrix A across all consecutive samples with Laplace smoothing."""
    # States: 0=N, 1=1G, 2=2G, 3=3G, 4=4G, 5=5G
    counts = [[2.0 for _ in range(6)] for _ in range(6)]

    def classify_pt(sf: float, rf: float) -> int:
        if sf < 5.0 or rf < 25.0:
            return 0
        r = sf / rf
        for gi, m in enumerate(means):
            # Constant absolute tolerance of ±0.25 with Voronoi collision protection
            max_tol = 0.25
            if gi > 0:
                max_tol = min(max_tol, (m - means[gi - 1]) * 0.48)
            if gi < len(means) - 1:
                max_tol = min(max_tol, (means[gi + 1] - m) * 0.48)
            if abs(r - m) <= max_tol:
                return gi + 1
        return 0

    for ldata in all_logs_data:
        sf_list = ldata["speed_freq"]
        rf_list = ldata["rpm_freq"]
        n = len(sf_list)
        if n < 2:
            continue
        prev = classify_pt(sf_list[0], rf_list[0])
        for i in range(1, n):
            cur = classify_pt(sf_list[i], rf_list[i])
            counts[prev][cur] += 1.0
            prev = cur

    # Normalize rows
    A = []
    for i in range(6):
        row_sum = sum(counts[i])
        row = [round(c / row_sum, 4) for c in counts[i]]
        A.append(row)
    return A


def build_aggregated_dataset() -> Dict[str, Any]:
    """Scans all .bin files, extracts gear frames, and computes multi-log statistical models."""
    db = get_dbc()
    bin_files = find_bin_files()
    logs_data = []
    all_driving_ratios = []

    for p in bin_files:
        ldata = extract_gear_log(p, db)
        logs_data.append(ldata)
        for sf, rf in zip(ldata["speed_freq"], ldata["rpm_freq"]):
            if sf >= 5.0 and rf >= 25.0:
                all_driving_ratios.append(sf / rf)

    initial_seeds = [1.01, 1.80, 2.73, 3.76, 4.54]
    fitted = fit_gear_clusters(all_driving_ratios, initial_seeds)
    A = compute_empirical_transition_matrix(logs_data, fitted["means"])

    # Build histogram (bins 0.0 to 7.0)
    bin_width = 0.04
    hist_bins = []
    b_val = 0.0
    while b_val <= 7.0:
        hist_bins.append(round(b_val, 2))
        b_val += bin_width

    hist_counts = [0] * len(hist_bins)
    for r in all_driving_ratios:
        if 0.0 <= r < 7.0:
            idx = int(r / bin_width)
            if 0 <= idx < len(hist_counts):
                hist_counts[idx] += 1

    # Build concatenated timeline with session offset and boundaries
    concat_times = []
    concat_speed_freq = []
    concat_rpm_freq = []
    concat_speed_kph = []
    concat_rpm = []
    concat_ground_truth = []
    session_boundaries = []
    cur_offset = 0.0

    for ldata in logs_data:
        t_arr = ldata["times"]
        if not t_arr:
            continue
        t0 = cur_offset
        t_shifted = [round(t + cur_offset, 4) for t in t_arr]
        t1 = t_shifted[-1]
        session_boundaries.append({
            "name": ldata["filename"],
            "start_time": round(t0, 2),
            "end_time": round(t1, 2),
            "duration": round(t1 - t0, 2),
        })
        concat_times.extend(t_shifted)
        concat_speed_freq.extend(ldata["speed_freq"])
        concat_rpm_freq.extend(ldata["rpm_freq"])
        concat_speed_kph.extend(ldata["speed_kph"])
        concat_rpm.extend(ldata["rpm"])
        concat_ground_truth.extend(ldata["ground_truth"])
        cur_offset = round(t1 + 5.0, 2)  # 5-second buffer gap between consecutive logs

    concat_timeline = {
        "filename": "All Combined Logs (Concatenated)",
        "duration_s": round(concat_times[-1] if concat_times else 0.0, 2),
        "total_frames": len(concat_times),
        "times": concat_times,
        "speed_freq": concat_speed_freq,
        "rpm_freq": concat_rpm_freq,
        "speed_kph": concat_speed_kph,
        "rpm": concat_rpm,
        "ground_truth": concat_ground_truth,
        "session_boundaries": session_boundaries,
    }

    return {
        "logs": logs_data,
        "concat_timeline": concat_timeline,
        "total_driving_samples": len(all_driving_ratios),
        "fitted": fitted,
        "transition_matrix": A,
        "histogram": {
            "bins": hist_bins,
            "counts": hist_counts,
        },
    }


# ==============================================================================
# 3 EMBEDDED MODEL INFERENCE ALGORITHMS (Python reference & evaluation)
# ==============================================================================

def run_model_1_heuristic(g: Dict[str, Any], means: List[float], alpha: float = 0.15, tol: float = 0.25, latch_ms: float = 200.0, min_speed_hz: float = 11.28, min_rpm_hz: float = 33.33, return_details: bool = False) -> Any:
    """Model 1: Calibrated Gated Heuristic Baseline with ratio EMA, absolute tolerance window, State 14 Uncertain, and temporal latching."""
    n = len(g["times"])
    out = [0] * n
    smoothed_ratios = [None] * n
    latched = 0
    pending = 0
    p_time = 0.0
    current_ema = None
    prev_raw = None

    for i in range(n):
        t = g["times"][i]
        sf = g["speed_freq"][i]
        rf = g["rpm_freq"][i]

        speed_valid = (sf >= min_speed_hz)
        rpm_valid = (rf >= min_rpm_hz)
        ratio = (sf / rf) if (rpm_valid and sf > 0) else None

        stable = False
        if ratio is not None and prev_raw is not None:
            stable = (abs(ratio - prev_raw) <= 0.05)
        elif ratio is not None:
            stable = True
        prev_raw = ratio

        if speed_valid and rpm_valid and stable and ratio is not None:
            if current_ema is None:
                current_ema = ratio
            else:
                current_ema = alpha * ratio + (1.0 - alpha) * current_ema
        elif not speed_valid or not rpm_valid:
            current_ema = None

        cand = 0
        if not speed_valid or not rpm_valid:
            cand = 0  # Neutral: standstill or idling below cutoff (<1000 RPM)
        elif current_ema is not None:
            cand_found = 0
            for gi, nom in enumerate(means):
                max_tol = tol
                if gi > 0:
                    max_tol = min(max_tol, (nom - means[gi - 1]) * 0.48)
                if gi < len(means) - 1:
                    max_tol = min(max_tol, (means[gi + 1] - nom) * 0.48)
                if abs(current_ema - nom) <= max_tol:
                    cand_found = gi + 1
                    break
            cand = cand_found if cand_found > 0 else 14  # State 14: Uncertain (moving above cutoff, ratio out of calibrated bands)
        else:
            cand = 14  # State 14: Uncertain (moving above cutoff, ratio unstable or clutch disengaged)

        if not speed_valid or not rpm_valid:
            latched = 0
            pending = 0
            p_time = t
            out[i] = 0
        else:
            if cand != pending:
                pending = cand
                p_time = t
            if (t - p_time) * 1000.0 >= latch_ms:
                latched = pending
            out[i] = latched

        smoothed_ratios[i] = current_ema

    if return_details:
        return out, smoothed_ratios
    return out


def run_model_2_bayesian(g: Dict[str, Any], means: List[float], vars_: List[float], decay: float = 0.94, p0: float = 0.08, conf_thresh: float = 0.38, inertia: float = 0.96, latch_ms: float = 200.0, min_speed_hz: float = 11.28, min_rpm_hz: float = 33.33, return_details: bool = False) -> Any:
    """Model 2: Kinematic-Conditioned Bayesian Filter with signed speed/RPM rates of change, loss-of-fix handling, State 14 Uncertain, and guarded temporal latching."""
    n = len(g["times"])
    out = [0] * n
    post_history = []
    prior = [0.90, 0.02, 0.02, 0.02, 0.02, 0.02]
    prev_rf = None
    prev_sf = None

    latched = 0
    pending = 0
    pending_time = 0.0

    for i in range(n):
        sf = g["speed_freq"][i]
        rf = g["rpm_freq"][i]
        t = g["times"][i]
        dt = max(0.005, min(0.5, t - g["times"][i-1])) if i > 0 else 0.05

        if sf < min_speed_hz or rf < min_rpm_hz:
            out[i] = 0
            latched = 0
            pending = 0
            pending_time = 0.0
            prior = [0.95, 0.01, 0.01, 0.01, 0.01, 0.01]
            prev_rf = rf
            prev_sf = sf
            if return_details:
                post_history.append(prior[:])
            continue

        r = sf / rf
        dsf = (sf - prev_sf) / dt if prev_sf is not None else 0.0
        drf = (rf - prev_rf) / dt if prev_rf is not None else 0.0
        prev_sf = sf
        prev_rf = rf

        # Construct Kinematic Transition Matrix T[6][6]
        T = [[0.02] * 6 for _ in range(6)]
        T[0][0] = 0.85
        for k in range(1, 6):
            T[0][k] = 0.03
            T[k][k] = inertia
            T[k][0] = 0.03
            if dsf >= 0.0 and rf >= 55.0:
                # Upshift bias: accelerating in upper RPM
                if k < 5: T[k][k+1] = 0.06
                if k > 1: T[k][k-1] = 0.0001
            elif dsf < -3.0:
                # Downshift bias: braking
                if k > 1: T[k][k-1] = 0.06
                if k < 5: T[k][k+1] = 0.0001
            else:
                if k < 5: T[k][k+1] = 0.02
                if k > 1: T[k][k-1] = 0.02

        for r_idx in range(6):
            row_sum = sum(T[r_idx])
            T[r_idx] = [x / row_sum for x in T[r_idx]]

        pred = [sum(prior[i_idx] * T[i_idx][j] for i_idx in range(6)) for j in range(6)]

        lik = [0.0] * 6
        is_clutch_drop = (drf < -35.0 and sf >= min_speed_hz and dsf > -5.0)
        lik[0] = p0 * (1.8 if is_clutch_drop else 1.0)

        curr_assumed = prior.index(max(prior[1:])) if max(prior[1:]) > 0.3 else 0
        for gi in range(5):
            diff = r - means[gi]
            v = vars_[gi]
            density = math.exp(-0.5 * (diff * diff) / v) / math.sqrt(2 * math.pi * v)
            if is_clutch_drop and (gi + 1) > curr_assumed and curr_assumed > 0:
                density *= 0.0001
            lik[gi + 1] = density

        post = [lik[k] * (decay * pred[k] + (1.0 - decay) * 0.1666) for k in range(6)]
        tot = sum(post)
        if tot > 0:
            post = [p / tot for p in post]
        prior = post

        best_k = post.index(max(post))
        if post[best_k] >= conf_thresh:
            raw_choice = 14 if best_k == 0 else best_k
        else:
            raw_choice = 14  # Low posterior confidence while vehicle is moving

        # Guard against phantom upward shift during clutch-drop engine deceleration
        if is_clutch_drop and raw_choice > latched and 1 <= latched <= 5:
            raw_choice = latched

        if raw_choice != pending:
            pending = raw_choice
            pending_time = 0.0
        else:
            pending_time += (dt * 1000.0)
            if pending_time >= latch_ms:
                latched = pending
        out[i] = latched

        if return_details:
            post_history.append(post[:])

    if return_details:
        return out, post_history
    return out


def run_model_3_hmm(g: Dict[str, Any], means: List[float], vars_: List[float], A: List[List[float]], inertia: float = 0.97, clutch_decel: float = -40.0, min_speed_hz: float = 11.28, min_rpm_hz: float = 33.33, return_details: bool = False) -> Any:
    """Model 3: Hidden Markov Model with physical transition matrix, clutch-drop suppression, and State 14 Uncertain."""
    n = len(g["times"])
    out = [0] * n
    alpha_history = []
    alpha = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    A_eff = [row[:] for row in A]
    if inertia > 0.0:
        for i in range(6):
            A_eff[i][i] = inertia
            rem = (1.0 - inertia) / 5.0
            for j in range(6):
                if j != i:
                    A_eff[i][j] = rem

    for i in range(n):
        t = g["times"][i]
        sf = g["speed_freq"][i]
        rf = g["rpm_freq"][i]

        if sf < min_speed_hz or rf < min_rpm_hz:
            out[i] = 0
            alpha = [0.95, 0.01, 0.01, 0.01, 0.01, 0.01]
            if return_details:
                alpha_history.append(alpha[:])
            continue

        r = sf / rf
        prev_rf = g["rpm_freq"][i - 1] if i > 0 else rf
        dt = max(0.01, t - g["times"][i - 1]) if i > 0 else 0.1
        drpm = (rf - prev_rf) / dt
        is_clutch_drop = (drpm < clutch_decel)

        prev_g = out[i - 1] if i > 0 else 0
        emiss = [0.0] * 6
        emiss[0] = 0.18 if is_clutch_drop else 0.04

        for gi in range(5):
            diff = r - means[gi]
            v = vars_[gi]
            density = math.exp(-0.5 * (diff * diff) / v) / math.sqrt(2 * math.pi * v)
            if is_clutch_drop and (gi + 1) > prev_g and 1 <= prev_g <= 5:
                density *= 0.0001
            emiss[gi + 1] = density

        # HMM forward step
        new_alpha = [0.0] * 6
        for j in range(6):
            s = sum(alpha[k] * A_eff[k][j] for k in range(6))
            new_alpha[j] = s * emiss[j]

        tot = sum(new_alpha)
        if tot > 0:
            new_alpha = [x / tot for x in new_alpha]
        alpha = new_alpha

        best_j = alpha.index(max(alpha))
        if alpha[best_j] >= 0.38:
            out[i] = 14 if best_j == 0 else best_j
        else:
            out[i] = 14

        if return_details:
            alpha_history.append(alpha[:])

    if return_details:
        return out, alpha_history
    return out


def evaluate_glitches(times: List[float], speeds: List[float], rpms: List[float], gears: List[int], max_events: int = 150) -> Dict[str, Any]:
    """Standardized glitch evaluator: Dropouts, Chatter, Phantoms, Glitch Score (State 14 Uncertain compliant)."""
    n = len(gears)
    if n < 3:
        return {"dropouts": 0, "chatter": 0, "phantoms": 0, "glitch_score": 100, "active_pct": "0.0", "events": []}

    segments = []
    cur_g = gears[0]
    cur_start = 0

    for i in range(1, n):
        if gears[i] != cur_g:
            segments.append({
                "gear": cur_g,
                "start": cur_start,
                "end": i - 1,
                "duration": times[i - 1] - times[cur_start],
            })
            cur_g = gears[i]
            cur_start = i
    segments.append({
        "gear": cur_g,
        "start": cur_start,
        "end": n - 1,
        "duration": times[n - 1] - times[cur_start],
    })

    dropouts = 0
    chatter = 0
    phantoms = 0
    forward_samples = 0
    events = []

    for s in range(len(segments)):
        seg = segments[s]
        # Forward gears: 1 <= gear <= 5 (ignore 0 Neutral and 14 Uncertain)
        if 1 <= seg["gear"] <= 5:
            forward_samples += (seg["end"] - seg["start"] + 1)
            # Chatter: dwell < 300 ms in forward gear
            if seg["duration"] < 0.30:
                chatter += 1
                if len(events) < max_events:
                    events.append({
                        "type": "chatter",
                        "time": round(times[seg["start"]], 2),
                        "gear": seg["gear"],
                        "desc": f"Chatter: {seg['gear']}G dwell only {(seg['duration']*1000):.0f}ms"
                    })

        # Neutral dropout: k -> 0 -> k within 450 ms while rolling
        # Transitions k -> 14 -> k+1 or k -> 14 -> k are shift transitions and NOT dropouts to Neutral!
        if seg["gear"] == 0 and 0 < s < len(segments) - 1:
            p = segments[s - 1]
            nxt = segments[s + 1]
            if 1 <= p["gear"] <= 5 and p["gear"] == nxt["gear"] and seg["duration"] < 0.45:
                avg_v = (speeds[seg["start"]] + speeds[seg["end"]]) / 2.0
                if avg_v >= 20.0:
                    dropouts += 1
                    if len(events) < max_events:
                        events.append({
                            "type": "dropout",
                            "time": round(times[seg["start"]], 2),
                            "gear": 0,
                            "desc": f"Dropout: {p['gear']}G -> N -> {nxt['gear']}G in {(seg['duration']*1000):.0f}ms @ {avg_v:.1f} km/h"
                        })

    # Phantom upward shifts during coasting (between forward gears 1..5)
    for s in range(1, len(segments)):
        prev_s = segments[s - 1]
        cur_s = segments[s]
        if 1 <= prev_s["gear"] <= 5 and 1 <= cur_s["gear"] <= 5 and cur_s["gear"] > prev_s["gear"]:
            idx = cur_s["start"]
            back_idx = max(0, idx - 4)
            dt = times[idx] - times[back_idx]
            if dt > 0.05:
                drpm = (rpms[idx] - rpms[back_idx]) / dt
                dspeed = (speeds[idx] - speeds[back_idx]) / dt
                if drpm < -1200.0 and dspeed < 1.0:
                    phantoms += 1
                    if len(events) < max_events:
                        events.append({
                            "type": "phantom",
                            "time": round(times[idx], 2),
                            "gear": cur_s["gear"],
                            "desc": f"Phantom Shift: {prev_s['gear']}G -> {cur_s['gear']}G during engine drop ({drpm:.0f} RPM/s)"
                        })

    score = max(0, min(100, round(100 - (2.5 * dropouts + 1.0 * chatter + 5.0 * phantoms))))
    active_pct = f"{(forward_samples / n * 100):.1f}"

    return {
        "dropouts": dropouts,
        "chatter": chatter,
        "phantoms": phantoms,
        "glitch_score": score,
        "active_pct": active_pct,
        "events": events,
    }


def optimize_parameters(agg: Dict[str, Any], target_log: str = "all", min_speed_hz: float = 11.28, min_rpm_hz: float = 33.33) -> Dict[str, Any]:
    """Auto-optimizes tuning parameters across M1, M2, and M3 to maximize Glitch-Free Quality Scores."""
    if target_log == "all":
        log_data = agg.get("concat_timeline") or agg["logs"][0]
    else:
        log_data = next((l for l in agg["logs"] if l["filename"] == target_log), agg.get("concat_timeline") or agg["logs"][0])

    means = agg["fitted"]["means"]
    vars_ = agg["fitted"]["vars"]
    A = agg["transition_matrix"]
    times = log_data["times"]
    speeds = log_data["speed_kph"]
    rpms = log_data["rpm"]

    # Initial baseline scores
    base_m1 = run_model_1_heuristic(log_data, means, alpha=0.15, tol=0.25, latch_ms=200.0, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)
    base_m2 = run_model_2_bayesian(log_data, means, vars_, decay=0.94, p0=0.08, conf_thresh=0.38, inertia=0.96, latch_ms=200.0, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)
    base_m3 = run_model_3_hmm(log_data, means, vars_, A, inertia=0.97, clutch_decel=-40.0, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)

    base_sc1 = evaluate_glitches(times, speeds, rpms, base_m1)
    base_sc2 = evaluate_glitches(times, speeds, rpms, base_m2)
    base_sc3 = evaluate_glitches(times, speeds, rpms, base_m3)
    before_score = round((base_sc1["glitch_score"] + base_sc2["glitch_score"] + base_sc3["glitch_score"]) / 3.0, 1)

    # 1. Optimize Model 1 (Gated Heuristic)
    best_m1_score = -1
    best_m1_params = {"alpha": 0.15, "tol": 0.25, "latch_ms": 200.0}
    best_m1_sc = None

    for tol in [0.18, 0.22, 0.25, 0.28, 0.32]:
        for latch_ms in [120.0, 180.0, 220.0, 260.0, 320.0]:
            for alpha in [0.08, 0.12, 0.15, 0.20, 0.25]:
                m1 = run_model_1_heuristic(log_data, means, alpha=alpha, tol=tol, latch_ms=latch_ms, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)
                sc = evaluate_glitches(times, speeds, rpms, m1)
                if sc["glitch_score"] > best_m1_score:
                    best_m1_score = sc["glitch_score"]
                    best_m1_params = {"alpha": alpha, "tol": tol, "latch_ms": latch_ms}
                    best_m1_sc = sc

    # 2. Optimize Model 2 (Kinematic Bayesian)
    best_m2_score = -1
    best_m2_params = {"decay": 0.94, "p0": 0.08, "conf": 0.38, "inertia": 0.96, "latch_ms": 200.0}
    best_m2_sc = None

    for decay in [0.88, 0.92, 0.94, 0.97]:
        for inertia in [0.92, 0.95, 0.97, 0.985]:
            for conf in [0.32, 0.38, 0.44]:
                for latch_ms in [120.0, 180.0, 220.0, 280.0]:
                    m2 = run_model_2_bayesian(log_data, means, vars_, decay=decay, p0=0.08, conf_thresh=conf, inertia=inertia, latch_ms=latch_ms, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)
                    sc = evaluate_glitches(times, speeds, rpms, m2)
                    if sc["glitch_score"] > best_m2_score:
                        best_m2_score = sc["glitch_score"]
                        best_m2_params = {"decay": decay, "p0": 0.08, "conf": conf, "inertia": inertia, "latch_ms": latch_ms}
                        best_m2_sc = sc

    # 3. Optimize Model 3 (HMM)
    best_m3_score = -1
    best_m3_params = {"inertia": 0.97, "clutch_decel": -40.0}
    best_m3_sc = None

    for inertia in [0.94, 0.96, 0.975, 0.99]:
        for decel in [-55.0, -40.0, -30.0, -20.0]:
            m3 = run_model_3_hmm(log_data, means, vars_, A, inertia=inertia, clutch_decel=decel, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)
            sc = evaluate_glitches(times, speeds, rpms, m3)
            if sc["glitch_score"] > best_m3_score:
                best_m3_score = sc["glitch_score"]
                best_m3_params = {"inertia": inertia, "clutch_decel": decel}
                best_m3_sc = sc

    after_score = round((best_m1_score + best_m2_score + best_m3_score) / 3.0, 1)
    recommended = {
        "m1_alpha": best_m1_params["alpha"],
        "m1_tol": best_m1_params["tol"],
        "m1_latch_ms": best_m1_params["latch_ms"],
        "m2_decay": best_m2_params["decay"],
        "m2_inertia": best_m2_params["inertia"],
        "m2_latch_ms": best_m2_params["latch_ms"],
        "m2_conf": best_m2_params["conf"],
        "m3_inertia": best_m3_params["inertia"],
        "m3_clutch_decel": best_m3_params["clutch_decel"],
        "best_score": after_score,
    }

    changes = [
        {"param": "M1 Ratio EMA Alpha", "before": 0.15, "after": best_m1_params["alpha"], "unit": ""},
        {"param": "M1 Absolute Tolerance", "before": 0.25, "after": best_m1_params["tol"], "unit": ""},
        {"param": "M1 Latch Debounce", "before": 200, "after": int(best_m1_params["latch_ms"]), "unit": "ms"},
        {"param": "M2 Prior Decay", "before": 0.94, "after": best_m2_params["decay"], "unit": ""},
        {"param": "M2 Inertia T_kk", "before": 0.960, "after": best_m2_params["inertia"], "unit": ""},
        {"param": "M2 Confidence Cutoff", "before": 0.38, "after": best_m2_params["conf"], "unit": ""},
        {"param": "M2 Latch Debounce", "before": 200, "after": int(best_m2_params["latch_ms"]), "unit": "ms"},
        {"param": "M3 Self-Inertia A_ii", "before": 0.970, "after": best_m3_params["inertia"], "unit": ""},
        {"param": "M3 Clutch Decel Cutoff", "before": -40, "after": int(best_m3_params["clutch_decel"]), "unit": "Hz/s"},
    ]

    return {
        "status": "ok",
        "target_log": target_log,
        "before_score": before_score,
        "after_score": after_score,
        "score_delta": round(after_score - before_score, 1),
        "recommended": recommended,
        "changes": changes,
        "m1": {"params": best_m1_params, "scorecard": best_m1_sc, "before_score": base_sc1["glitch_score"]},
        "m2": {"params": best_m2_params, "scorecard": best_m2_sc, "before_score": base_sc2["glitch_score"]},
        "m3": {"params": best_m3_params, "scorecard": best_m3_sc, "before_score": base_sc3["glitch_score"]},
    }

# ==============================================================================
# ESP32 C HEADER GENERATION (zero-allocation, fixed-size C99 implementation)
# ==============================================================================

def generate_esp32_c_header(means: List[float], vars_: List[float], A: List[List[float]], min_speed_hz: float = 11.28, min_rpm_hz: float = 33.33) -> str:
    """Produces turnkey C99 header gear_estimator_params.h with parameters and inference routines."""
    c_means = ", ".join(f"{m:.4f}f" for m in means)
    c_vars = ", ".join(f"{v:.5f}f" for v in vars_)

    a_rows = []
    for row in A:
        a_rows.append("    { " + ", ".join(f"{x:.4f}f" for x in row) + " }")
    c_matrix = ",\n".join(a_rows)

    return f"""/**
 * @file gear_estimator_params.h
 * @brief Auto-generated Gear Estimation Models for MiniGauge (ESP32 / ESP-IDF)
 * Generated by MiniGauge Gear Estimator Lab from multi-log driving dataset.
 *
 * Models implemented:
 * 1. Gated Heuristic Baseline (zero-float fast table lookup)
 * 2. Kinematic-Conditioned Bayesian Classifier (signed acceleration transitions + loss-of-fix handling)
 * 3. Hidden Markov Model (HMM 6-state transition filter with clutch suppression)
 *
 * DBC Values:
 * 0  = Neutral
 * 1..5 = Forward Gears
 * 14 = Uncertain (clutch depression, transition, or ratio out of band)
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {{
#endif

/* DBC Gear Position Constants */
#define GEAR_NEUTRAL           0
#define GEAR_UNCERTAIN         14
#define GEAR_NUM_FORWARD_GEARS 5
#define GEAR_TOLERANCE_ABS     (0.25f)
#define GEAR_MIN_SPEED_HZ      ({min_speed_hz:.2f}f)
#define GEAR_MIN_RPM_HZ        ({min_rpm_hz:.2f}f)

static const float GEAR_RATIO_MEANS[GEAR_NUM_FORWARD_GEARS] = {{ {c_means} }};
static const float GEAR_RATIO_VARS[GEAR_NUM_FORWARD_GEARS]  = {{ {c_vars} }};

/* Empirical 6x6 State Transition Probability Matrix A (N, 1G, 2G, 3G, 4G, 5G) */
static const float GEAR_HMM_TRANSITION[6][6] = {{
{c_matrix}
}};

/* -------------------------------------------------------------------------- */
/* Model 1: Calibrated Gated Heuristic Baseline                               */
/* -------------------------------------------------------------------------- */
typedef struct {{
    float latched_ratio_ema;
    uint8_t latched_gear;
    uint8_t pending_gear;
    float pending_time_ms;
    float prev_ratio;
}} gear_heuristic_state_t;

static inline void gear_heuristic_init(gear_heuristic_state_t *st) {{
    st->latched_ratio_ema = 0.0f;
    st->latched_gear = GEAR_NEUTRAL;
    st->pending_gear = GEAR_NEUTRAL;
    st->pending_time_ms = 0.0f;
    st->prev_ratio = 0.0f;
}}

static inline uint8_t gear_heuristic_update(gear_heuristic_state_t *st, float speed_freq, float rpm_freq, float dt_s) {{
    if (speed_freq < GEAR_MIN_SPEED_HZ || rpm_freq < GEAR_MIN_RPM_HZ) {{
        st->latched_gear = GEAR_NEUTRAL;
        st->pending_gear = GEAR_NEUTRAL;
        st->pending_time_ms = 0.0f;
        st->latched_ratio_ema = 0.0f;
        return GEAR_NEUTRAL;
    }}

    float r = speed_freq / rpm_freq;
    bool stable = (st->prev_ratio <= 0.0f) || (fabsf(r - st->prev_ratio) <= 0.050f);
    st->prev_ratio = r;

    if (!stable) {{
        return st->latched_gear;
    }}

    if (st->latched_ratio_ema <= 0.0f) {{
        st->latched_ratio_ema = r;
    }} else {{
        st->latched_ratio_ema = 0.15f * r + 0.85f * st->latched_ratio_ema;
    }}

    uint8_t cand = GEAR_UNCERTAIN;
    for (int gi = 0; gi < GEAR_NUM_FORWARD_GEARS; gi++) {{
        float nom = GEAR_RATIO_MEANS[gi];
        float max_tol = GEAR_TOLERANCE_ABS;
        if (gi > 0) {{
            float d_prev = (nom - GEAR_RATIO_MEANS[gi - 1]) * 0.48f;
            if (d_prev < max_tol) max_tol = d_prev;
        }}
        if (gi < GEAR_NUM_FORWARD_GEARS - 1) {{
            float d_next = (GEAR_RATIO_MEANS[gi + 1] - nom) * 0.48f;
            if (d_next < max_tol) max_tol = d_next;
        }}
        if (fabsf(st->latched_ratio_ema - nom) <= max_tol) {{
            cand = (uint8_t)(gi + 1);
            break;
        }}
    }}

    if (cand != st->pending_gear) {{
        st->pending_gear = cand;
        st->pending_time_ms = 0.0f;
    }} else {{
        st->pending_time_ms += (dt_s * 1000.0f);
        if (st->pending_time_ms >= 200.0f) {{
            st->latched_gear = st->pending_gear;
        }}
    }}

    return st->latched_gear;
}}

/* -------------------------------------------------------------------------- */
/* Model 2: Kinematic-Conditioned Bayesian Classifier                         */
/* -------------------------------------------------------------------------- */
typedef struct {{
    float prior[6];
    float prev_speed_freq;
    float prev_rpm_freq;
    uint8_t latched_gear;
    uint8_t pending_gear;
    float pending_time_ms;
}} gear_bayesian_state_t;

static inline void gear_bayesian_init(gear_bayesian_state_t *st) {{
    st->prior[0] = 0.90f;
    for (int i = 1; i < 6; i++) st->prior[i] = 0.02f;
    st->prev_speed_freq = 0.0f;
    st->prev_rpm_freq = 0.0f;
    st->latched_gear = GEAR_NEUTRAL;
    st->pending_gear = GEAR_NEUTRAL;
    st->pending_time_ms = 0.0f;
}}

static inline uint8_t gear_bayesian_update(gear_bayesian_state_t *st, float speed_freq, float rpm_freq, float dt_s) {{
    if (speed_freq < GEAR_MIN_SPEED_HZ || rpm_freq < GEAR_MIN_RPM_HZ) {{
        st->prior[0] = 0.95f;
        for (int i = 1; i < 6; i++) st->prior[i] = 0.01f;
        st->prev_speed_freq = speed_freq;
        st->prev_rpm_freq = rpm_freq;
        st->latched_gear = GEAR_NEUTRAL;
        st->pending_gear = GEAR_NEUTRAL;
        st->pending_time_ms = 0.0f;
        return GEAR_NEUTRAL;
    }}

    float dt = (dt_s > 0.005f) ? dt_s : 0.05f;
    float dsf = (st->prev_speed_freq > 0.0f) ? ((speed_freq - st->prev_speed_freq) / dt) : 0.0f;
    float drf = (st->prev_rpm_freq > 0.0f) ? ((rpm_freq - st->prev_rpm_freq) / dt) : 0.0f;
    st->prev_speed_freq = speed_freq;
    st->prev_rpm_freq = rpm_freq;

    /* Construct dynamic Kinematic Transition Matrix T[6][6] */
    float T[6][6];
    for (int i = 0; i < 6; i++) {{
        for (int j = 0; j < 6; j++) T[i][j] = 0.02f;
    }}
    T[0][0] = 0.85f;
    for (int k = 1; k < 6; k++) {{
        T[0][k] = 0.03f;
        T[k][k] = 0.96f;
        T[k][0] = 0.03f;
        if (dsf >= 0.0f && rpm_freq >= 55.0f) {{
            if (k < 5) T[k][k + 1] = 0.06f;
            if (k > 1) T[k][k - 1] = 0.0001f;
        }} else if (dsf < -3.0f) {{
            if (k > 1) T[k][k - 1] = 0.06f;
            if (k < 5) T[k][k + 1] = 0.0001f;
        }} else {{
            if (k < 5) T[k][k + 1] = 0.02f;
            if (k > 1) T[k][k - 1] = 0.02f;
        }}
    }}

    for (int i = 0; i < 6; i++) {{
        float rsum = 0.0f;
        for (int j = 0; j < 6; j++) rsum += T[i][j];
        float inv_sum = 1.0f / rsum;
        for (int j = 0; j < 6; j++) T[i][j] *= inv_sum;
    }}

    float pred[6];
    for (int j = 0; j < 6; j++) {{
        pred[j] = 0.0f;
        for (int i = 0; i < 6; i++) pred[j] += st->prior[i] * T[i][j];
    }}

    float r = speed_freq / rpm_freq;
    bool is_clutch_drop = (drf < -35.0f && speed_freq >= GEAR_MIN_SPEED_HZ && dsf > -5.0f);
    float lik[6];
    lik[0] = 0.08f * (is_clutch_drop ? 1.8f : 1.0f);

    int curr_assumed = 0;
    float max_sub = 0.3f;
    for (int i = 1; i < 6; i++) {{
        if (st->prior[i] > max_sub) {{
            max_sub = st->prior[i];
            curr_assumed = i;
        }}
    }}

    for (int gi = 0; gi < 5; gi++) {{
        float diff = r - GEAR_RATIO_MEANS[gi];
        float v = GEAR_RATIO_VARS[gi];
        float density = expf(-0.5f * (diff * diff) / v) / sqrtf(6.2831853f * v);
        if (is_clutch_drop && (gi + 1) > curr_assumed && curr_assumed > 0) {{
            density *= 0.0001f;
        }}
        lik[gi + 1] = density;
    }}

    const float decay = 0.94f;
    float post[6];
    float tot = 0.0f;
    for (int k = 0; k < 6; k++) {{
        post[k] = lik[k] * (decay * pred[k] + (1.0f - decay) * 0.1666f);
        tot += post[k];
    }}

    uint8_t raw_choice = GEAR_UNCERTAIN;
    if (tot > 0.00001f) {{
        float inv = 1.0f / tot;
        float max_p = 0.0f;
        int best_k = 0;
        for (int k = 0; k < 6; k++) {{
            st->prior[k] = post[k] * inv;
            if (st->prior[k] > max_p) {{
                max_p = st->prior[k];
                best_k = k;
            }}
        }}
        if (max_p >= 0.38f) {{
            raw_choice = (best_k == 0) ? GEAR_UNCERTAIN : (uint8_t)best_k;
        }} else {{
            raw_choice = GEAR_UNCERTAIN;
        }}
    }}

    if (is_clutch_drop && raw_choice > st->latched_gear && st->latched_gear > 0 && st->latched_gear <= 5) {{
        raw_choice = st->latched_gear;
    }}

    if (raw_choice != st->pending_gear) {{
        st->pending_gear = raw_choice;
        st->pending_time_ms = 0.0f;
    }} else {{
        st->pending_time_ms += (dt * 1000.0f);
        if (st->pending_time_ms >= 200.0f) {{
            st->latched_gear = st->pending_gear;
        }}
    }}

    return st->latched_gear;
}}

/* -------------------------------------------------------------------------- */
/* Model 3: Hidden Markov Model (HMM) with Clutch Suppression                 */
/* -------------------------------------------------------------------------- */
typedef struct {{
    float alpha[6];
    float prev_rpm_freq;
    uint8_t prev_gear;
}} gear_hmm_state_t;

static inline void gear_hmm_init(gear_hmm_state_t *st) {{
    st->alpha[0] = 1.0f;
    for (int i = 1; i < 6; i++) st->alpha[i] = 0.0f;
    st->prev_rpm_freq = 0.0f;
    st->prev_gear = GEAR_NEUTRAL;
}}

static inline uint8_t gear_hmm_update(gear_hmm_state_t *st, float speed_freq, float rpm_freq, float dt_s) {{
    if (speed_freq < GEAR_MIN_SPEED_HZ || rpm_freq < GEAR_MIN_RPM_HZ) {{
        st->alpha[0] = 0.95f;
        for (int i = 1; i < 6; i++) st->alpha[i] = 0.01f;
        st->prev_rpm_freq = rpm_freq;
        st->prev_gear = GEAR_NEUTRAL;
        return GEAR_NEUTRAL;
    }}

    float r = speed_freq / rpm_freq;
    float dt = (dt_s > 0.005f) ? dt_s : 0.05f;
    float drpm = (st->prev_rpm_freq > 0.0f) ? ((rpm_freq - st->prev_rpm_freq) / dt) : 0.0f;
    st->prev_rpm_freq = rpm_freq;

    bool is_clutch_drop = (drpm < -40.0f); /* Fast engine drop */
    float emiss[6];
    emiss[0] = is_clutch_drop ? 0.180f : 0.040f;

    for (int gi = 0; gi < 5; gi++) {{
        float diff = r - GEAR_RATIO_MEANS[gi];
        float v = GEAR_RATIO_VARS[gi];
        float dens = expf(-0.5f * (diff * diff) / v) / sqrtf(6.2831853f * v);
        /* Suppress higher phantom gears while engine is falling toward idle */
        if (is_clutch_drop && (gi + 1) > st->prev_gear && st->prev_gear > 0 && st->prev_gear <= 5) {{
            dens *= 0.0001f;
        }}
        emiss[gi + 1] = dens;
    }}

    float new_alpha[6];
    float tot = 0.0f;

    for (int j = 0; j < 6; j++) {{
        float s = 0.0f;
        for (int k = 0; k < 6; k++) {{
            s += st->alpha[k] * GEAR_HMM_TRANSITION[k][j];
        }}
        new_alpha[j] = s * emiss[j];
        tot += new_alpha[j];
    }}

    uint8_t best_j = GEAR_UNCERTAIN;
    float max_a = 0.0f;

    if (tot > 0.00001f) {{
        float inv = 1.0f / tot;
        for (int j = 0; j < 6; j++) {{
            st->alpha[j] = new_alpha[j] * inv;
            if (st->alpha[j] > max_a) {{
                max_a = st->alpha[j];
                best_j = (uint8_t)j;
            }}
        }}
    }}

    uint8_t result = GEAR_UNCERTAIN;
    if (max_a >= 0.38f) {{
        result = (best_j == 0) ? GEAR_UNCERTAIN : best_j;
    }} else {{
        result = GEAR_UNCERTAIN;
    }}

    st->prev_gear = result;
    return result;
}}

#ifdef __cplusplus
}}
#endif
"""

# ==============================================================================
# HTML / CSS / JS WEB INTERFACE
# ==============================================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MiniGauge - Gear Estimator Lab & Model Trainer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --panel-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --accent: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --hover-bg: rgba(255, 255, 255, 0.05);
      --input-bg: #0f172a;
      --input-border: #475569;
    }
    body.theme-light {
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --panel-border: #cbd5e1;
      --text: #0f172a;
      --text-muted: #64748b;
      --primary: #0284c7;
      --primary-hover: #0369a1;
      --accent: #059669;
      --warning: #d97706;
      --danger: #dc2626;
      --hover-bg: rgba(0, 0, 0, 0.04);
      --input-bg: #ffffff;
      --input-border: #cbd5e1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }
    header {
      background: var(--card-bg);
      border-bottom: 1px solid var(--panel-border);
      padding: 0.5rem 1.25rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-shrink: 0;
    }
    .header-left { display: flex; align-items: center; gap: 1rem; }
    .app-title { font-weight: 700; font-size: 1.05rem; display: flex; align-items: center; gap: 0.5rem; color: var(--primary); }
    .header-controls { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
    select, button, input {
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--input-border);
      border-radius: 4px;
      padding: 0.35rem 0.65rem;
      font-size: 0.82rem;
    }
    button {
      cursor: pointer;
      font-weight: 500;
      transition: background 0.15s, border-color 0.15s;
    }
    button:hover { background: var(--hover-bg); }
    button.btn-primary {
      background: var(--primary);
      color: #0f172a;
      border-color: var(--primary);
      font-weight: 600;
    }
    button.btn-primary:hover { background: var(--primary-hover); }
    button.btn-accent {
      background: var(--accent);
      color: #0f172a;
      border-color: var(--accent);
      font-weight: 600;
    }
    button.btn-accent:hover { opacity: 0.9; }

    .info-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: var(--hover-bg);
      border: 1px solid var(--panel-border);
      color: var(--text-muted);
      font-size: 0.65rem;
      font-family: serif;
      font-style: italic;
      cursor: help;
      flex-shrink: 0;
      user-select: none;
      vertical-align: middle;
      transition: all 0.15s ease;
    }
    .info-icon:hover {
      background: var(--primary);
      color: #ffffff;
      border-color: var(--primary);
    }

    .main-layout {
      flex: 1;
      display: flex;
      overflow: hidden;
    }
    .sidebar {
      width: 320px;
      min-width: 320px;
      background: var(--card-bg);
      border-right: 1px solid var(--panel-border);
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      padding: 0.85rem;
      gap: 0.75rem;
    }
    .content-pane {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      padding: 0.65rem 0.85rem;
      gap: 0.55rem;
    }

    /* Tab Navigation Bar */
    .tabs-bar {
      display: flex;
      align-items: center;
      gap: 0.35rem;
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 0.25rem 0.35rem;
      flex-shrink: 0;
    }
    .tab-btn {
      padding: 0.35rem 0.75rem;
      font-size: 0.78rem;
      font-weight: 600;
      border-radius: 4px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.15s;
    }
    .tab-btn:hover {
      color: var(--text);
      background: var(--hover-bg);
    }
    .tab-btn.active {
      background: var(--input-bg);
      color: var(--primary);
      border-color: var(--panel-border);
      box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }

    .tab-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      gap: 0.55rem;
      min-height: 0;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      padding: 0.65rem 0.85rem;
    }
    .card-title {
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    /* Comparison Scorecard Table */
    .benchmark-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.80rem;
      text-align: left;
    }
    .benchmark-table th {
      padding: 0.35rem 0.55rem;
      background: var(--input-bg);
      color: var(--text-muted);
      font-size: 0.70rem;
      text-transform: uppercase;
      border-bottom: 1px solid var(--panel-border);
    }
    .benchmark-table td {
      padding: 0.4rem 0.55rem;
      border-bottom: 1px solid var(--panel-border);
      font-family: monospace;
    }
    .model-badge {
      font-family: -apple-system, sans-serif;
      font-size: 0.70rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      display: inline-block;
    }
    .badge-m1 { background: rgba(59, 130, 246, 0.2); color: #3b82f6; border: 1px solid #3b82f6; }
    .badge-m2 { background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid #f59e0b; }
    .badge-m3 { background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981; }
    .badge-neutral { background: rgba(148, 163, 184, 0.2); color: #94a3b8; border: 1px solid #94a3b8; }
    .badge-uncertain { background: rgba(245, 158, 11, 0.25); color: #f59e0b; border: 1px solid #f59e0b; }

    .val-good { color: var(--accent); font-weight: 700; }
    .val-warn { color: var(--warning); font-weight: 700; }
    .val-bad  { color: var(--danger); font-weight: 700; }

    /* Plots */
    .plots-column {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      overflow: hidden;
      min-height: 0;
    }
    .plot-box {
      flex: 1;
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      min-height: 140px;
      position: relative;
    }
    .timeline-needle {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 2px;
      background: #ef4444;
      pointer-events: none;
      z-index: 50;
      display: none;
      box-shadow: 0 0 5px rgba(239, 68, 68, 0.9);
    }

    /* Modal */
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.7);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      padding: 1.5rem;
    }
    .modal-content {
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      width: 100%;
      max-width: 850px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .modal-header {
      padding: 0.75rem 1.25rem;
      border-bottom: 1px solid var(--panel-border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .modal-body {
      padding: 1rem 1.25rem;
      overflow-y: auto;
      flex: 1;
    }
    pre.code-block {
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 1rem;
      font-family: "Courier New", Courier, monospace;
      font-size: 0.78rem;
      color: #38bdf8;
      overflow-x: auto;
      white-space: pre;
    }
  </style>
</head>
<body>

  <header>
    <div class="header-left">
      <div class="app-title">
        <span>⚙️</span> MiniGauge Gear Estimator Lab
      </div>
      <div style="display:flex; align-items:center; gap:0.4rem;">
        <label for="select-log" style="font-size:0.8rem; color:var(--text-muted);">Dataset / Log:</label>
        <select id="select-log">
          <option value="all">⚡ All Combined Logs (Aggregated)</option>
        </select>
      </div>
    </div>
    <div class="header-controls">
      <button id="btn-retrain" title="Re-cluster and train parameters across logs">⚡ Train Models</button>
      <button class="btn-primary" id="btn-export-c" title="Export ready-to-use C header for ESP32">💾 Export ESP32 C Header</button>
      <button id="btn-theme" title="Toggle Light/Dark Theme">🌓 Theme</button>
    </div>
  </header>

  <div class="main-layout">
    <!-- SIDEBAR -->
    <div class="sidebar">
      <div class="card">
        <div class="card-title">Multi-Log Dataset Overview</div>
        <div style="font-size:0.78rem; line-height:1.45; color:var(--text-muted);">
          Total Log Files: <strong style="color:var(--text);" id="stat-log-count">--</strong><br>
          Driving Frames: <strong style="color:var(--text);" id="stat-sample-count">--</strong><br>
          Vehicle Base: <span style="font-family:monospace; color:var(--primary);">4-cyl 5-Speed MT</span>
        </div>
      </div>

      <!-- Global Low Cutoffs -->
      <div class="card" style="border-left:3px solid var(--primary);">
        <div class="card-title">
          <span>⚡ Low Cutoff Thresholds</span>
          <span class="info-icon" title="Global vehicle standstill and engine idle gating thresholds shared across all algorithms. Below these cutoffs, the car is in Neutral (0).">i</span>
        </div>
        <div style="font-size:0.74rem; color:var(--text-muted); line-height:1.4;">
          <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
            <span>Min Speed: <span class="info-icon" title="Threshold below which vehicle is considered stationary. Low speeds cause noisy ratio spikes; below this cutoff, output defaults to Neutral (0).">i</span></span>
            <span class="ctrl-val" id="val-cutoff-speed" style="font-family:monospace; color:var(--primary);">11.28 Hz (25 km/h)</span>
          </div>
          <input type="range" id="slider-cutoff-speed" min="2.0" max="25.0" step="0.5" value="11.28" style="width:100%;" title="Adjust minimum road speed cutoff">
          <div style="display:flex; justify-content:space-between; margin-top:0.35rem;">
            <span>Min RPM: <span class="info-icon" title="Rejects engine idle/stall conditions. When coasting in neutral or with clutch disengaged, RPM drops to idle while road speed is high, creating false gear ratios.">i</span></span>
            <span class="ctrl-val" id="val-cutoff-rpm" style="font-family:monospace; color:var(--warning);">33.33 Hz (1000 RPM)</span>
          </div>
          <input type="range" id="slider-cutoff-rpm" min="15.0" max="60.0" step="1.0" value="33.33" style="width:100%;" title="Adjust minimum engine RPM cutoff">
          <div style="font-size:0.68rem; color:var(--text-muted); margin-top:0.35rem;">
            Below cutoffs &rarr; <strong>Neutral (0)</strong>.<br>
            Rolling above cutoffs &rarr; <strong>Uncertain (14)</strong> during shifts.
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Trained Gear Ratio Clusters</div>
        <table style="width:100%; font-size:0.78rem; border-collapse:collapse; text-align:left;">
          <thead>
            <tr style="color:var(--text-muted); font-size:0.68rem; border-bottom:1px solid var(--panel-border);">
              <th>Gear</th>
              <th>Ratio (&mu;)</th>
              <th>Std Dev (&sigma;)</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody id="tbl-cluster-body">
            <tr><td colspan="4" style="text-align:center; padding:0.4rem; color:var(--text-muted);">Loading...</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Collapsible: Model Theory & Assumptions -->
      <div class="card" style="padding:0.65rem;">
        <div class="card-title" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center;" id="btn-toggle-theory">
          <span>🧠 Model Theory & Assumptions</span>
          <span id="theory-arrow" style="font-size:0.72rem; color:var(--text-muted);">▶ Expand</span>
        </div>
        <div id="theory-body" style="display:none; margin-top:0.5rem; font-size:0.72rem; color:var(--text-muted); line-height:1.4;">
          <div style="margin-bottom:0.5rem;">
            <strong style="color:#3b82f6;">M1: Gated Heuristic</strong><br>
            • <em>Assumptions</em>: Rigid mechanical coupling; discrete step shifts; zero ratio phase lag.<br>
            • <em>Mechanics</em>: Physical gating (speed&ge;cutoff, RPM&ge;cutoff, |&Delta;r/&Delta;t|&le;0.05), ratio EMA (&alpha;), constant tolerance window (&plusmn;tol<sub>abs</sub>) with Voronoi collision protection, and temporal latching debounce.
          </div>
          <div style="margin-bottom:0.5rem;">
            <strong style="color:#f59e0b;">M2: Kinematic Bayes</strong><br>
            • <em>Assumptions</em>: Dynamic context vector u<sub>t</sub> = [V, &Delta;V/&Delta;t, RPM, &Delta;RPM/&Delta;t]; signed acceleration transition conditioning; loss-of-fix prediction.<br>
            • <em>Mechanics</em>: Conditioned transition prior T<sub>ij</sub>(u<sub>t</sub>). When ratio leaves corridor or engine drops during shift (loss of fix), predicts probable target gears (accelerating in 4th &rarr; 5th &gt; 4th &gt; 3rd; braking &rarr; downshifts) with synchronous RPM likelihood and guarded latching.
          </div>
          <div>
            <strong style="color:#10b981;">M3: HMM State-Space</strong><br>
            • <em>Assumptions</em>: First-order Markov chain with empirical shift matrix A<sub>6&times;6</sub>; self-inertia (~97%); asymmetric engine braking physics.<br>
            • <em>Mechanics</em>: Forward Viterbi belief update with directional clutch-drop suppression (&Delta;f<sub>RPM</sub> &lt; cutoff): upward gear emissions are suppressed during coast-down engine deceleration, eliminating phantom upshifts.
          </div>
        </div>
      </div>

      <!-- Collapsible: Interactive Model Parameter Tuning Drawer -->
      <div class="card" style="padding:0.65rem;">
        <div class="card-title" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center;" id="btn-toggle-tuning">
          <span>🎛️ Interactive Model Tuning</span>
          <span id="tuning-arrow" style="font-size:0.72rem; color:var(--text-muted);">▼ Collapse</span>
        </div>
        <div id="tuning-body" style="display:block; margin-top:0.5rem; font-size:0.72rem; color:var(--text-muted); line-height:1.4;">
          <!-- Model 1 Params -->
          <div style="border-left:2px solid #3b82f6; padding-left:0.45rem; margin-bottom:0.45rem;">
            <strong style="color:#3b82f6;">M1: Gated Heuristic</strong>
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>EMA &alpha;: <span class="info-icon" title="Controls smoothing on the speed/RPM ratio. Lower values filter out transient noise and clutch chatter; higher values respond faster to physical gear shifts.">i</span></span>
              <span class="ctrl-val" id="val-m1-alpha">0.15</span>
            </div>
            <input type="range" id="slider-m1-alpha" min="0.05" max="0.50" step="0.01" value="0.15" style="width:100%;" title="Adjust M1 ratio EMA alpha smoothing factor">
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Abs Tolerance: <span class="info-icon" title="Half-width acceptance band around nominal gear ratios (μ ± Δ). Wider bands catch loose ratios; narrower bands prevent adjacent gear misclassification.">i</span></span>
              <span class="ctrl-val" id="val-m1-tol">&plusmn;0.25</span>
            </div>
            <input type="range" id="slider-m1-tol" min="0.10" max="0.45" step="0.01" value="0.25" style="width:100%;" title="Adjust M1 absolute ratio tolerance corridor half-width">
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Latch Debounce: <span class="info-icon" title="Minimum continuous hold time required before confirming a gear transition. Suppresses momentary shift chatter and transient spikes.">i</span></span>
              <span class="ctrl-val" id="val-m1-latch">200 ms</span>
            </div>
            <input type="range" id="slider-m1-latch" min="50" max="500" step="25" value="200" style="width:100%;" title="Adjust M1 output latch confirmation time">
          </div>

          <!-- Model 2 Params -->
          <div style="border-left:2px solid #f59e0b; padding-left:0.45rem; margin-bottom:0.45rem;">
            <strong style="color:#f59e0b;">M2: Kinematic Bayes</strong>
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Prior Decay &lambda;: <span class="info-icon" title="Forgetting factor for previous belief (P_t|t-1 = P_prev^λ). Higher values maintain stable belief during sensor dropouts; lower values adapt faster to gear transitions.">i</span></span>
              <span class="ctrl-val" id="val-m2-decay">0.94</span>
            </div>
            <input type="range" id="slider-m2-decay" min="0.70" max="0.99" step="0.01" value="0.94" style="width:100%;" title="Adjust M2 Bayesian prior decay factor lambda">
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Inertia T<sub>kk</sub>: <span class="info-icon" title="Diagonal self-transition weight in kinematic transition matrix. High inertia favors staying in the current gear and penalizes erratic gear switching during throttle transients.">i</span></span>
              <span class="ctrl-val" id="val-m2-inertia">0.960</span>
            </div>
            <input type="range" id="slider-m2-inertia" min="0.85" max="0.995" step="0.005" value="0.96" style="width:100%;" title="Adjust M2 kinematic transition matrix diagonal self-inertia">
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Latch Debounce: <span class="info-icon" title="Enforces continuous stability of the MAP gear decision before switching the physical output.">i</span></span>
              <span class="ctrl-val" id="val-m2-latch">200 ms</span>
            </div>
            <input type="range" id="slider-m2-latch" min="50" max="500" step="25" value="200" style="width:100%;" title="Adjust M2 Bayesian output latch confirmation time">
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Min Confidence: <span class="info-icon" title="Minimum posterior probability required to declare a gear. Below this threshold, estimator outputs Uncertain (14) instead of guessing.">i</span></span>
              <span class="ctrl-val" id="val-m2-conf">0.38</span>
            </div>
            <input type="range" id="slider-m2-conf" min="0.20" max="0.60" step="0.02" value="0.38" style="width:100%;" title="Adjust M2 minimum posterior confidence threshold">
          </div>

          <!-- Model 3 Params -->
          <div style="border-left:2px solid #10b981; padding-left:0.45rem; margin-bottom:0.45rem;">
            <strong style="color:#10b981;">M3: HMM State-Space</strong>
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Self-Inertia A<sub>ii</sub>: <span class="info-icon" title="Diagonal persistence in the 6x6 transition matrix. High values prevent erratic gear jumping and enforce Markov state stability.">i</span></span>
              <span class="ctrl-val" id="val-m3-inertia">0.970</span>
            </div>
            <input type="range" id="slider-m3-inertia" min="0.85" max="0.999" step="0.005" value="0.97" style="width:100%;" title="Adjust M3 HMM transition matrix diagonal self-inertia">
            <div style="display:flex; justify-content:space-between; margin-top:0.2rem;">
              <span>Clutch Decel Cutoff: <span class="info-icon" title="Detects rapid engine deceleration during clutch-in coasting (e.g. < -40 Hz/s ≈ -1200 RPM/s). Suppresses false upward gear transitions while engine speed falls towards idle.">i</span></span>
              <span class="ctrl-val" id="val-m3-decel">-40 Hz/s</span>
            </div>
            <input type="range" id="slider-m3-decel" min="-80" max="-15" step="5" value="-40" style="width:100%;" title="Adjust M3 clutch-in deceleration detection threshold">
          </div>

          <div style="display:flex; gap:0.35rem; margin-top:0.4rem;">
            <button id="btn-apply-tuning" class="btn-primary" style="flex:1; padding:0.25rem 0.4rem; font-size:0.72rem;" title="Re-evaluate all 3 models across the dataset using current tuning parameters">⚡ Apply & Evaluate</button>
            <button id="btn-reset-tuning" style="padding:0.25rem 0.4rem; font-size:0.72rem;" title="Reset model parameters to calibrated baseline">↺ Reset</button>
          </div>
          <div style="display:flex; gap:0.35rem; margin-top:0.35rem;">
            <button id="btn-auto-optimize" data-alias="btn-auto-tune" class="btn-accent" style="width:100%; padding:0.3rem 0.4rem; font-size:0.72rem;" title="Run automated parameter grid search to maximize glitch-free scores">⚡ Auto-Optimize Parameters</button>
          </div>
          <div style="display:flex; gap:0.35rem; margin-top:0.35rem;">
            <button id="btn-save-shared-cal" style="flex:1; padding:0.22rem 0.35rem; font-size:0.68rem;" title="Save current tuning parameters to decoder/gear_calibration.json">💾 Save Shared Cal</button>
            <button id="btn-load-shared-cal" style="flex:1; padding:0.22rem 0.35rem; font-size:0.68rem;" title="Load parameters from decoder/gear_calibration.json">📥 Load Shared Cal</button>
          </div>
        </div>
      </div>

      <div class="card" style="border-left:3px solid var(--accent);">
        <div class="card-title" style="color:var(--accent);">ESP32 Deployment Notes</div>
        <div style="font-size:0.72rem; color:var(--text-muted); line-height:1.4;">
          All 3 models run with <strong>zero heap allocation</strong>.<br>
          • M1: ~0.4 &mu;s execution (table lookup)<br>
          • M2: ~1.5 &mu;s (Kinematic Bayes + latch)<br>
          • M3: ~1.8 &mu;s (36 MAC operations)<br>
          RAM footprint: <strong>&lt; 64 bytes</strong>.
        </div>
      </div>
    </div>

    <!-- MAIN CONTENT PANE -->
    <div class="content-pane">
      <!-- Tab Navigation -->
      <div class="tabs-bar">
        <button class="tab-btn active" data-tab="tab-overview" id="tabbtn-overview">🏁 Multi-Model Overview</button>
        <button class="tab-btn" data-tab="tab-m1" id="tabbtn-m1">⚙️ Model 1: Heuristic</button>
        <button class="tab-btn" data-tab="tab-m2" id="tabbtn-m2">🧠 Model 2: Kinematic Bayes</button>
        <button class="tab-btn" data-tab="tab-m3" id="tabbtn-m3">🕸️ Model 3: HMM State-Space</button>
      </div>

      <!-- Shared Replayer Transport Controls Bar -->
      <div class="card" style="padding:0.45rem 0.75rem; flex-shrink:0;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:0.8rem; flex-wrap:wrap;">
          <div style="display:flex; align-items:center; gap:0.35rem;">
            <button id="btn-replay-play" class="btn-primary" style="padding:0.22rem 0.55rem; font-size:0.75rem;">▶ Play</button>
            <button id="btn-replay-reset" style="padding:0.22rem 0.45rem; font-size:0.75rem;">⏹ Reset</button>
            <button id="btn-replay-prev" style="padding:0.22rem 0.4rem; font-size:0.75rem;" title="Step Back 100ms">◀</button>
            <button id="btn-replay-next" style="padding:0.22rem 0.4rem; font-size:0.75rem;" title="Step Forward 100ms">▶</button>
            <select id="select-replay-speed" style="padding:0.18rem 0.35rem; font-size:0.72rem;">
              <option value="0.25">0.25x</option>
              <option value="0.5">0.5x</option>
              <option value="1.0" selected>1.0x</option>
              <option value="2.0">2.0x</option>
              <option value="5.0">5.0x</option>
            </select>
          </div>
          <div style="flex:1; min-width:180px; display:flex; align-items:center; gap:0.5rem;">
            <input type="range" id="slider-replay-scrub" min="0" max="100" step="0.05" value="0" style="flex:1;">
            <span id="lbl-replay-time" style="font-family:monospace; font-size:0.74rem; color:var(--text-muted); white-space:nowrap;">0.00s / 0.00s</span>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 1: MULTI-MODEL OVERVIEW                                         -->
      <!-- =================================================================== -->
      <div class="tab-content" id="tab-overview">
        <!-- Comparative Benchmark Matrix -->
        <div class="card" style="padding:0.5rem 0.75rem; flex-shrink:0;">
          <table class="benchmark-table">
            <thead>
              <tr>
                <th>Model Variant</th>
                <th>Glitch-Free Score</th>
                <th>Neutral Dropouts</th>
                <th>Chatter (&lt;300ms)</th>
                <th>Coast Phantoms</th>
                <th>Active Drive %</th>
                <th>ESP32 Architecture</th>
              </tr>
            </thead>
            <tbody id="benchmark-tbody">
              <tr>
                <td><span class="model-badge badge-m1">M1: Gated Heuristic</span></td>
                <td class="val-good" id="m1-score">--%</td>
                <td id="m1-drop">--</td>
                <td id="m1-chat">--</td>
                <td id="m1-phan">--</td>
                <td id="m1-act">--%</td>
                <td style="color:var(--text-muted); font-size:0.72rem;">Static hysteresis timer</td>
              </tr>
              <tr>
                <td><span class="model-badge badge-m2">M2: Kinematic Bayes</span></td>
                <td class="val-good" id="m2-score">--%</td>
                <td id="m2-drop">--</td>
                <td id="m2-chat">--</td>
                <td id="m2-phan">--</td>
                <td id="m2-act">--%</td>
                <td style="color:var(--text-muted); font-size:0.72rem;">Kinematic transition prior</td>
              </tr>
              <tr>
                <td><span class="model-badge badge-m3">M3: HMM State-Space</span></td>
                <td class="val-good" id="m3-score">--%</td>
                <td id="m3-drop">--</td>
                <td id="m3-chat">--</td>
                <td id="m3-phan">--</td>
                <td id="m3-act">--%</td>
                <td style="color:var(--text-muted); font-size:0.72rem;">6-state forward filter</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Triple Simulated Diagnostic Gauge Pod -->
        <div class="card" style="padding:0.5rem 0.75rem; flex-shrink:0;">
          <div id="triple-gauge-pod" style="display:grid; grid-template-columns: repeat(3, 1fr); gap:0.5rem;">
            <!-- Pod 1: M1 Heuristic -->
            <div style="background:var(--input-bg); border:1px solid var(--panel-border); border-left:3px solid #3b82f6; border-radius:6px; padding:0.4rem 0.6rem;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.68rem; font-weight:700; color:#3b82f6;">M1: HEURISTIC</span>
                <span id="m1-pod-status" class="model-badge badge-m1" style="font-size:0.60rem;">LATCHED</span>
              </div>
              <div style="display:flex; align-items:center; gap:0.6rem; margin-top:0.15rem;">
                <span id="m1-pod-gear" style="font-size:1.75rem; font-weight:800; font-family:monospace; line-height:1; color:#3b82f6;">N</span>
                <div style="font-size:0.68rem; font-family:monospace; color:var(--text-muted); line-height:1.25;">
                  <div>Speed: <span id="m1-pod-speed" style="color:var(--text); font-weight:600;">0.0 km/h</span></div>
                  <div>RPM: <span id="m1-pod-rpm" style="color:var(--text); font-weight:600;">0 RPM</span></div>
                  <div>Ratio: <span id="m1-pod-ratio" style="color:var(--text); font-weight:600;">--</span></div>
                </div>
              </div>
            </div>

            <!-- Pod 2: M2 Kinematic Bayes -->
            <div style="background:var(--input-bg); border:1px solid var(--panel-border); border-left:3px solid #f59e0b; border-radius:6px; padding:0.4rem 0.6rem;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.68rem; font-weight:700; color:#f59e0b;">M2: KINEMATIC BAYES</span>
                <span id="m2-pod-regime" class="model-badge badge-m2" style="font-size:0.60rem;">CORRIDOR LOCK</span>
              </div>
              <div style="display:flex; align-items:center; gap:0.6rem; margin-top:0.15rem;">
                <span id="m2-pod-gear" style="font-size:1.75rem; font-weight:800; font-family:monospace; line-height:1; color:#f59e0b;">N</span>
                <div style="font-size:0.68rem; font-family:monospace; color:var(--text-muted); line-height:1.25;">
                  <div>Bayes Conf: <span id="m2-pod-prob" style="color:var(--text); font-weight:600;">--%</span></div>
                  <div>Context: <span id="m2-pod-context" style="color:var(--text); font-weight:600;">Steady</span></div>
                  <div>Ratio: <span id="m2-pod-ratio" style="color:var(--text); font-weight:600;">--</span></div>
                </div>
              </div>
            </div>

            <!-- Pod 3: M3 HMM -->
            <div style="background:var(--input-bg); border:1px solid var(--panel-border); border-left:3px solid #10b981; border-radius:6px; padding:0.4rem 0.6rem;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.68rem; font-weight:700; color:#10b981;">M3: HMM STATE-SPACE</span>
                <span id="m3-pod-state" class="model-badge badge-m3" style="font-size:0.60rem;">ENGAGED</span>
              </div>
              <div style="display:flex; align-items:center; gap:0.6rem; margin-top:0.15rem;">
                <span id="m3-pod-gear" style="font-size:1.75rem; font-weight:800; font-family:monospace; line-height:1; color:#10b981;">N</span>
                <div style="font-size:0.68rem; font-family:monospace; color:var(--text-muted); line-height:1.25;">
                  <div>Forward &alpha;: <span id="m3-pod-alpha" style="color:var(--text); font-weight:600;">--%</span></div>
                  <div>Emission: <span id="m3-pod-emission" style="color:var(--text); font-weight:600;">Inertial</span></div>
                  <div>Ratio: <span id="m3-pod-ratio" style="color:var(--text); font-weight:600;">--</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Plots Column -->
        <div class="plots-column">
          <div class="plot-box" id="plot-ratio-hist" style="flex:0.75;"></div>
          <div class="plot-box" id="plot-dynamics" style="flex:0.7;"></div>

          <!-- Timeline Mode Bar -->
          <div style="display:flex; justify-content:space-between; align-items:center; background:var(--card-bg); padding:0.3rem 0.6rem; border:1px solid var(--panel-border); border-radius:6px; font-size:0.74rem;">
            <div style="display:flex; align-items:center; gap:0.5rem;">
              <span style="font-weight:600;">Timeline Mode:</span>
              <div style="display:inline-flex; border:1px solid var(--panel-border); border-radius:4px; overflow:hidden;">
                <button id="btn-view-shared" style="padding:0.18rem 0.45rem; font-size:0.70rem; cursor:pointer; background:var(--primary); color:#ffffff; border:none;">🔀 Shared Overlay</button>
                <button id="btn-view-stacked" style="padding:0.18rem 0.45rem; font-size:0.70rem; cursor:pointer; background:var(--input-bg); color:var(--text); border:none;">🥞 Stacked Subplots</button>
              </div>
              <div style="display:flex; align-items:center; gap:0.45rem; margin-left:0.3rem;">
                <label style="cursor:pointer; display:flex; align-items:center; gap:0.2rem;"><input type="checkbox" id="chk-show-m1" checked> <span style="color:#3b82f6; font-weight:600;">M1</span></label>
                <label style="cursor:pointer; display:flex; align-items:center; gap:0.2rem;"><input type="checkbox" id="chk-show-m2" checked> <span style="color:#f59e0b; font-weight:600;">M2</span></label>
                <label style="cursor:pointer; display:flex; align-items:center; gap:0.2rem;"><input type="checkbox" id="chk-show-m3" checked> <span style="color:#10b981; font-weight:600;">M3</span></label>
                <label style="cursor:pointer; display:flex; align-items:center; gap:0.2rem;"><input type="checkbox" id="chk-show-gt"> <span style="color:#94a3b8;">GT</span></label>
              </div>
            </div>
            <div style="display:flex; align-items:center; gap:0.4rem; font-size:0.70rem; color:var(--text-muted);">
              <span style="font-weight:600;">Glitch Callouts:</span>
              <span title="Neutral Dropout (<450ms while rolling)">🔴 Dropout</span>
              <span title="Rapid Chatter (<300ms dwell)">🟠 Chatter</span>
              <span title="Phantom Upshift during deceleration">🟣 Phantom</span>
            </div>
          </div>

          <div class="plot-box" id="plot-models-compare" style="flex:1.2;"></div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 2: MODEL 1 DEDICATED (GATED HEURISTIC)                          -->
      <!-- =================================================================== -->
      <div class="tab-content" id="tab-m1" style="display:none;">
        <!-- Top Banner: M1 Scorecard & Single Gauge Pod -->
        <div style="display:grid; grid-template-columns: 2fr 1fr; gap:0.5rem; flex-shrink:0;">
          <div class="card" style="display:flex; flex-direction:column; justify-content:space-around;">
            <div class="card-title" style="color:#3b82f6;">M1: Gated Heuristic Scorecard</div>
            <div style="display:grid; grid-template-columns: repeat(5, 1fr); gap:0.4rem; text-align:center;">
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Glitch Score</div>
                <div id="m1-tab-score" style="font-size:1.2rem; font-weight:800; color:var(--accent);">--%</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Dropouts</div>
                <div id="m1-tab-drop" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Chatter</div>
                <div id="m1-tab-chat" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Phantoms</div>
                <div id="m1-tab-phan" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Active Drive</div>
                <div id="m1-tab-act" style="font-size:1.2rem; font-weight:700; color:var(--primary);">--%</div>
              </div>
            </div>
          </div>

          <!-- M1 Single Gauge Pod -->
          <div class="card" style="border-left:3px solid #3b82f6; display:flex; align-items:center; justify-content:space-between; padding:0.4rem 0.8rem;">
            <div>
              <div style="font-size:0.65rem; font-weight:700; color:#3b82f6;">SIMULATED GAUGE POD</div>
              <div id="m1-single-gear" style="font-size:2.2rem; font-weight:800; font-family:monospace; line-height:1; color:#3b82f6;">N</div>
            </div>
            <div style="font-size:0.70rem; font-family:monospace; color:var(--text-muted); line-height:1.35; text-align:right;">
              <div>Speed: <span id="m1-single-speed" style="color:var(--text); font-weight:600;">0.0 km/h</span></div>
              <div>RPM: <span id="m1-single-rpm" style="color:var(--text); font-weight:600;">0 RPM</span></div>
              <div>Smoothed Ratio: <span id="m1-single-ratio" style="color:var(--text); font-weight:600;">--</span></div>
              <div>Status: <span id="m1-single-status" class="model-badge badge-m1" style="font-size:0.62rem;">LATCHED</span></div>
            </div>
          </div>
        </div>

        <!-- M1 Plots Column -->
        <div class="plots-column">
          <div class="plot-box" id="plot-m1-hist" style="flex:0.75;"></div>
          <div class="plot-box" id="plot-m1-dyn" style="flex:0.7;"></div>
          <div class="plot-box" id="plot-m1-trace" style="flex:1.2;"></div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 3: MODEL 2 DEDICATED (KINEMATIC BAYES)                          -->
      <!-- =================================================================== -->
      <div class="tab-content" id="tab-m2" style="display:none;">
        <!-- Top Banner: M2 Scorecard & Single Gauge Pod -->
        <div style="display:grid; grid-template-columns: 2fr 1fr; gap:0.5rem; flex-shrink:0;">
          <div class="card" style="display:flex; flex-direction:column; justify-content:space-around;">
            <div class="card-title" style="color:#f59e0b;">M2: Kinematic Bayes Scorecard</div>
            <div style="display:grid; grid-template-columns: repeat(5, 1fr); gap:0.4rem; text-align:center;">
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Glitch Score</div>
                <div id="m2-tab-score" style="font-size:1.2rem; font-weight:800; color:var(--accent);">--%</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Dropouts</div>
                <div id="m2-tab-drop" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Chatter</div>
                <div id="m2-tab-chat" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Phantoms</div>
                <div id="m2-tab-phan" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Active Drive</div>
                <div id="m2-tab-act" style="font-size:1.2rem; font-weight:700; color:var(--warning);">--%</div>
              </div>
            </div>
          </div>

          <!-- M2 Single Gauge Pod -->
          <div class="card" style="border-left:3px solid #f59e0b; display:flex; align-items:center; justify-content:space-between; padding:0.4rem 0.8rem;">
            <div>
              <div style="font-size:0.65rem; font-weight:700; color:#f59e0b;">SIMULATED GAUGE POD</div>
              <div id="m2-single-gear" style="font-size:2.2rem; font-weight:800; font-family:monospace; line-height:1; color:#f59e0b;">N</div>
            </div>
            <div style="font-size:0.70rem; font-family:monospace; color:var(--text-muted); line-height:1.35; text-align:right;">
              <div>Speed: <span id="m2-single-speed" style="color:var(--text); font-weight:600;">0.0 km/h</span></div>
              <div>RPM: <span id="m2-single-rpm" style="color:var(--text); font-weight:600;">0 RPM</span></div>
              <div>Bayes Conf: <span id="m2-single-prob" style="color:var(--text); font-weight:600;">--%</span></div>
              <div>Context: <span id="m2-single-context" class="model-badge badge-m2" style="font-size:0.62rem;">CORRIDOR LOCK</span></div>
            </div>
          </div>
        </div>

        <!-- M2 Plots Column -->
        <div class="plots-column">
          <div class="plot-box" id="plot-m2-corridors" style="flex:0.75;"></div>
          <div class="plot-box" id="plot-m2-dyn" style="flex:0.7;"></div>
          <div class="plot-box" id="plot-m2-trace" style="flex:1.2;"></div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 4: MODEL 3 DEDICATED (HMM STATE-SPACE)                          -->
      <!-- =================================================================== -->
      <div class="tab-content" id="tab-m3" style="display:none;">
        <!-- Top Banner: M3 Scorecard & Single Gauge Pod -->
        <div style="display:grid; grid-template-columns: 2fr 1fr; gap:0.5rem; flex-shrink:0;">
          <div class="card" style="display:flex; flex-direction:column; justify-content:space-around;">
            <div class="card-title" style="color:#10b981;">M3: HMM State-Space Scorecard</div>
            <div style="display:grid; grid-template-columns: repeat(5, 1fr); gap:0.4rem; text-align:center;">
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Glitch Score</div>
                <div id="m3-tab-score" style="font-size:1.2rem; font-weight:800; color:var(--accent);">--%</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Dropouts</div>
                <div id="m3-tab-drop" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Chatter</div>
                <div id="m3-tab-chat" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Phantoms</div>
                <div id="m3-tab-phan" style="font-size:1.2rem; font-weight:700;">--</div>
              </div>
              <div>
                <div style="font-size:0.68rem; color:var(--text-muted);">Active Drive</div>
                <div id="m3-tab-act" style="font-size:1.2rem; font-weight:700; color:var(--accent);">--%</div>
              </div>
            </div>
          </div>

          <!-- M3 Single Gauge Pod -->
          <div class="card" style="border-left:3px solid #10b981; display:flex; align-items:center; justify-content:space-between; padding:0.4rem 0.8rem;">
            <div>
              <div style="font-size:0.65rem; font-weight:700; color:#10b981;">SIMULATED GAUGE POD</div>
              <div id="m3-single-gear" style="font-size:2.2rem; font-weight:800; font-family:monospace; line-height:1; color:#10b981;">N</div>
            </div>
            <div style="font-size:0.70rem; font-family:monospace; color:var(--text-muted); line-height:1.35; text-align:right;">
              <div>Speed: <span id="m3-single-speed" style="color:var(--text); font-weight:600;">0.0 km/h</span></div>
              <div>RPM: <span id="m3-single-rpm" style="color:var(--text); font-weight:600;">0 RPM</span></div>
              <div>Forward &alpha;: <span id="m3-single-alpha" style="color:var(--text); font-weight:600;">--%</span></div>
              <div>Emission: <span id="m3-single-emission" class="model-badge badge-m3" style="font-size:0.62rem;">ENGAGED</span></div>
            </div>
          </div>
        </div>

        <!-- M3 Plots Column -->
        <div class="plots-column">
          <div class="plot-box" id="plot-m3-matrix" style="flex:0.75;"></div>
          <div class="plot-box" id="plot-m3-dyn" style="flex:0.7;"></div>
          <div class="plot-box" id="plot-m3-trace" style="flex:1.2;"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Auto-Optimizer Modal -->
  <div class="modal-overlay" id="optimizer-modal">
    <div class="modal-content" style="max-width: 620px;">
      <div class="modal-header">
        <strong style="font-size:0.95rem;">⚡ Model Parameter Auto-Optimization Complete</strong>
        <button id="btn-close-opt-modal" style="padding:0.2rem 0.5rem;">✕</button>
      </div>
      <div class="modal-body" style="display:flex; flex-direction:column; gap:0.8rem;">
        <div style="display:flex; align-items:center; justify-content:space-between; background:var(--input-bg); border:1px solid var(--panel-border); border-radius:6px; padding:0.6rem 0.8rem;">
          <div>
            <div style="font-size:0.70rem; color:var(--text-muted); text-transform:uppercase;">Overall Multi-Model Glitch Score</div>
            <div style="font-size:1.35rem; font-weight:800; font-family:monospace; display:flex; align-items:center; gap:0.5rem; margin-top:0.15rem;">
              <span id="opt-before-score" style="color:var(--text-muted);">--%</span>
              <span>&rarr;</span>
              <span id="opt-after-score" style="color:var(--accent);">--%</span>
              <span id="opt-delta-badge" class="model-badge badge-m3" style="font-size:0.75rem;">+0.0%</span>
            </div>
          </div>
          <div style="text-align:right; font-size:0.75rem; color:var(--text-muted);">
            Target: <strong id="opt-target-log" style="color:var(--text);">All Logs</strong>
          </div>
        </div>

        <div style="font-size:0.76rem; font-weight:700; color:var(--text-muted); text-transform:uppercase;">
          Parameter Exploration & Delta Matrix
        </div>
        <table style="width:100%; font-size:0.80rem; border-collapse:collapse;" id="opt-table-changes">
          <thead>
            <tr style="border-bottom:1px solid var(--panel-border); color:var(--text-muted); font-size:0.70rem; background:var(--input-bg);">
              <th style="padding:0.4rem 0.6rem; text-align:left;">Parameter</th>
              <th style="padding:0.4rem 0.6rem; text-align:right;">Current</th>
              <th style="padding:0.4rem 0.6rem; text-align:right;">Optimized</th>
            </tr>
          </thead>
          <tbody id="opt-tbody-changes">
            <!-- Injected by JS -->
          </tbody>
        </table>

        <div style="display:flex; justify-content:flex-end; gap:0.5rem; margin-top:0.4rem;">
          <button id="btn-opt-dismiss">Dismiss</button>
          <button id="btn-opt-apply" class="btn-primary">⚡ Apply & Save to Calibration</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Export C Header Modal -->
  <div class="modal-overlay" id="export-modal">
    <div class="modal-content">
      <div class="modal-header">
        <strong style="font-size:0.95rem;">💾 Generated ESP32 C Header (gear_estimator_params.h)</strong>
        <button id="btn-close-modal" style="padding:0.2rem 0.5rem;">✕</button>
      </div>
      <div class="modal-body">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.6rem;">
          <span style="font-size:0.78rem; color:var(--text-muted);">Ready-to-compile, zero-allocation C99 implementation for ESP-IDF:</span>
          <div style="display:flex; gap:0.5rem;">
            <button id="btn-copy-c">📋 Copy Code</button>
            <a id="btn-download-c" href="/api/export_c" download="gear_estimator_params.h" style="text-decoration:none;">
              <button class="btn-primary">⬇️ Download .h</button>
            </a>
          </div>
        </div>
        <pre class="code-block" id="c-code-preview">// Loading code...</pre>
      </div>
    </div>
  </div>

  <script>
    let currentTheme = localStorage.getItem('minigauge_theme') || 'dark';
    let datasetData = null;
    let currentLog = 'all';
    let activeTabId = 'tab-overview';
    let timelineViewMode = 'shared'; // 'shared' or 'stacked'
    let lastOptResults = null;

    function initTheme() {
      if (currentTheme === 'light') {
        document.body.classList.add('theme-light');
      } else {
        document.body.classList.remove('theme-light');
      }
    }
    initTheme();

    document.getElementById('btn-theme').addEventListener('click', () => {
      currentTheme = (currentTheme === 'dark') ? 'light' : 'dark';
      localStorage.setItem('minigauge_theme', currentTheme);
      initTheme();
      renderActiveTabPlots();
    });

    function getPlotlyTheme() {
      const isLight = document.body.classList.contains('theme-light');
      return {
        paper_bgcolor: isLight ? '#ffffff' : '#1e293b',
        plot_bgcolor: isLight ? '#ffffff' : '#1e293b',
        font: { color: isLight ? '#0f172a' : '#f8fafc', size: 10 },
        gridcolor: isLight ? '#e2e8f0' : '#334155'
      };
    }

    // =========================================================================
    // TAB SWITCHER
    // =========================================================================
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
        btn.classList.add('active');
        activeTabId = btn.dataset.tab;
        const target = document.getElementById(activeTabId);
        if (target) target.style.display = 'flex';
        renderActiveTabPlots();
        updateReplayDisplay(replayer.currentTime);
      });
    });

    // Collapsible Card Toggles
    const btnToggleTheory = document.getElementById('btn-toggle-theory');
    if (btnToggleTheory) {
      btnToggleTheory.addEventListener('click', () => {
        const body = document.getElementById('theory-body');
        const arrow = document.getElementById('theory-arrow');
        const isOpen = body.style.display !== 'none';
        body.style.display = isOpen ? 'none' : 'block';
        arrow.innerText = isOpen ? '▶ Expand' : '▼ Collapse';
      });
    }

    const btnToggleTuning = document.getElementById('btn-toggle-tuning');
    if (btnToggleTuning) {
      btnToggleTuning.addEventListener('click', () => {
        const body = document.getElementById('tuning-body');
        const arrow = document.getElementById('tuning-arrow');
        const isOpen = body.style.display !== 'none';
        body.style.display = isOpen ? 'none' : 'block';
        arrow.innerText = isOpen ? '▶ Expand' : '▼ Collapse';
      });
    }

    // Tuning Sliders Live Value Labels
    function setupSliderSync(id, valId, formatFn) {
      const el = document.getElementById(id);
      const valEl = document.getElementById(valId);
      if (el && valEl) {
        el.addEventListener('input', () => {
          valEl.innerText = formatFn(parseFloat(el.value));
        });
      }
    }
    setupSliderSync('slider-cutoff-speed', 'val-cutoff-speed', v => `${v.toFixed(2)} Hz (${(v * 2.214).toFixed(0)} km/h)`);
    setupSliderSync('slider-cutoff-rpm', 'val-cutoff-rpm', v => `${v.toFixed(2)} Hz (${(v * 30.0).toFixed(0)} RPM)`);
    setupSliderSync('slider-m1-alpha', 'val-m1-alpha', v => v.toFixed(2));
    setupSliderSync('slider-m1-tol', 'val-m1-tol', v => '±' + v.toFixed(2));
    setupSliderSync('slider-m1-latch', 'val-m1-latch', v => Math.round(v) + ' ms');
    setupSliderSync('slider-m2-decay', 'val-m2-decay', v => v.toFixed(2));
    setupSliderSync('slider-m2-inertia', 'val-m2-inertia', v => v.toFixed(3));
    setupSliderSync('slider-m2-latch', 'val-m2-latch', v => Math.round(v) + ' ms');
    setupSliderSync('slider-m2-conf', 'val-m2-conf', v => v.toFixed(2));
    setupSliderSync('slider-m3-inertia', 'val-m3-inertia', v => v.toFixed(3));
    setupSliderSync('slider-m3-decel', 'val-m3-decel', v => Math.round(v) + ' Hz/s');

    function getTuningQuery() {
      const p = [];
      const getVal = id => document.getElementById(id) ? document.getElementById(id).value : null;
      if (getVal('slider-cutoff-speed')) p.push(`min_speed_hz=${getVal('slider-cutoff-speed')}`);
      if (getVal('slider-cutoff-rpm')) p.push(`min_rpm_hz=${getVal('slider-cutoff-rpm')}`);
      if (getVal('slider-m1-alpha')) p.push(`m1_alpha=${getVal('slider-m1-alpha')}`);
      if (getVal('slider-m1-tol')) p.push(`m1_tol=${getVal('slider-m1-tol')}`);
      if (getVal('slider-m1-latch')) p.push(`m1_latch_ms=${getVal('slider-m1-latch')}`);
      if (getVal('slider-m2-decay')) p.push(`m2_decay=${getVal('slider-m2-decay')}`);
      if (getVal('slider-m2-inertia')) p.push(`m2_inertia=${getVal('slider-m2-inertia')}`);
      if (getVal('slider-m2-latch')) p.push(`m2_latch_ms=${getVal('slider-m2-latch')}`);
      if (getVal('slider-m2-conf')) p.push(`m2_conf=${getVal('slider-m2-conf')}`);
      if (getVal('slider-m3-inertia')) p.push(`m3_inertia=${getVal('slider-m3-inertia')}`);
      if (getVal('slider-m3-decel')) p.push(`m3_decel=${getVal('slider-m3-decel')}`);
      return p.join('&');
    }

    document.getElementById('btn-apply-tuning').addEventListener('click', () => {
      loadDataset();
    });

    document.getElementById('btn-reset-tuning').addEventListener('click', () => {
      document.getElementById('slider-cutoff-speed').value = 11.28;
      document.getElementById('val-cutoff-speed').innerText = '11.28 Hz (25 km/h)';
      document.getElementById('slider-cutoff-rpm').value = 33.33;
      document.getElementById('val-cutoff-rpm').innerText = '33.33 Hz (1000 RPM)';

      document.getElementById('slider-m1-alpha').value = 0.15;
      document.getElementById('val-m1-alpha').innerText = '0.15';
      document.getElementById('slider-m1-tol').value = 0.25;
      document.getElementById('val-m1-tol').innerText = '±0.25';
      document.getElementById('slider-m1-latch').value = 200;
      document.getElementById('val-m1-latch').innerText = '200 ms';

      document.getElementById('slider-m2-decay').value = 0.94;
      document.getElementById('val-m2-decay').innerText = '0.94';
      document.getElementById('slider-m2-inertia').value = 0.96;
      document.getElementById('val-m2-inertia').innerText = '0.960';
      document.getElementById('slider-m2-latch').value = 200;
      document.getElementById('val-m2-latch').innerText = '200 ms';
      document.getElementById('slider-m2-conf').value = 0.38;
      document.getElementById('val-m2-conf').innerText = '0.38';

      document.getElementById('slider-m3-inertia').value = 0.970;
      document.getElementById('val-m3-inertia').innerText = '0.970';
      document.getElementById('slider-m3-decel').value = -40;
      document.getElementById('val-m3-decel').innerText = '-40 Hz/s';

      loadDataset();
    });

    // View Mode Switcher
    const btnViewShared = document.getElementById('btn-view-shared');
    const btnViewStacked = document.getElementById('btn-view-stacked');

    btnViewShared.addEventListener('click', () => {
      timelineViewMode = 'shared';
      btnViewShared.style.background = 'var(--primary)';
      btnViewShared.style.color = '#ffffff';
      btnViewStacked.style.background = 'var(--input-bg)';
      btnViewStacked.style.color = 'var(--text)';
      renderOverviewPlots();
    });

    btnViewStacked.addEventListener('click', () => {
      timelineViewMode = 'stacked';
      btnViewStacked.style.background = 'var(--primary)';
      btnViewStacked.style.color = '#ffffff';
      btnViewShared.style.background = 'var(--input-bg)';
      btnViewShared.style.color = 'var(--text)';
      renderOverviewPlots();
    });

    ['chk-show-m1', 'chk-show-m2', 'chk-show-m3', 'chk-show-gt'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', renderOverviewPlots);
    });

    async function loadDataset() {
      try {
        const query = getTuningQuery();
        const url = `/api/dataset?log=${encodeURIComponent(currentLog)}${query ? '&' + query : ''}`;
        const res = await fetch(url);
        datasetData = await res.json();
        updateUI();
        renderActiveTabPlots();
        initReplayer(datasetData);
      } catch (err) {
        console.error('Failed to load dataset:', err);
      }
    }

    async function loadLogsList() {
      try {
        const res = await fetch('/api/logs');
        const logs = await res.json();
        const sel = document.getElementById('select-log');
        sel.innerHTML = '<option value="all">⚡ All Combined Logs (Concatenated Aggregated)</option>';
        logs.forEach(l => {
          const opt = document.createElement('option');
          opt.value = l.filename;
          opt.innerText = `${l.filename} (${(l.size/1024).toFixed(0)} KB)`;
          sel.appendChild(opt);
        });
        document.getElementById('stat-log-count').innerText = logs.length;
      } catch (e) {
        console.error('Failed to load logs:', e);
      }
    }

    document.getElementById('select-log').addEventListener('change', (e) => {
      currentLog = e.target.value;
      loadDataset();
    });

    document.getElementById('btn-retrain').addEventListener('click', async () => {
      const btn = document.getElementById('btn-retrain');
      btn.innerText = '⏳ Training...';
      btn.disabled = true;
      try {
        const res = await fetch('/api/train', { method: 'POST' });
        const resData = await res.json();
        alert(`Models trained across all logs! Found 5 cluster peaks: ${resData.means.join(', ')}`);
        await loadDataset();
      } catch(e) {
        alert('Training failed: ' + e);
      } finally {
        btn.innerText = '⚡ Train Models';
        btn.disabled = false;
      }
    });

    document.getElementById('btn-export-c').addEventListener('click', async () => {
      const modal = document.getElementById('export-modal');
      modal.style.display = 'flex';
      try {
        const res = await fetch('/api/export_c');
        const code = await res.text();
        document.getElementById('c-code-preview').innerText = code;
      } catch (e) {
        document.getElementById('c-code-preview').innerText = '// Failed to fetch code: ' + e;
      }
    });

    document.getElementById('btn-close-modal').addEventListener('click', () => {
      document.getElementById('export-modal').style.display = 'none';
    });

    document.getElementById('btn-copy-c').addEventListener('click', () => {
      const code = document.getElementById('c-code-preview').innerText;
      navigator.clipboard.writeText(code).then(() => {
        const btn = document.getElementById('btn-copy-c');
        btn.innerText = '✓ Copied!';
        setTimeout(() => { btn.innerText = '📋 Copy Code'; }, 1500);
      });
    });

    function updateUI() {
      if (!datasetData) return;
      document.getElementById('stat-sample-count').innerText = datasetData.total_driving_samples.toLocaleString();

      const f = datasetData.fitted;
      const tbody = document.getElementById('tbl-cluster-body');
      tbody.innerHTML = '';
      for (let i = 0; i < 5; i++) {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid var(--panel-border)';
        tr.innerHTML = `
          <td style="font-weight:700; color:var(--primary);">${i + 1}st</td>
          <td style="font-family:monospace;">${f.means[i].toFixed(3)}</td>
          <td style="font-family:monospace; color:var(--text-muted);">&plusmn;${f.stds[i].toFixed(3)}</td>
          <td style="font-family:monospace;">${f.counts[i].toLocaleString()}</td>
        `;
        tbody.appendChild(tr);
      }

      // Update benchmark table & dedicated tab scorecards
      const b = datasetData.benchmarks;
      if (b) {
        const setScore = (id, sc) => {
          const el = document.getElementById(id);
          if (!el) return;
          el.innerText = sc + '%';
          el.className = sc >= 90 ? 'val-good' : (sc >= 75 ? 'val-warn' : 'val-bad');
        };

        setScore('m1-score', b.m1.glitch_score);
        document.getElementById('m1-drop').innerText = b.m1.dropouts;
        document.getElementById('m1-chat').innerText = b.m1.chatter;
        document.getElementById('m1-phan').innerText = b.m1.phantoms;
        document.getElementById('m1-act').innerText = b.m1.active_pct + '%';

        setScore('m1-tab-score', b.m1.glitch_score);
        document.getElementById('m1-tab-drop').innerText = b.m1.dropouts;
        document.getElementById('m1-tab-chat').innerText = b.m1.chatter;
        document.getElementById('m1-tab-phan').innerText = b.m1.phantoms;
        document.getElementById('m1-tab-act').innerText = b.m1.active_pct + '%';

        setScore('m2-score', b.m2.glitch_score);
        document.getElementById('m2-drop').innerText = b.m2.dropouts;
        document.getElementById('m2-chat').innerText = b.m2.chatter;
        document.getElementById('m2-phan').innerText = b.m2.phantoms;
        document.getElementById('m2-act').innerText = b.m2.active_pct + '%';

        setScore('m2-tab-score', b.m2.glitch_score);
        document.getElementById('m2-tab-drop').innerText = b.m2.dropouts;
        document.getElementById('m2-tab-chat').innerText = b.m2.chatter;
        document.getElementById('m2-tab-phan').innerText = b.m2.phantoms;
        document.getElementById('m2-tab-act').innerText = b.m2.active_pct + '%';

        setScore('m3-score', b.m3.glitch_score);
        document.getElementById('m3-drop').innerText = b.m3.dropouts;
        document.getElementById('m3-chat').innerText = b.m3.chatter;
        document.getElementById('m3-phan').innerText = b.m3.phantoms;
        document.getElementById('m3-act').innerText = b.m3.active_pct + '%';

        setScore('m3-tab-score', b.m3.glitch_score);
        document.getElementById('m3-tab-drop').innerText = b.m3.dropouts;
        document.getElementById('m3-tab-chat').innerText = b.m3.chatter;
        document.getElementById('m3-tab-phan').innerText = b.m3.phantoms;
        document.getElementById('m3-tab-act').innerText = b.m3.active_pct + '%';
      }
    }

    function renderActiveTabPlots() {
      if (!datasetData) return;
      if (activeTabId === 'tab-overview') {
        renderOverviewPlots();
      } else if (activeTabId === 'tab-m1') {
        renderM1Plots();
      } else if (activeTabId === 'tab-m2') {
        renderM2Plots();
      } else if (activeTabId === 'tab-m3') {
        renderM3Plots();
      }
      ensureNeedles();
      updateReplayDisplay(replayer.currentTime);
    }

    // =========================================================================
    // TAB 1 PLOTS (OVERVIEW)
    // =========================================================================
    function renderOverviewPlots() {
      if (!datasetData) return;
      const theme = getPlotlyTheme();
      const f = datasetData.fitted;
      const hist = datasetData.histogram;

      // 1. Ratio Histogram & Fitted Gaussians
      const gearColors = ['#94a3b8', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
      const histTraces = [
        {
          x: hist.bins,
          y: hist.counts,
          type: 'bar',
          name: 'Multi-Log Samples',
          marker: { color: 'rgba(56, 189, 248, 0.4)', line: { color: '#38bdf8', width: 1 } }
        }
      ];

      const xDense = [];
      for (let v = 0.0; v <= 6.5; v += 0.02) xDense.push(v);
      const maxCount = Math.max(...hist.counts);
      for (let gi = 0; gi < 5; gi++) {
        const m = f.means[gi];
        const s = f.stds[gi];
        const yCurve = xDense.map(x => {
          const diff = x - m;
          const g = Math.exp(-0.5 * (diff * diff) / (s * s));
          return g * (maxCount * 0.75);
        });
        histTraces.push({
          x: xDense,
          y: yCurve,
          mode: 'lines',
          name: `${gi + 1}st Gear (&mu;=${m.toFixed(2)})`,
          line: { color: gearColors[gi + 1], width: 2 }
        });
      }

      Plotly.react('plot-ratio-hist', histTraces, {
        ...theme,
        margin: { t: 25, b: 30, l: 45, r: 25 },
        title: { text: 'Global Ratio Histogram & Fitted Gaussian Distributions (All Logs Combined)', font: { size: 11 } },
        xaxis: { title: 'Speed / RPM Frequency Ratio', gridcolor: theme.gridcolor, range: [0.0, 6.5] },
        yaxis: { title: 'Sample Count', gridcolor: theme.gridcolor },
        legend: { orientation: 'h', y: 1.15, x: 0 },
        showlegend: true
      }, { responsive: true });

      // Session boundary shapes
      const sessionShapes = [];
      const sessionAnnotations = [];
      if (datasetData.session_boundaries && datasetData.session_boundaries.length > 1 && currentLog === 'all') {
        datasetData.session_boundaries.forEach((b, idx) => {
          if (idx > 0) {
            sessionShapes.push({
              type: 'line',
              xref: 'x',
              yref: 'paper',
              x0: b.start_time,
              x1: b.start_time,
              y0: 0,
              y1: 1,
              line: { color: '#64748b', width: 1.5, dash: 'dash' }
            });
            sessionAnnotations.push({
              xref: 'x',
              yref: 'paper',
              x: b.start_time + 1.0,
              y: 0.98,
              text: b.name.replace('.bin', ''),
              showarrow: false,
              font: { size: 9, color: '#94a3b8' },
              xanchor: 'left'
            });
          }
        });
      }

      // 2. Synchronized Vehicle Dynamics
      const ts = datasetData.timeseries;
      const dynTraces = [
        {
          x: ts.times,
          y: ts.speed_kph,
          mode: 'lines',
          name: 'Speed (km/h)',
          line: { color: '#38bdf8', width: 1.8 },
          yaxis: 'y'
        },
        {
          x: ts.times,
          y: ts.rpm,
          mode: 'lines',
          name: 'RPM',
          line: { color: '#f59e0b', width: 1.5 },
          yaxis: 'y2'
        }
      ];

      Plotly.react('plot-dynamics', dynTraces, {
        ...theme,
        margin: { t: 25, b: 25, l: 50, r: 45 },
        title: { text: `Synchronized Driving Dynamics (${currentLog === 'all' ? 'All Logs Concatenated' : currentLog})`, font: { size: 11 } },
        xaxis: { title: '', gridcolor: theme.gridcolor },
        yaxis: { title: 'km/h', titlefont: { color: '#38bdf8' }, tickfont: { color: '#38bdf8' }, gridcolor: theme.gridcolor },
        yaxis2: { title: 'RPM', titlefont: { color: '#f59e0b' }, tickfont: { color: '#f59e0b' }, overlaying: 'y', side: 'right', gridcolor: 'transparent' },
        shapes: sessionShapes,
        annotations: sessionAnnotations,
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      // 3. Side-by-Side Model Comparison (Shared vs. Stacked)
      const showM1 = document.getElementById('chk-show-m1') ? document.getElementById('chk-show-m1').checked : true;
      const showM2 = document.getElementById('chk-show-m2') ? document.getElementById('chk-show-m2').checked : true;
      const showM3 = document.getElementById('chk-show-m3') ? document.getElementById('chk-show-m3').checked : true;
      const showGT = document.getElementById('chk-show-gt') ? document.getElementById('chk-show-gt').checked : false;

      const b = datasetData.benchmarks || {};
      const compareTraces = [];

      function addGlitchTraces(modelKey, targetYaxis, modelName) {
        const events = (b[modelKey] && b[modelKey].events) ? b[modelKey].events : [];
        if (!events || events.length === 0) return;

        const drops = events.filter(e => e.type === 'dropout');
        const chats = events.filter(e => e.type === 'chatter');
        const phans = events.filter(e => e.type === 'phantom');

        if (drops.length > 0) {
          compareTraces.push({
            x: drops.map(e => e.time),
            y: drops.map(e => e.gear === 14 ? 6 : e.gear),
            mode: 'markers',
            name: `${modelName} Dropout (${drops.length})`,
            text: drops.map(e => e.desc),
            hoverinfo: 'text+x',
            marker: { symbol: 'circle', size: 9, color: '#ef4444', line: { color: '#ffffff', width: 1.2 } },
            yaxis: targetYaxis
          });
        }
        if (chats.length > 0) {
          compareTraces.push({
            x: chats.map(e => e.time),
            y: chats.map(e => e.gear === 14 ? 6 : e.gear),
            mode: 'markers',
            name: `${modelName} Chatter (${chats.length})`,
            text: chats.map(e => e.desc),
            hoverinfo: 'text+x',
            marker: { symbol: 'diamond', size: 9, color: '#f97316', line: { color: '#ffffff', width: 1.2 } },
            yaxis: targetYaxis
          });
        }
        if (phans.length > 0) {
          compareTraces.push({
            x: phans.map(e => e.time),
            y: phans.map(e => e.gear === 14 ? 6 : e.gear),
            mode: 'markers',
            name: `${modelName} Phantom (${phans.length})`,
            text: phans.map(e => e.desc),
            hoverinfo: 'text+x',
            marker: { symbol: 'triangle-up', size: 11, color: '#a855f7', line: { color: '#ffffff', width: 1.2 } },
            yaxis: targetYaxis
          });
        }
      }

      // Map gear 14 to level 6 for clean plotting without gap
      const mapGear = g => (g === 14 ? 6 : g);
      const gearText = g => (g === 14 ? 'Gear: Uncertain (14)' : (g === 0 ? 'Gear: Neutral (0)' : `Gear: ${g}`));

      if (timelineViewMode === 'shared') {
        if (showM1) {
          compareTraces.push({
            x: ts.times,
            y: ts.m1_gears.map(mapGear),
            text: ts.m1_gears.map(gearText),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'M1: Gated Heuristic',
            line: { color: '#3b82f6', width: 1.8, shape: 'hv' },
            yaxis: 'y'
          });
          addGlitchTraces('m1', 'y', 'M1');
        }
        if (showM2) {
          compareTraces.push({
            x: ts.times,
            y: ts.m2_gears.map(mapGear),
            text: ts.m2_gears.map(gearText),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'M2: Recursive Bayes',
            line: { color: '#f59e0b', width: 1.8, shape: 'hv' },
            yaxis: 'y'
          });
          addGlitchTraces('m2', 'y', 'M2');
        }
        if (showM3) {
          compareTraces.push({
            x: ts.times,
            y: ts.m3_gears.map(mapGear),
            text: ts.m3_gears.map(gearText),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'M3: HMM State-Space',
            line: { color: '#10b981', width: 2.2, shape: 'hv' },
            yaxis: 'y'
          });
          addGlitchTraces('m3', 'y', 'M3');
        }
        if (showGT && ts.ground_truth) {
          compareTraces.push({
            x: ts.times,
            y: ts.ground_truth.map(mapGear),
            text: ts.ground_truth.map(g => (g === 14 ? 'GT: Uncertain (14)' : (g === 0 ? 'GT: Neutral (0)' : `GT: ${g}`))),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'ITF_gear_position_ST',
            line: { color: '#94a3b8', width: 1.5, dash: 'dot', shape: 'hv' },
            yaxis: 'y'
          });
        }

        Plotly.react('plot-models-compare', compareTraces, {
          ...theme,
          margin: { t: 30, b: 35, l: 50, r: 45 },
          title: { text: `Shared Model Predictions & Glitch Callouts (${currentLog === 'all' ? 'All Logs' : currentLog})`, font: { size: 11 } },
          xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor },
          yaxis: {
            title: 'Gear',
            gridcolor: theme.gridcolor,
            tickvals: [0, 1, 2, 3, 4, 5, 6],
            ticktext: ['N', '1st', '2nd', '3rd', '4th', '5th', '? (Uncert)'],
            range: [-0.4, 6.6]
          },
          shapes: sessionShapes,
          annotations: sessionAnnotations,
          legend: { orientation: 'h', y: 1.15, x: 0 }
        }, { responsive: true });

      } else {
        // Stacked Subplots Mode
        if (showM1) {
          compareTraces.push({
            x: ts.times,
            y: ts.m1_gears.map(mapGear),
            text: ts.m1_gears.map(gearText),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'M1: Heuristic',
            line: { color: '#3b82f6', width: 1.8, shape: 'hv' },
            yaxis: 'y'
          });
          addGlitchTraces('m1', 'y', 'M1');
        }
        if (showM2) {
          compareTraces.push({
            x: ts.times,
            y: ts.m2_gears.map(mapGear),
            text: ts.m2_gears.map(gearText),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'M2: Bayes',
            line: { color: '#f59e0b', width: 1.8, shape: 'hv' },
            yaxis: 'y2'
          });
          addGlitchTraces('m2', 'y2', 'M2');
        }
        if (showM3) {
          compareTraces.push({
            x: ts.times,
            y: ts.m3_gears.map(mapGear),
            text: ts.m3_gears.map(gearText),
            hoverinfo: 'text+x',
            mode: 'lines',
            name: 'M3: HMM',
            line: { color: '#10b981', width: 2.0, shape: 'hv' },
            yaxis: 'y3'
          });
          addGlitchTraces('m3', 'y3', 'M3');
        }

        const stackedShapes = [];
        if (datasetData.session_boundaries && datasetData.session_boundaries.length > 1 && currentLog === 'all') {
          datasetData.session_boundaries.forEach((sb, idx) => {
            if (idx > 0) {
              ['y', 'y2', 'y3'].forEach(yAxisRef => {
                stackedShapes.push({
                  type: 'line',
                  xref: 'x',
                  yref: yAxisRef,
                  x0: sb.start_time,
                  x1: sb.start_time,
                  y0: 0,
                  y1: 6,
                  line: { color: '#64748b', width: 1.5, dash: 'dash' }
                });
              });
            }
          });
        }

        Plotly.react('plot-models-compare', compareTraces, {
          ...theme,
          margin: { t: 30, b: 35, l: 50, r: 45 },
          title: { text: `Stacked Subplots: M1 (Top), M2 (Mid), M3 (Bottom) (${currentLog === 'all' ? 'All Logs' : currentLog})`, font: { size: 11 } },
          xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor },
          yaxis: {
            domain: [0.69, 1.0],
            title: 'M1',
            gridcolor: theme.gridcolor,
            tickvals: [0, 1, 2, 3, 4, 5, 6],
            ticktext: ['N', '1', '2', '3', '4', '5', '?'],
            range: [-0.4, 6.6]
          },
          yaxis2: {
            domain: [0.35, 0.66],
            title: 'M2',
            gridcolor: theme.gridcolor,
            tickvals: [0, 1, 2, 3, 4, 5, 6],
            ticktext: ['N', '1', '2', '3', '4', '5', '?'],
            range: [-0.4, 6.6]
          },
          yaxis3: {
            domain: [0.0, 0.31],
            title: 'M3',
            gridcolor: theme.gridcolor,
            tickvals: [0, 1, 2, 3, 4, 5, 6],
            ticktext: ['N', '1', '2', '3', '4', '5', '?'],
            range: [-0.4, 6.6]
          },
          shapes: stackedShapes,
          legend: { orientation: 'h', y: 1.15, x: 0 }
        }, { responsive: true });
      }

      syncZooming('plot-dynamics', 'plot-models-compare');
      attachReplayerClickListeners(['plot-dynamics', 'plot-models-compare']);
    }

    // =========================================================================
    // TAB 2 PLOTS (MODEL 1: HEURISTIC)
    // =========================================================================
    function renderM1Plots() {
      if (!datasetData) return;
      const theme = getPlotlyTheme();
      const f = datasetData.fitted;
      const hist = datasetData.histogram;
      const ts = datasetData.timeseries;
      const tol = parseFloat(document.getElementById('slider-m1-tol').value) || 0.25;

      // 1. M1 Tolerance Band Histogram
      const gearColors = ['#94a3b8', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
      const histTraces = [{
        x: hist.bins,
        y: hist.counts,
        type: 'bar',
        name: 'Ratio Samples',
        marker: { color: 'rgba(59, 130, 246, 0.35)', line: { color: '#3b82f6', width: 1 } }
      }];

      const tolShapes = [];
      for (let gi = 0; gi < 5; gi++) {
        const m = f.means[gi];
        let maxTol = tol;
        if (gi > 0) maxTol = Math.min(maxTol, (m - f.means[gi - 1]) * 0.48);
        if (gi < 4) maxTol = Math.min(maxTol, (f.means[gi + 1] - m) * 0.48);

        tolShapes.push({
          type: 'rect',
          xref: 'x',
          yref: 'paper',
          x0: m - maxTol,
          x1: m + maxTol,
          y0: 0,
          y1: 1,
          fillcolor: gearColors[gi + 1],
          opacity: 0.18,
          line: { width: 1, color: gearColors[gi + 1] }
        });
      }

      Plotly.react('plot-m1-hist', histTraces, {
        ...theme,
        margin: { t: 25, b: 30, l: 45, r: 25 },
        title: { text: `Model 1 Calibrated Ratio Corridors (Tolerance ±${tol.toFixed(2)} with Voronoi Midpoint Protection)`, font: { size: 11 } },
        xaxis: { title: 'Speed / RPM Frequency Ratio', gridcolor: theme.gridcolor, range: [0.0, 6.5] },
        yaxis: { title: 'Samples', gridcolor: theme.gridcolor },
        shapes: tolShapes,
        showlegend: false
      }, { responsive: true });

      // 2. Dynamics
      renderSubDynPlot('plot-m1-dyn');

      // 3. M1 Smoothed Ratio vs Classified Gear Trace
      const mapGear = g => (g === 14 ? 6 : g);
      const trace = [
        {
          x: ts.times,
          y: ts.ratios,
          mode: 'markers',
          name: 'Raw Ratio',
          marker: { color: 'rgba(148, 163, 184, 0.4)', size: 3 },
          yaxis: 'y'
        },
        {
          x: ts.times,
          y: ts.m1_smoothed_ratios || ts.ratios,
          mode: 'lines',
          name: 'Ratio EMA',
          line: { color: '#38bdf8', width: 1.8 },
          yaxis: 'y'
        },
        {
          x: ts.times,
          y: ts.m1_gears.map(mapGear),
          mode: 'lines',
          name: 'M1 Classified Gear',
          line: { color: '#3b82f6', width: 2, shape: 'hv' },
          text: ts.m1_gears.map(g => (g === 14 ? 'Gear: Uncertain (14)' : (g === 0 ? 'Gear: Neutral (0)' : `Gear: ${g}`))),
          hoverinfo: 'text+x',
          yaxis: 'y2'
        }
      ];

      addGlitchMarkersToTrace(trace, 'm1', 'y2');

      Plotly.react('plot-m1-trace', trace, {
        ...theme,
        margin: { t: 30, b: 35, l: 50, r: 45 },
        title: { text: 'M1 Ratio Smoothing & Classified Gear Trace (with Dropout/Chatter/Phantom Callouts)', font: { size: 11 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor },
        yaxis: { domain: [0.38, 1.0], title: 'Ratio', gridcolor: theme.gridcolor },
        yaxis2: {
          domain: [0.0, 0.30],
          title: 'Gear',
          gridcolor: theme.gridcolor,
          tickvals: [0, 1, 2, 3, 4, 5, 6],
          ticktext: ['N', '1st', '2nd', '3rd', '4th', '5th', '? (Uncert)'],
          range: [-0.4, 6.6]
        },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      syncZooming('plot-m1-dyn', 'plot-m1-trace');
      attachReplayerClickListeners(['plot-m1-dyn', 'plot-m1-trace']);
    }

    // =========================================================================
    // TAB 3 PLOTS (MODEL 2: KINEMATIC BAYES)
    // =========================================================================
    function renderM2Plots() {
      if (!datasetData) return;
      const theme = getPlotlyTheme();
      const f = datasetData.fitted;
      const ts = datasetData.timeseries;

      // 1. Likelihood Corridors
      const gearColors = ['#94a3b8', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
      const xDense = [];
      for (let v = 0.0; v <= 6.5; v += 0.02) xDense.push(v);
      const corridorTraces = [];

      for (let gi = 0; gi < 5; gi++) {
        const m = f.means[gi];
        const v = f.vars[gi];
        const s = Math.sqrt(v);
        const yCurve = xDense.map(x => {
          const diff = x - m;
          return Math.exp(-0.5 * (diff * diff) / v) / (Math.sqrt(2 * Math.PI * v));
        });
        corridorTraces.push({
          x: xDense,
          y: yCurve,
          mode: 'lines',
          name: `${gi + 1}st Gear Density`,
          line: { color: gearColors[gi + 1], width: 2 }
        });
      }

      Plotly.react('plot-m2-corridors', corridorTraces, {
        ...theme,
        margin: { t: 25, b: 30, l: 45, r: 25 },
        title: { text: 'Model 2 Gaussian Likelihood Distributions p(r | Gear = k)', font: { size: 11 } },
        xaxis: { title: 'Speed / RPM Frequency Ratio', gridcolor: theme.gridcolor, range: [0.0, 6.5] },
        yaxis: { title: 'Probability Density', gridcolor: theme.gridcolor },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      // 2. Dynamics
      renderSubDynPlot('plot-m2-dyn');

      // 3. Posterior Probability Traces & Classified Gear
      const mapGear = g => (g === 14 ? 6 : g);
      const postTraces = [];

      if (ts.m2_probs && ts.m2_probs.length > 0) {
        for (let k = 1; k <= 5; k++) {
          postTraces.push({
            x: ts.times,
            y: ts.m2_probs.map(p => p[k]),
            mode: 'lines',
            name: `P(${k}G)`,
            line: { color: gearColors[k], width: 1.2 },
            yaxis: 'y'
          });
        }
      }

      postTraces.push({
        x: ts.times,
        y: ts.m2_gears.map(mapGear),
        mode: 'lines',
        name: 'M2 Classified Gear',
        line: { color: '#f59e0b', width: 2, shape: 'hv' },
        text: ts.m2_gears.map(g => (g === 14 ? 'Gear: Uncertain (14)' : (g === 0 ? 'Gear: Neutral (0)' : `Gear: ${g}`))),
        hoverinfo: 'text+x',
        yaxis: 'y2'
      });

      addGlitchMarkersToTrace(postTraces, 'm2', 'y2');

      Plotly.react('plot-m2-trace', postTraces, {
        ...theme,
        margin: { t: 30, b: 35, l: 50, r: 45 },
        title: { text: 'M2 Posterior Belief & Classified Gear Trace (with Loss-of-Fix & Coast Guards)', font: { size: 11 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor },
        yaxis: { domain: [0.38, 1.0], title: 'Posterior P(k)', gridcolor: theme.gridcolor, range: [-0.05, 1.05] },
        yaxis2: {
          domain: [0.0, 0.30],
          title: 'Gear',
          gridcolor: theme.gridcolor,
          tickvals: [0, 1, 2, 3, 4, 5, 6],
          ticktext: ['N', '1st', '2nd', '3rd', '4th', '5th', '? (Uncert)'],
          range: [-0.4, 6.6]
        },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      syncZooming('plot-m2-dyn', 'plot-m2-trace');
      attachReplayerClickListeners(['plot-m2-dyn', 'plot-m2-trace']);
    }

    // =========================================================================
    // TAB 4 PLOTS (MODEL 3: HMM STATE-SPACE)
    // =========================================================================
    function renderM3Plots() {
      if (!datasetData) return;
      const theme = getPlotlyTheme();
      const ts = datasetData.timeseries;
      const A = datasetData.transition_matrix;

      // 1. Empirical Transition Matrix Heatmap
      const labels = ['N', '1st', '2nd', '3rd', '4th', '5th'];
      const heatmapTrace = [{
        z: A,
        x: labels,
        y: labels,
        type: 'heatmap',
        colorscale: 'Viridis',
        reversescale: true,
        hoverongaps: false
      }];

      Plotly.react('plot-m3-matrix', heatmapTrace, {
        ...theme,
        margin: { t: 25, b: 35, l: 45, r: 25 },
        title: { text: 'Model 3 Empirical Transition Probability Matrix A[i, j]', font: { size: 11 } },
        xaxis: { title: 'To State (j)', gridcolor: theme.gridcolor },
        yaxis: { title: 'From State (i)', gridcolor: theme.gridcolor, autorange: 'reversed' }
      }, { responsive: true });

      // 2. Dynamics
      renderSubDynPlot('plot-m3-dyn');

      // 3. Forward Alpha Probabilities & Classified Gear
      const mapGear = g => (g === 14 ? 6 : g);
      const gearColors = ['#94a3b8', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
      const hmmTraces = [];

      if (ts.m3_alphas && ts.m3_alphas.length > 0) {
        for (let k = 1; k <= 5; k++) {
          hmmTraces.push({
            x: ts.times,
            y: ts.m3_alphas.map(a => a[k]),
            mode: 'lines',
            name: `Forward &alpha;(${k}G)`,
            line: { color: gearColors[k], width: 1.2 },
            yaxis: 'y'
          });
        }
      }

      hmmTraces.push({
        x: ts.times,
        y: ts.m3_gears.map(mapGear),
        mode: 'lines',
        name: 'M3 Classified Gear',
        line: { color: '#10b981', width: 2, shape: 'hv' },
        text: ts.m3_gears.map(g => (g === 14 ? 'Gear: Uncertain (14)' : (g === 0 ? 'Gear: Neutral (0)' : `Gear: ${g}`))),
        hoverinfo: 'text+x',
        yaxis: 'y2'
      });

      addGlitchMarkersToTrace(hmmTraces, 'm3', 'y2');

      Plotly.react('plot-m3-trace', hmmTraces, {
        ...theme,
        margin: { t: 30, b: 35, l: 50, r: 45 },
        title: { text: 'M3 Forward Belief & Classified Gear Trace (Clutch-Drop Suppression Active)', font: { size: 11 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor },
        yaxis: { domain: [0.38, 1.0], title: 'Belief &alpha;', gridcolor: theme.gridcolor, range: [-0.05, 1.05] },
        yaxis2: {
          domain: [0.0, 0.30],
          title: 'Gear',
          gridcolor: theme.gridcolor,
          tickvals: [0, 1, 2, 3, 4, 5, 6],
          ticktext: ['N', '1st', '2nd', '3rd', '4th', '5th', '? (Uncert)'],
          range: [-0.4, 6.6]
        },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      syncZooming('plot-m3-dyn', 'plot-m3-trace');
      attachReplayerClickListeners(['plot-m3-dyn', 'plot-m3-trace']);
    }

    function renderSubDynPlot(elementId) {
      const theme = getPlotlyTheme();
      const ts = datasetData.timeseries;
      Plotly.react(elementId, [
        { x: ts.times, y: ts.speed_kph, mode: 'lines', name: 'Speed (km/h)', line: { color: '#38bdf8', width: 1.6 }, yaxis: 'y' },
        { x: ts.times, y: ts.rpm, mode: 'lines', name: 'RPM', line: { color: '#f59e0b', width: 1.4 }, yaxis: 'y2' }
      ], {
        ...theme,
        margin: { t: 20, b: 20, l: 50, r: 45 },
        xaxis: { title: '', gridcolor: theme.gridcolor },
        yaxis: { title: 'km/h', titlefont: { color: '#38bdf8' }, tickfont: { color: '#38bdf8' }, gridcolor: theme.gridcolor },
        yaxis2: { title: 'RPM', titlefont: { color: '#f59e0b' }, tickfont: { color: '#f59e0b' }, overlaying: 'y', side: 'right', gridcolor: 'transparent' },
        legend: { orientation: 'h', y: 1.15, x: 0 },
        showlegend: false
      }, { responsive: true });
    }

    function addGlitchMarkersToTrace(targetTraces, modelKey, targetYaxis) {
      const b = datasetData.benchmarks || {};
      const events = (b[modelKey] && b[modelKey].events) ? b[modelKey].events : [];
      if (!events || events.length === 0) return;

      const drops = events.filter(e => e.type === 'dropout');
      const chats = events.filter(e => e.type === 'chatter');
      const phans = events.filter(e => e.type === 'phantom');

      if (drops.length > 0) {
        targetTraces.push({
          x: drops.map(e => e.time),
          y: drops.map(e => e.gear === 14 ? 6 : e.gear),
          mode: 'markers',
          name: `Dropout (${drops.length})`,
          text: drops.map(e => e.desc),
          hoverinfo: 'text+x',
          marker: { symbol: 'circle', size: 9, color: '#ef4444', line: { color: '#ffffff', width: 1.2 } },
          yaxis: targetYaxis
        });
      }
      if (chats.length > 0) {
        targetTraces.push({
          x: chats.map(e => e.time),
          y: chats.map(e => e.gear === 14 ? 6 : e.gear),
          mode: 'markers',
          name: `Chatter (${chats.length})`,
          text: chats.map(e => e.desc),
          hoverinfo: 'text+x',
          marker: { symbol: 'diamond', size: 9, color: '#f97316', line: { color: '#ffffff', width: 1.2 } },
          yaxis: targetYaxis
        });
      }
      if (phans.length > 0) {
        targetTraces.push({
          x: phans.map(e => e.time),
          y: phans.map(e => e.gear === 14 ? 6 : e.gear),
          mode: 'markers',
          name: `Phantom (${phans.length})`,
          text: phans.map(e => e.desc),
          hoverinfo: 'text+x',
          marker: { symbol: 'triangle-up', size: 11, color: '#a855f7', line: { color: '#ffffff', width: 1.2 } },
          yaxis: targetYaxis
        });
      }
    }

    function syncZooming(id1, id2) {
      const el1 = document.getElementById(id1);
      const el2 = document.getElementById(id2);
      if (el1 && typeof el1.on === 'function' && !el1._syncAttached) {
        el1._syncAttached = true;
        el1.on('plotly_relayout', (ed) => {
          if (ed['xaxis.range[0]'] !== undefined) {
            Plotly.relayout(id2, {
              'xaxis.range[0]': ed['xaxis.range[0]'],
              'xaxis.range[1]': ed['xaxis.range[1]']
            });
          } else if (ed['xaxis.autorange'] !== undefined) {
            Plotly.relayout(id2, { 'xaxis.autorange': true });
          }
          updateReplayDisplay(replayer.currentTime);
        });
      }
      if (el2 && typeof el2.on === 'function' && !el2._syncAttached) {
        el2._syncAttached = true;
        el2.on('plotly_relayout', (ed) => {
          if (ed['xaxis.range[0]'] !== undefined) {
            Plotly.relayout(id1, {
              'xaxis.range[0]': ed['xaxis.range[0]'],
              'xaxis.range[1]': ed['xaxis.range[1]']
            });
          } else if (ed['xaxis.autorange'] !== undefined) {
            Plotly.relayout(id1, { 'xaxis.autorange': true });
          }
          updateReplayDisplay(replayer.currentTime);
        });
      }
    }

    // =========================================================================
    // REPLAYER & ALL GAUGE PODS ENGINE
    // =========================================================================
    const allTimelinePlotIds = [
      'plot-dynamics', 'plot-models-compare',
      'plot-m1-dyn', 'plot-m1-trace',
      'plot-m2-dyn', 'plot-m2-trace',
      'plot-m3-dyn', 'plot-m3-trace'
    ];

    const replayer = {
      playing: false,
      timer: null,
      lastTimestamp: 0,
      currentTime: 0,
      minTime: 0,
      maxTime: 0,
      speed: 1.0,
      times: [],
      data: null
    };

    function ensureNeedles() {
      allTimelinePlotIds.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (!el.querySelector(`.timeline-needle-${id}`)) {
          const needle = document.createElement('div');
          needle.className = `timeline-needle timeline-needle-${id}`;
          needle.style.display = 'none';
          el.appendChild(needle);
        }
      });
    }

    function initReplayer(datasetData) {
      ensureNeedles();
      replayer.data = datasetData.timeseries;
      replayer.times = datasetData.timeseries.times;
      replayer.minTime = replayer.times[0] || 0.0;
      replayer.maxTime = replayer.times[replayer.times.length - 1] || 0.0;

      const scrub = document.getElementById('slider-replay-scrub');
      if (scrub) {
        scrub.min = replayer.minTime;
        scrub.max = replayer.maxTime;
        scrub.step = Math.max(0.01, (replayer.maxTime - replayer.minTime) / 3500);
        if (replayer.currentTime < replayer.minTime || replayer.currentTime > replayer.maxTime) {
          replayer.currentTime = replayer.minTime;
        }
        scrub.value = replayer.currentTime;
      }

      updateReplayDisplay(replayer.currentTime);
    }

    function findClosestIndex(times, t) {
      if (!times || times.length === 0) return 0;
      let low = 0, high = times.length - 1;
      while (low <= high) {
        const mid = (low + high) >> 1;
        if (times[mid] === t) return mid;
        else if (times[mid] < t) low = mid + 1;
        else high = mid - 1;
      }
      if (low >= times.length) return times.length - 1;
      if (low === 0) return 0;
      return (Math.abs(times[low] - t) < Math.abs(times[low - 1] - t)) ? low : low - 1;
    }

    function updateReplayDisplay(t) {
      replayer.currentTime = t;
      const scrub = document.getElementById('slider-replay-scrub');
      if (scrub && Math.abs(parseFloat(scrub.value) - t) > 0.05) {
        scrub.value = t;
      }
      const lbl = document.getElementById('lbl-replay-time');
      if (lbl) {
        lbl.textContent = `${t.toFixed(2)}s / ${replayer.maxTime.toFixed(2)}s`;
      }

      // Update needles on all plots in active tab
      const visiblePlotIds = (activeTabId === 'tab-overview')
        ? ['plot-dynamics', 'plot-models-compare']
        : (activeTabId === 'tab-m1' ? ['plot-m1-dyn', 'plot-m1-trace']
        : (activeTabId === 'tab-m2' ? ['plot-m2-dyn', 'plot-m2-trace'] : ['plot-m3-dyn', 'plot-m3-trace']));

      allTimelinePlotIds.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const needle = el.querySelector(`.timeline-needle-${id}`);
        if (!visiblePlotIds.includes(id)) {
          if (needle) needle.style.display = 'none';
          return;
        }
        if (!el._fullLayout || !el._fullLayout.xaxis) return;
        let n = needle;
        if (!n) {
          ensureNeedles();
          n = el.querySelector(`.timeline-needle-${id}`);
        }
        if (!n) return;

        const xaxis = el._fullLayout.xaxis;
        if (t < xaxis.range[0] || t > xaxis.range[1]) {
          n.style.display = 'none';
          return;
        }
        const leftPx = xaxis._offset + xaxis.d2p(t);
        n.style.left = `${leftPx}px`;
        n.style.top = `${el._fullLayout.margin.t}px`;
        n.style.height = `${el._fullLayout._size.h}px`;
        n.style.display = 'block';
      });

      // Update All Simulated Gauge Pods
      if (!replayer.data || !replayer.times || replayer.times.length === 0) return;
      const ts = replayer.data;
      const idx = findClosestIndex(replayer.times, t);

      const spd = (ts.speed_kph && ts.speed_kph[idx] !== undefined) ? ts.speed_kph[idx] : 0;
      const rpm = (ts.rpm && ts.rpm[idx] !== undefined) ? ts.rpm[idx] : 0;
      const ratio = (ts.ratios && ts.ratios[idx] !== undefined) ? ts.ratios[idx] : 0;
      const m1Gear = (ts.m1_gears && ts.m1_gears[idx] !== undefined) ? ts.m1_gears[idx] : 0;
      const m2Gear = (ts.m2_gears && ts.m2_gears[idx] !== undefined) ? ts.m2_gears[idx] : 0;
      const m3Gear = (ts.m3_gears && ts.m3_gears[idx] !== undefined) ? ts.m3_gears[idx] : 0;

      const fmtGear = (g) => g === 0 ? 'N' : (g === 14 ? '?' : String(g));
      const gearColor = (g, defaultCol) => g === 0 ? 'var(--text-muted)' : (g === 14 ? '#f59e0b' : defaultCol);

      // --- M1 (Heuristic Pods) ---
      const m1Color = gearColor(m1Gear, '#3b82f6');
      ['m1-pod-gear', 'm1-single-gear'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = fmtGear(m1Gear); el.style.color = m1Color; }
      });
      ['m1-pod-speed', 'm1-single-speed'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${spd.toFixed(1)} km/h`;
      });
      ['m1-pod-rpm', 'm1-single-rpm'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${Math.round(rpm)} RPM`;
      });
      ['m1-pod-ratio', 'm1-single-ratio'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = ratio > 0.1 ? ratio.toFixed(2) : '--';
      });
      ['m1-pod-status', 'm1-single-status'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.textContent = m1Gear === 0 ? 'NEUTRAL/COAST' : (m1Gear === 14 ? 'UNCERTAIN (14)' : 'LATCHED');
          el.className = `model-badge ${m1Gear === 0 ? 'badge-neutral' : (m1Gear === 14 ? 'badge-uncertain' : 'badge-m1')}`;
        }
      });

      // --- M2 (Kinematic Bayes Pods) ---
      const m2Color = gearColor(m2Gear, '#f59e0b');
      let m2ProbStr = '--%';
      if (ts.m2_probs && ts.m2_probs[idx]) {
        const p = ts.m2_probs[idx];
        const maxP = Math.max(...p);
        m2ProbStr = (maxP * 100).toFixed(0) + '%';
      }
      let m2ContextStr = 'Steady Cruise';
      if (spd < 3.0) m2ContextStr = 'Standstill';
      else if (rpm < 1000.0) m2ContextStr = 'Engine Idle';
      else if (m2Gear === 14) m2ContextStr = 'Loss-of-Fix Shift';

      ['m2-pod-gear', 'm2-single-gear'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = fmtGear(m2Gear); el.style.color = m2Color; }
      });
      ['m2-single-speed'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${spd.toFixed(1)} km/h`;
      });
      ['m2-single-rpm'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${Math.round(rpm)} RPM`;
      });
      ['m2-pod-prob', 'm2-single-prob'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = m2Gear === 0 ? '--' : m2ProbStr;
      });
      ['m2-pod-context', 'm2-single-context'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = m2ContextStr;
      });
      ['m2-pod-regime'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.textContent = m2Gear === 0 ? 'NEUTRAL' : (m2Gear === 14 ? 'UNCERTAIN (14)' : 'CORRIDOR LOCK');
          el.className = `model-badge ${m2Gear === 0 ? 'badge-neutral' : (m2Gear === 14 ? 'badge-uncertain' : 'badge-m2')}`;
        }
      });

      // --- M3 (HMM State-Space Pods) ---
      const m3Color = gearColor(m3Gear, '#10b981');
      let m3AlphaStr = '--%';
      if (ts.m3_alphas && ts.m3_alphas[idx]) {
        const a = ts.m3_alphas[idx];
        const maxA = Math.max(...a);
        m3AlphaStr = (maxA * 100).toFixed(0) + '%';
      }
      let m3EmissStr = 'Inertial Forward';
      if (m3Gear === 0) m3EmissStr = 'Neutral Idle';
      else if (m3Gear === 14) m3EmissStr = 'Transition / Uncertain';

      ['m3-pod-gear', 'm3-single-gear'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = fmtGear(m3Gear); el.style.color = m3Color; }
      });
      ['m3-single-speed'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${spd.toFixed(1)} km/h`;
      });
      ['m3-single-rpm'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${Math.round(rpm)} RPM`;
      });
      ['m3-pod-alpha', 'm3-single-alpha'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = m3Gear === 0 ? '--' : m3AlphaStr;
      });
      ['m3-pod-emission', 'm3-single-emission'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = m3EmissStr;
      });
      ['m3-pod-state'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.textContent = m3Gear === 0 ? 'NEUTRAL' : (m3Gear === 14 ? 'UNCERTAIN (14)' : 'VITERBI BEST');
          el.className = `model-badge ${m3Gear === 0 ? 'badge-neutral' : (m3Gear === 14 ? 'badge-uncertain' : 'badge-m3')}`;
        }
      });
    }

    function playStep(timestamp) {
      if (!replayer.playing) return;
      if (!replayer.lastTimestamp) replayer.lastTimestamp = timestamp;
      const dt = (timestamp - replayer.lastTimestamp) / 1000.0;
      replayer.lastTimestamp = timestamp;

      let nextT = replayer.currentTime + dt * replayer.speed;
      if (nextT >= replayer.maxTime) {
        nextT = replayer.maxTime;
        updateReplayDisplay(nextT);
        stopPlayback();
        return;
      }
      updateReplayDisplay(nextT);
      replayer.timer = requestAnimationFrame(playStep);
    }

    function startPlayback() {
      if (replayer.currentTime >= replayer.maxTime) {
        replayer.currentTime = replayer.minTime;
      }
      replayer.playing = true;
      replayer.lastTimestamp = 0;
      const btn = document.getElementById('btn-replay-play');
      if (btn) btn.textContent = '⏸ Pause';
      replayer.timer = requestAnimationFrame(playStep);
    }

    function stopPlayback() {
      replayer.playing = false;
      if (replayer.timer) {
        cancelAnimationFrame(replayer.timer);
        replayer.timer = null;
      }
      const btn = document.getElementById('btn-replay-play');
      if (btn) btn.textContent = '▶ Play';
    }

    // Transport controls setup
    const btnPlay = document.getElementById('btn-replay-play');
    if (btnPlay) {
      btnPlay.addEventListener('click', () => {
        if (replayer.playing) stopPlayback();
        else startPlayback();
      });
    }

    const btnReset = document.getElementById('btn-replay-reset');
    if (btnReset) {
      btnReset.addEventListener('click', () => {
        stopPlayback();
        updateReplayDisplay(replayer.minTime);
      });
    }

    const btnPrev = document.getElementById('btn-replay-prev');
    if (btnPrev) {
      btnPrev.addEventListener('click', () => {
        stopPlayback();
        updateReplayDisplay(Math.max(replayer.minTime, replayer.currentTime - 0.2));
      });
    }

    const btnNext = document.getElementById('btn-replay-next');
    if (btnNext) {
      btnNext.addEventListener('click', () => {
        stopPlayback();
        updateReplayDisplay(Math.min(replayer.maxTime, replayer.currentTime + 0.2));
      });
    }

    const selSpeed = document.getElementById('select-replay-speed');
    if (selSpeed) {
      selSpeed.addEventListener('change', (e) => {
        replayer.speed = parseFloat(e.target.value) || 1.0;
      });
    }

    const scrubSlider = document.getElementById('slider-replay-scrub');
    if (scrubSlider) {
      scrubSlider.addEventListener('input', (e) => {
        stopPlayback();
        updateReplayDisplay(parseFloat(e.target.value));
      });
    }

    function attachReplayerClickListeners(plotIds) {
      plotIds.forEach(id => {
        const el = document.getElementById(id);
        if (el && typeof el.on === 'function' && !el._replayerClickAttached) {
          el._replayerClickAttached = true;
          el.on('plotly_click', (d) => {
            if (d && d.points && d.points[0] && d.points[0].x !== undefined) {
              stopPlayback();
              updateReplayDisplay(d.points[0].x);
            }
          });
        }
      });
    }

    // =========================================================================
    // AUTO-OPTIMIZER MODAL & EXECUTION
    // =========================================================================
    const btnAutoOptimize = document.getElementById('btn-auto-optimize');
    if (btnAutoOptimize) {
      btnAutoOptimize.addEventListener('click', async () => {
        btnAutoOptimize.disabled = true;
        btnAutoOptimize.textContent = '⏳ Optimizing Grid...';
        try {
          const speedHz = document.getElementById('slider-cutoff-speed') ? document.getElementById('slider-cutoff-speed').value : 11.28;
          const rpmHz = document.getElementById('slider-cutoff-rpm') ? document.getElementById('slider-cutoff-rpm').value : 33.33;
          const url = `/api/auto_tune?log=${encodeURIComponent(currentLog)}&min_speed_hz=${speedHz}&min_rpm_hz=${rpmHz}`;

          const resp = await fetch(url, { method: 'POST' });
          const res = await resp.json();
          if (res.status === 'ok') {
            lastOptResults = res;
            document.getElementById('opt-target-log').textContent = (res.target_log === 'all') ? 'All Combined Logs' : res.target_log;
            document.getElementById('opt-before-score').textContent = res.before_score.toFixed(1) + '%';
            document.getElementById('opt-after-score').textContent = res.after_score.toFixed(1) + '%';
            const deltaEl = document.getElementById('opt-delta-badge');
            deltaEl.textContent = (res.score_delta >= 0 ? '+' : '') + res.score_delta.toFixed(1) + '%';
            deltaEl.className = `model-badge ${res.score_delta >= 0 ? 'badge-m3' : 'badge-neutral'}`;

            const tbody = document.getElementById('opt-tbody-changes');
            tbody.innerHTML = '';
            res.changes.forEach(c => {
              const tr = document.createElement('tr');
              tr.style.borderBottom = '1px solid var(--panel-border)';
              const beforeStr = typeof c.before === 'number' ? (c.unit ? `${c.before} ${c.unit}` : c.before.toString()) : c.before;
              const afterStr = typeof c.after === 'number' ? (c.unit ? `${c.after} ${c.unit}` : c.after.toString()) : c.after;
              const isChanged = (c.before !== c.after);
              tr.innerHTML = `
                <td style="padding:0.4rem 0.6rem; font-weight:600; color:var(--text);">${c.param}</td>
                <td style="padding:0.4rem 0.6rem; text-align:right; font-family:monospace; color:var(--text-muted);">${beforeStr}</td>
                <td style="padding:0.4rem 0.6rem; text-align:right; font-family:monospace; font-weight:${isChanged ? '700' : 'normal'}; color:${isChanged ? 'var(--accent)' : 'var(--text)'};">${afterStr}</td>
              `;
              tbody.appendChild(tr);
            });

            document.getElementById('optimizer-modal').style.display = 'flex';
          } else {
            alert('Auto-tune error: ' + (res.error || 'Unknown error'));
          }
        } catch (err) {
          alert('Auto-tune request failed: ' + err.message);
        } finally {
          btnAutoOptimize.disabled = false;
          btnAutoOptimize.textContent = '⚡ Auto-Optimize Parameters';
        }
      });
    }

    document.getElementById('btn-close-opt-modal').addEventListener('click', () => {
      document.getElementById('optimizer-modal').style.display = 'none';
    });
    document.getElementById('btn-opt-dismiss').addEventListener('click', () => {
      document.getElementById('optimizer-modal').style.display = 'none';
    });

    document.getElementById('btn-opt-apply').addEventListener('click', async () => {
      if (!lastOptResults) return;
      const s = lastOptResults.recommended;
      if (s.m1_alpha !== undefined && document.getElementById('slider-m1-alpha')) {
        document.getElementById('slider-m1-alpha').value = s.m1_alpha;
        document.getElementById('val-m1-alpha').textContent = s.m1_alpha;
      }
      if (s.m1_tol !== undefined && document.getElementById('slider-m1-tol')) {
        document.getElementById('slider-m1-tol').value = s.m1_tol;
        document.getElementById('val-m1-tol').textContent = '±' + s.m1_tol;
      }
      if (s.m1_latch_ms !== undefined && document.getElementById('slider-m1-latch')) {
        document.getElementById('slider-m1-latch').value = s.m1_latch_ms;
        document.getElementById('val-m1-latch').textContent = s.m1_latch_ms + ' ms';
      }
      if (s.m2_decay !== undefined && document.getElementById('slider-m2-decay')) {
        document.getElementById('slider-m2-decay').value = s.m2_decay;
        document.getElementById('val-m2-decay').textContent = s.m2_decay;
      }
      if (s.m2_inertia !== undefined && document.getElementById('slider-m2-inertia')) {
        document.getElementById('slider-m2-inertia').value = s.m2_inertia;
        document.getElementById('val-m2-inertia').textContent = s.m2_inertia.toFixed(3);
      }
      if (s.m2_latch_ms !== undefined && document.getElementById('slider-m2-latch')) {
        document.getElementById('slider-m2-latch').value = s.m2_latch_ms;
        document.getElementById('val-m2-latch').textContent = s.m2_latch_ms + ' ms';
      }
      if (s.m2_conf !== undefined && document.getElementById('slider-m2-conf')) {
        document.getElementById('slider-m2-conf').value = s.m2_conf;
        document.getElementById('val-m2-conf').textContent = s.m2_conf;
      }
      if (s.m3_inertia !== undefined && document.getElementById('slider-m3-inertia')) {
        document.getElementById('slider-m3-inertia').value = s.m3_inertia;
        document.getElementById('val-m3-inertia').textContent = s.m3_inertia.toFixed(3);
      }
      if (s.m3_clutch_decel !== undefined && document.getElementById('slider-m3-decel')) {
        document.getElementById('slider-m3-decel').value = s.m3_clutch_decel;
        document.getElementById('val-m3-decel').textContent = s.m3_clutch_decel + ' Hz/s';
      }

      document.getElementById('optimizer-modal').style.display = 'none';

      // Save to calibration file
      try {
        const payload = {
          tolerance: s.m1_tol,
          tolerance_abs: s.m1_tol,
          latch_ms: s.m1_latch_ms,
          latch_time_ms: s.m1_latch_ms,
          min_speed_hz: parseFloat(document.getElementById('slider-cutoff-speed').value) || 11.28,
          min_speed_kph: (parseFloat(document.getElementById('slider-cutoff-speed').value) || 11.28) * 2.214,
          min_rpm: (parseFloat(document.getElementById('slider-cutoff-rpm').value) || 33.33) * 30.0,
          min_rpm_hz: parseFloat(document.getElementById('slider-cutoff-rpm').value) || 33.33
        };
        await fetch('/api/calibration', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (e) {
        console.warn('Failed to auto-save calibration:', e);
      }

      await loadDataset();
    });

    // =========================================================================
    // SHARED CALIBRATION SAVE / LOAD HANDLERS
    // =========================================================================
    const btnSaveCal = document.getElementById('btn-save-shared-cal');
    if (btnSaveCal) {
      btnSaveCal.addEventListener('click', async () => {
        btnSaveCal.disabled = true;
        try {
          const tol = parseFloat(document.getElementById('slider-m1-tol').value);
          const latch = parseInt(document.getElementById('slider-m1-latch').value);
          const spdHz = parseFloat(document.getElementById('slider-cutoff-speed').value);
          const rpmHz = parseFloat(document.getElementById('slider-cutoff-rpm').value);

          const payload = {
            tolerance: tol,
            tolerance_abs: tol,
            latch_ms: latch,
            latch_time_ms: latch,
            min_speed_hz: spdHz,
            min_speed_kph: spdHz * 2.214,
            min_rpm: rpmHz * 30.0,
            min_rpm_hz: rpmHz
          };
          const resp = await fetch('/api/calibration', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const res = await resp.json();
          if (res.status === 'ok') {
            alert('Shared Calibration saved successfully to decoder/gear_calibration.json');
          } else {
            alert('Failed to save calibration: ' + (res.message || 'error'));
          }
        } catch (e) {
          alert('Save calibration error: ' + e.message);
        } finally {
          btnSaveCal.disabled = false;
        }
      });
    }

    const btnLoadCal = document.getElementById('btn-load-shared-cal');
    if (btnLoadCal) {
      btnLoadCal.addEventListener('click', async () => {
        btnLoadCal.disabled = true;
        try {
          const resp = await fetch('/api/calibration');
          const cal = await resp.json();
          if (cal.tolerance_abs !== undefined && document.getElementById('slider-m1-tol')) {
            document.getElementById('slider-m1-tol').value = cal.tolerance_abs;
            document.getElementById('val-m1-tol').textContent = '±' + cal.tolerance_abs;
          } else if (cal.tolerance !== undefined && document.getElementById('slider-m1-tol')) {
            document.getElementById('slider-m1-tol').value = cal.tolerance;
            document.getElementById('val-m1-tol').textContent = '±' + cal.tolerance;
          }
          if (cal.latch_time_ms !== undefined && document.getElementById('slider-m1-latch')) {
            document.getElementById('slider-m1-latch').value = cal.latch_time_ms;
            document.getElementById('val-m1-latch').textContent = cal.latch_time_ms + ' ms';
          } else if (cal.latch_ms !== undefined && document.getElementById('slider-m1-latch')) {
            document.getElementById('slider-m1-latch').value = cal.latch_ms;
            document.getElementById('val-m1-latch').textContent = cal.latch_ms + ' ms';
          }
          if (cal.min_speed_hz !== undefined && document.getElementById('slider-cutoff-speed')) {
            document.getElementById('slider-cutoff-speed').value = cal.min_speed_hz;
            document.getElementById('val-cutoff-speed').textContent = `${cal.min_speed_hz.toFixed(2)} Hz (${(cal.min_speed_hz * 2.214).toFixed(0)} km/h)`;
          }
          if (cal.min_rpm_hz !== undefined && document.getElementById('slider-cutoff-rpm')) {
            document.getElementById('slider-cutoff-rpm').value = cal.min_rpm_hz;
            document.getElementById('val-cutoff-rpm').textContent = `${cal.min_rpm_hz.toFixed(2)} Hz (${(cal.min_rpm_hz * 30.0).toFixed(0)} RPM)`;
          }
          alert('Shared Calibration loaded from decoder/gear_calibration.json');
          loadDataset();
        } catch (e) {
          alert('Load calibration error: ' + e.message);
        } finally {
          btnLoadCal.disabled = false;
        }
      });
    }

    // Resize synchronization
    window.addEventListener('resize', () => {
      updateReplayDisplay(replayer.currentTime);
    });

    // Startup
    loadLogsList();
    loadDataset();
  </script>
</body>
</html>
"""

# ==============================================================================
# HTTP REQUEST HANDLER
# ==============================================================================

class GearLabHandler(BaseHTTPRequestHandler):
    def send_json(self, data: Any):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            payload = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        elif path == "/api/logs":
            files = find_bin_files()
            res = [{"filename": p.name, "size": p.stat().st_size} for p in files if p.stat().st_size > 0]
            self.send_json(res)

        elif path == "/api/dataset":
            log_param = query.get("log", ["all"])[0]
            if "cached_agg" not in DATASET_CACHE:
                DATASET_CACHE["cached_agg"] = build_aggregated_dataset()
            agg = DATASET_CACHE["cached_agg"]

            means = agg["fitted"]["means"]
            vars_ = agg["fitted"]["vars"]
            A = agg["transition_matrix"]

            # Parse custom parameters & cutoffs
            min_speed_hz = float(query.get("min_speed_hz", [11.28])[0])
            min_rpm_hz = float(query.get("min_rpm_hz", [33.33])[0])

            m1_alpha = float(query.get("m1_alpha", [0.15])[0])
            m1_tol = float(query.get("m1_tol", [0.25])[0])
            m1_latch_ms = float(query.get("m1_latch_ms", [200.0])[0])

            m2_decay = float(query.get("m2_decay", [0.94])[0])
            m2_p0 = float(query.get("m2_p0", [0.08])[0])
            m2_conf = float(query.get("m2_conf", [0.38])[0])
            m2_inertia = float(query.get("m2_inertia", [0.96])[0])
            m2_latch_ms = float(query.get("m2_latch_ms", [200.0])[0])

            m3_inertia = float(query.get("m3_inertia", [0.97])[0])
            m3_clutch_decel = float(query.get("m3_clutch_decel", [-40.0])[0])

            # Select timeline dataset
            session_boundaries = []
            if log_param == "all":
                chosen_log = agg.get("concat_timeline") or agg["logs"][0]
                session_boundaries = chosen_log.get("session_boundaries", [])
            else:
                chosen_log = next((l for l in agg["logs"] if l["filename"] == log_param), None)
                if not chosen_log:
                    chosen_log = agg["logs"][0] if agg["logs"] else {"times": [], "speed_freq": [], "rpm_freq": [], "speed_kph": [], "rpm": [], "ground_truth": []}

            # Run 3 models on the chosen log with details
            m1, m1_ratios = run_model_1_heuristic(chosen_log, means, alpha=m1_alpha, tol=m1_tol, latch_ms=m1_latch_ms, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz, return_details=True)
            m2, m2_posts = run_model_2_bayesian(chosen_log, means, vars_, decay=m2_decay, p0=m2_p0, conf_thresh=m2_conf, inertia=m2_inertia, latch_ms=m2_latch_ms, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz, return_details=True)
            m3, m3_alphas = run_model_3_hmm(chosen_log, means, vars_, A, inertia=m3_inertia, clutch_decel=m3_clutch_decel, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz, return_details=True)

            b1 = evaluate_glitches(chosen_log["times"], chosen_log["speed_kph"], chosen_log["rpm"], m1)
            b2 = evaluate_glitches(chosen_log["times"], chosen_log["speed_kph"], chosen_log["rpm"], m2)
            b3 = evaluate_glitches(chosen_log["times"], chosen_log["speed_kph"], chosen_log["rpm"], m3)

            # Subsample points for responsive web rendering (max 3500 points)
            step = max(1, len(chosen_log["times"]) // 3500)
            times_sub = chosen_log["times"][::step]
            speed_kph_sub = chosen_log["speed_kph"][::step]
            rpm_sub = chosen_log["rpm"][::step]
            gt_sub = chosen_log["ground_truth"][::step]
            m1_sub = m1[::step]
            m1_ratios_sub = m1_ratios[::step]
            m2_sub = m2[::step]
            m2_posts_sub = m2_posts[::step] if m2_posts else []
            m3_sub = m3[::step]
            m3_alphas_sub = m3_alphas[::step] if m3_alphas else []

            ratios_raw = [
                round(sf / rf, 3) if rf > 0.5 else 0.0
                for rf, sf in zip(chosen_log.get("rpm_freq", []), chosen_log.get("speed_freq", []))
            ]
            ratios_sub = ratios_raw[::step] if ratios_raw else [0.0] * len(times_sub)

            res = {
                "total_driving_samples": agg["total_driving_samples"],
                "fitted": agg["fitted"],
                "transition_matrix": agg["transition_matrix"],
                "histogram": agg["histogram"],
                "session_boundaries": session_boundaries,
                "active_log": log_param,
                "benchmarks": {
                    "m1": b1,
                    "m2": b2,
                    "m3": b3,
                },
                "timeseries": {
                    "times": times_sub,
                    "speed_kph": speed_kph_sub,
                    "rpm": rpm_sub,
                    "ratios": ratios_sub,
                    "ground_truth": gt_sub,
                    "m1_gears": m1_sub,
                    "m1_smoothed_ratios": m1_ratios_sub,
                    "m2_gears": m2_sub,
                    "m2_probs": m2_posts_sub,
                    "m3_gears": m3_sub,
                    "m3_alphas": m3_alphas_sub,
                }
            }
            self.send_json(res)

        elif path == "/api/calibration":
            cal_file = SCRIPT_DIR / "gear_calibration.json"
            if cal_file.is_file():
                try:
                    with open(cal_file, "r", encoding="utf-8") as f:
                        self.send_json(json.load(f))
                        return
                except Exception:
                    pass
            self.send_json({
                "version": 1,
                "nominal_ratios": [1.018, 1.793, 2.726, 3.763, 4.542],
                "tolerance_abs": 0.25,
                "latch_time_ms": 200.0,
                "min_speed_hz": 11.28,
                "min_speed_kph": 25.0,
                "min_rpm": 1000.0,
                "min_rpm_hz": 33.33,
                "stability_gate": 0.05,
                "ratio_alpha": 0.15
            })

        elif path == "/api/export_c":
            if "cached_agg" not in DATASET_CACHE:
                DATASET_CACHE["cached_agg"] = build_aggregated_dataset()
            agg = DATASET_CACHE["cached_agg"]
            c_header = generate_esp32_c_header(agg["fitted"]["means"], agg["fitted"]["vars"], agg["transition_matrix"])
            payload = c_header.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="gear_estimator_params.h"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/train":
            DATASET_CACHE["cached_agg"] = build_aggregated_dataset()
            agg = DATASET_CACHE["cached_agg"]
            self.send_json({
                "status": "success",
                "means": agg["fitted"]["means"],
                "stds": agg["fitted"]["stds"],
                "total_samples": agg["total_driving_samples"]
            })
        elif parsed.path == "/api/calibration":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                cal = json.loads(body.decode("utf-8"))
                cal["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                cal_file = SCRIPT_DIR / "gear_calibration.json"
                existing = {}
                if cal_file.is_file():
                    try:
                        with open(cal_file, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                    except Exception:
                        pass
                existing.update(cal)
                if "tolerance" in existing:
                    existing["tolerance_abs"] = existing["tolerance"]
                if "latch_ms" in existing:
                    existing["latch_time_ms"] = existing["latch_ms"]
                with open(cal_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
                self.send_json({"status": "ok", "saved": existing, "calibration": existing})
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)})

        elif parsed.path == "/api/auto_tune":
            query = urllib.parse.parse_qs(parsed.query)
            target_log = query.get("log", ["all"])[0]
            min_speed_hz = float(query.get("min_speed_hz", [11.28])[0])
            min_rpm_hz = float(query.get("min_rpm_hz", [33.33])[0])

            if "cached_agg" not in DATASET_CACHE:
                DATASET_CACHE["cached_agg"] = build_aggregated_dataset()
            agg = DATASET_CACHE["cached_agg"]
            res = optimize_parameters(agg, target_log=target_log, min_speed_hz=min_speed_hz, min_rpm_hz=min_rpm_hz)
            self.send_json(res)
        else:
            self.send_error(404, "Not found")

    def log_message(self, format, *args):
        # Silence routine request logging
        pass

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

def main():
    global DBC_DEFAULT
    parser = argparse.ArgumentParser(description="MiniGauge Gear Estimator Lab & Model Trainer")
    parser.add_argument("--port", "-p", type=int, default=8082, help="HTTP server port (default: 8082)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically launch web browser")
    parser.add_argument("--dbc", "-d", type=Path, default=DBC_DEFAULT, help="Path to DBC database file")
    args = parser.parse_args()

    if args.dbc.is_file():
        DBC_DEFAULT = args.dbc.resolve()

    port = args.port
    server = None
    for attempt in range(10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), GearLabHandler)
            break
        except OSError:
            port += 1

    if server is None:
        print(f"Error: Could not bind to port {args.port} or subsequent 10 ports.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print(f" MiniGauge Gear Estimator Lab running on {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Gear Estimator Lab...")
        server.server_close()


if __name__ == "__main__":
    main()
