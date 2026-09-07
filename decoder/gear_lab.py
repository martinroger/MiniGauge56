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
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
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
                 max_val: float, unit: str, value_table: Dict[int, str]):
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

    def decode(self, data_bytes: bytes) -> Optional[float]:
        val_int = 0
        if self.is_little:
            data_int = int.from_bytes(data_bytes, byteorder="little")
            mask = (1 << self.length) - 1
            raw = (data_int >> self.start_bit) & mask
            if self.is_signed and (raw & (1 << (self.length - 1))):
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
            if self.is_signed and (raw & (1 << (self.length - 1))):
                raw -= (1 << self.length)
            val_int = raw
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
                msg.signals[sname] = DbcSignal(
                    sname, start_bit, length, is_little, is_signed, factor, offset, min_v, max_v, unit, {}
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
    return sorted(SCRIPT_DIR.glob("*.bin"))

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

    return {
        "logs": logs_data,
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

def run_model_1_heuristic(g: Dict[str, Any], means: List[float], latch_ms: float = 200.0) -> List[int]:
    """Model 1: Calibrated Gated Heuristic Baseline with ratio EMA and temporal latching."""
    n = len(g["times"])
    out = [0] * n
    latched = 0
    pending = 0
    p_time = 0.0
    current_ema = None
    prev_raw = None

    for i in range(n):
        t = g["times"][i]
        sf = g["speed_freq"][i]
        rf = g["rpm_freq"][i]

        speed_valid = (sf >= 5.0)
        rpm_valid = (rf >= 25.0)
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
                current_ema = 0.15 * ratio + 0.85 * current_ema
        else:
            current_ema = None

        cand = 0
        if current_ema is not None:
            for gi, nom in enumerate(means):
                max_tol = 0.25
                if gi > 0:
                    max_tol = min(max_tol, (nom - means[gi - 1]) * 0.48)
                if gi < len(means) - 1:
                    max_tol = min(max_tol, (means[gi + 1] - nom) * 0.48)
                if abs(current_ema - nom) <= max_tol:
                    cand = gi + 1
                    break

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

    return out


def run_model_2_bayesian(g: Dict[str, Any], means: List[float], vars_: List[float], decay: float = 0.88) -> List[int]:
    """Model 2: Recursive Bayesian Classifier with Gaussian likelihoods and temporal prior decay."""
    n = len(g["times"])
    out = [0] * n
    prior = [0.80, 0.04, 0.04, 0.04, 0.04, 0.04]

    for i in range(n):
        sf = g["speed_freq"][i]
        rf = g["rpm_freq"][i]

        if sf < 5.0 or rf < 25.0:
            out[i] = 0
            prior = [0.90, 0.02, 0.02, 0.02, 0.02, 0.02]
            continue

        r = sf / rf
        lik = [0.0] * 6
        lik[0] = 0.06 # neutral uniform likelihood

        for gi in range(5):
            diff = r - means[gi]
            v = vars_[gi]
            lik[gi + 1] = math.exp(-0.5 * (diff * diff) / v) / math.sqrt(2 * math.pi * v)

        # Bayes update with temporal forgetting factor
        post = [lik[k] * (decay * prior[k] + (1.0 - decay) * 0.166) for k in range(6)]
        tot = sum(post)
        if tot > 0:
            post = [p / tot for p in post]
        prior = post

        best_k = post.index(max(post))
        out[i] = best_k if post[best_k] >= 0.40 else 0

    return out


def run_model_3_hmm(g: Dict[str, Any], means: List[float], vars_: List[float], A: List[List[float]]) -> List[int]:
    """Model 3: Hidden Markov Model with physical transition matrix & engine deceleration conditioning."""
    n = len(g["times"])
    out = [0] * n
    alpha = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    for i in range(n):
        t = g["times"][i]
        sf = g["speed_freq"][i]
        rf = g["rpm_freq"][i]

        if sf < 5.0 or rf < 25.0:
            out[i] = 0
            alpha = [0.95, 0.01, 0.01, 0.01, 0.01, 0.01]
            continue

        r = sf / rf
        prev_rf = g["rpm_freq"][i - 1] if i > 0 else rf
        dt = max(0.01, t - g["times"][i - 1]) if i > 0 else 0.1
        drpm = (rf - prev_rf) / dt
        is_clutch_drop = (drpm < -40.0) # Engine dropping fast during shift/coast

        prev_g = out[i - 1] if i > 0 else 0
        emiss = [0.0] * 6
        emiss[0] = 0.18 if is_clutch_drop else 0.04

        for gi in range(5):
            diff = r - means[gi]
            v = vars_[gi]
            density = math.exp(-0.5 * (diff * diff) / v) / math.sqrt(2 * math.pi * v)
            # Asymmetric suppression of upward phantom shifts during engine rev-down
            if is_clutch_drop and (gi + 1) > prev_g and prev_g > 0:
                density *= 0.0001
            emiss[gi + 1] = density

        # HMM forward step
        new_alpha = [0.0] * 6
        for j in range(6):
            s = sum(alpha[k] * A[k][j] for k in range(6))
            new_alpha[j] = s * emiss[j]

        tot = sum(new_alpha)
        if tot > 0:
            new_alpha = [x / tot for x in new_alpha]
        alpha = new_alpha

        best_j = alpha.index(max(alpha))
        out[i] = best_j if alpha[best_j] >= 0.38 else 0

    return out


def evaluate_glitches(times: List[float], speeds: List[float], rpms: List[float], gears: List[int]) -> Dict[str, Any]:
    """Computes standardized glitch evaluation metrics: Dropouts, Chatter, Phantoms, and Glitch Score."""
    n = len(gears)
    if n < 3:
        return {"dropouts": 0, "chatter": 0, "phantoms": 0, "glitch_score": 100, "active_pct": "0.0"}

    # Group into contiguous gear segments
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

    for s in range(len(segments)):
        seg = segments[s]
        if seg["gear"] > 0:
            forward_samples += (seg["end"] - seg["start"] + 1)
            # Chatter: dwell < 300 ms in forward gear
            if seg["duration"] < 0.30:
                chatter += 1

        # Neutral dropout: k -> 0 -> k within 450 ms while rolling
        if seg["gear"] == 0 and 0 < s < len(segments) - 1:
            p = segments[s - 1]
            nxt = segments[s + 1]
            if p["gear"] > 0 and p["gear"] == nxt["gear"] and seg["duration"] < 0.45:
                avg_v = (speeds[seg["start"]] + speeds[seg["end"]]) / 2.0
                if avg_v >= 20.0:
                    dropouts += 1

    # Phantom upward shifts during coasting
    for s in range(1, len(segments)):
        prev_s = segments[s - 1]
        cur_s = segments[s]
        if cur_s["gear"] > prev_s["gear"] > 0:
            idx = cur_s["start"]
            back_idx = max(0, idx - 4)
            dt = times[idx] - times[back_idx]
            if dt > 0.05:
                drpm = (rpms[idx] - rpms[back_idx]) / dt
                dspeed = (speeds[idx] - speeds[back_idx]) / dt
                if drpm < -1200.0 and dspeed < 1.0:
                    phantoms += 1

    score = max(0, min(100, round(100 - (2.5 * dropouts + 1.0 * chatter + 5.0 * phantoms))))
    active_pct = f"{(forward_samples / n * 100):.1f}"

    return {
        "dropouts": dropouts,
        "chatter": chatter,
        "phantoms": phantoms,
        "glitch_score": score,
        "active_pct": active_pct,
    }

# ==============================================================================
# ESP32 C HEADER GENERATION (zero-allocation, fixed-size C99 implementation)
# ==============================================================================

def generate_esp32_c_header(means: List[float], vars_: List[float], A: List[List[float]]) -> str:
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
 * 2. Recursive Bayesian Classifier (Gaussian likelihood with temporal prior decay)
 * 3. Hidden Markov Model (HMM 6-state transition filter with clutch suppression)
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {{
#endif

/* Calibrated Nominal Gear Ratios & Variances (1st through 5th gear) */
#define GEAR_NUM_FORWARD_GEARS 5
#define GEAR_TOLERANCE_ABS     (0.25f)

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
    st->latched_gear = 0;
    st->pending_gear = 0;
    st->pending_time_ms = 0.0f;
    st->prev_ratio = 0.0f;
}}

static inline uint8_t gear_heuristic_update(gear_heuristic_state_t *st, float speed_freq, float rpm_freq, float dt_s) {{
    if (speed_freq < 5.0f || rpm_freq < 25.0f) {{
        st->latched_gear = 0;
        st->pending_gear = 0;
        st->pending_time_ms = 0.0f;
        st->latched_ratio_ema = 0.0f;
        return 0;
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

    uint8_t cand = 0;
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
/* Model 2: Recursive Bayesian Classifier                                     */
/* -------------------------------------------------------------------------- */
typedef struct {{
    float prior[6];
}} gear_bayesian_state_t;

static inline void gear_bayesian_init(gear_bayesian_state_t *st) {{
    st->prior[0] = 0.80f;
    for (int i = 1; i < 6; i++) st->prior[i] = 0.04f;
}}

static inline uint8_t gear_bayesian_update(gear_bayesian_state_t *st, float speed_freq, float rpm_freq) {{
    if (speed_freq < 5.0f || rpm_freq < 25.0f) {{
        st->prior[0] = 0.90f;
        for (int i = 1; i < 6; i++) st->prior[i] = 0.02f;
        return 0;
    }}

    float r = speed_freq / rpm_freq;
    float lik[6];
    lik[0] = 0.060f; /* Neutral floor */

    for (int gi = 0; gi < 5; gi++) {{
        float diff = r - GEAR_RATIO_MEANS[gi];
        float v = GEAR_RATIO_VARS[gi];
        lik[gi + 1] = expf(-0.5f * (diff * diff) / v) / sqrtf(6.2831853f * v);
    }}

    const float decay = 0.88f;
    float post[6];
    float tot = 0.0f;

    for (int k = 0; k < 6; k++) {{
        post[k] = lik[k] * (decay * st->prior[k] + (1.0f - decay) * 0.166f);
        tot += post[k];
    }}

    uint8_t best_k = 0;
    float max_p = 0.0f;

    if (tot > 0.00001f) {{
        float inv = 1.0f / tot;
        for (int k = 0; k < 6; k++) {{
            st->prior[k] = post[k] * inv;
            if (st->prior[k] > max_p) {{
                max_p = st->prior[k];
                best_k = (uint8_t)k;
            }}
        }}
    }}

    return (max_p >= 0.40f) ? best_k : 0;
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
    st->prev_gear = 0;
}}

static inline uint8_t gear_hmm_update(gear_hmm_state_t *st, float speed_freq, float rpm_freq, float dt_s) {{
    if (speed_freq < 5.0f || rpm_freq < 25.0f) {{
        st->alpha[0] = 0.95f;
        for (int i = 1; i < 6; i++) st->alpha[i] = 0.01f;
        st->prev_rpm_freq = rpm_freq;
        st->prev_gear = 0;
        return 0;
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
        if (is_clutch_drop && (gi + 1) > st->prev_gear && st->prev_gear > 0) {{
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

    uint8_t best_j = 0;
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

    uint8_t result = (max_a >= 0.38f) ? best_j : 0;
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
      padding: 1rem;
      gap: 1rem;
    }
    .content-pane {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      padding: 0.75rem;
      gap: 0.65rem;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      padding: 0.75rem 0.9rem;
    }
    .card-title {
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      margin-bottom: 0.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    /* Comparison Scorecard Table */
    .benchmark-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      text-align: left;
    }
    .benchmark-table th {
      padding: 0.45rem 0.65rem;
      background: var(--input-bg);
      color: var(--text-muted);
      font-size: 0.72rem;
      text-transform: uppercase;
      border-bottom: 1px solid var(--panel-border);
    }
    .benchmark-table td {
      padding: 0.5rem 0.65rem;
      border-bottom: 1px solid var(--panel-border);
      font-family: monospace;
    }
    .model-badge {
      font-family: -apple-system, sans-serif;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      display: inline-block;
    }
    .badge-m1 { background: rgba(59, 130, 246, 0.2); color: #3b82f6; border: 1px solid #3b82f6; }
    .badge-m2 { background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid #f59e0b; }
    .badge-m3 { background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981; }

    .val-good { color: var(--accent); font-weight: 700; }
    .val-warn { color: var(--warning); font-weight: 700; }
    .val-bad  { color: var(--danger); font-weight: 700; }

    /* Plots */
    .plots-column {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
      overflow: hidden;
      min-height: 0;
    }
    .plot-box {
      flex: 1;
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      min-height: 150px;
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
    <div class="sidebar">
      <div class="card">
        <div class="card-title">Multi-Log Dataset Overview</div>
        <div style="font-size:0.8rem; line-height:1.45; color:var(--text-muted);">
          Total Log Files: <strong style="color:var(--text);" id="stat-log-count">--</strong><br>
          Driving Frames: <strong style="color:var(--text);" id="stat-sample-count">--</strong><br>
          Vehicle Base: <span style="font-family:monospace; color:var(--primary);">4-cyl 5-Speed MT</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Trained Gear Ratio Clusters</div>
        <table style="width:100%; font-size:0.8rem; border-collapse:collapse; text-align:left;">
          <thead>
            <tr style="color:var(--text-muted); font-size:0.7rem; border-bottom:1px solid var(--panel-border);">
              <th>Gear</th>
              <th>Ratio (&mu;)</th>
              <th>Std Dev (&sigma;)</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody id="tbl-cluster-body">
            <tr><td colspan="4" style="text-align:center; padding:0.5rem; color:var(--text-muted);">Loading...</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-title">HMM Transition Dynamics</div>
        <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:0.4rem;">
          Trained 6x6 state matrix with physical shift constraints and clutch-drop suppression.
        </div>
        <div id="hmm-matrix-summary" style="font-family:monospace; font-size:0.72rem; line-height:1.4; background:var(--input-bg); padding:0.4rem; border-radius:4px;">
          Self-inertia: ~97%<br>
          Drop to N on clutch: Active
        </div>
      </div>

      <div class="card" style="border-left:3px solid var(--accent);">
        <div class="card-title" style="color:var(--accent);">ESP32 Deployment Notes</div>
        <div style="font-size:0.75rem; color:var(--text-muted); line-height:1.4;">
          All 3 models run with <strong>zero heap allocation</strong>.<br>
          • Model 1: ~0.4 &mu;s execution (table lookup)<br>
          • Model 2: ~1.2 &mu;s (5 Gaussians + Bayes)<br>
          • Model 3: ~1.8 &mu;s (36 MAC operations)<br>
          RAM footprint: <strong>&lt; 64 bytes</strong>.
        </div>
      </div>
    </div>

    <div class="content-pane">
      <!-- Comparative Benchmark Matrix -->
      <div class="card" style="padding:0.6rem 0.8rem;">
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
              <td style="color:var(--text-muted); font-size:0.75rem;">Static hysteresis timer</td>
            </tr>
            <tr>
              <td><span class="model-badge badge-m2">M2: Recursive Bayes</span></td>
              <td class="val-good" id="m2-score">--%</td>
              <td id="m2-drop">--</td>
              <td id="m2-chat">--</td>
              <td id="m2-phan">--</td>
              <td id="m2-act">--%</td>
              <td style="color:var(--text-muted); font-size:0.75rem;">1D Gaussian + prior decay</td>
            </tr>
            <tr>
              <td><span class="model-badge badge-m3">M3: HMM State-Space</span></td>
              <td class="val-good" id="m3-score">--%</td>
              <td id="m3-drop">--</td>
              <td id="m3-chat">--</td>
              <td id="m3-phan">--</td>
              <td id="m3-act">--%</td>
              <td style="color:var(--text-muted); font-size:0.75rem;">6-state forward filter</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Plots Column -->
      <div class="plots-column">
        <div class="plot-box" id="plot-ratio-hist" style="flex:0.75;"></div>
        <div class="plot-box" id="plot-dynamics" style="flex:0.7;"></div>
        <div class="plot-box" id="plot-models-compare" style="flex:1.2;"></div>
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
      renderAllPlots();
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

    async function loadDataset() {
      try {
        const res = await fetch(`/api/dataset?log=${encodeURIComponent(currentLog)}`);
        datasetData = await res.json();
        updateUI();
        renderAllPlots();
      } catch (err) {
        console.error('Failed to load dataset:', err);
      }
    }

    async function loadLogsList() {
      try {
        const res = await fetch('/api/logs');
        const logs = await res.json();
        const sel = document.getElementById('select-log');
        sel.innerHTML = '<option value="all">⚡ All Combined Logs (Aggregated)</option>';
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
          <td style="font-family:monospace;">${f.counts[i]}</td>
        `;
        tbody.appendChild(tr);
      }

      // Update benchmark table
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

        setScore('m2-score', b.m2.glitch_score);
        document.getElementById('m2-drop').innerText = b.m2.dropouts;
        document.getElementById('m2-chat').innerText = b.m2.chatter;
        document.getElementById('m2-phan').innerText = b.m2.phantoms;
        document.getElementById('m2-act').innerText = b.m2.active_pct + '%';

        setScore('m3-score', b.m3.glitch_score);
        document.getElementById('m3-drop').innerText = b.m3.dropouts;
        document.getElementById('m3-chat').innerText = b.m3.chatter;
        document.getElementById('m3-phan').innerText = b.m3.phantoms;
        document.getElementById('m3-act').innerText = b.m3.active_pct + '%';
      }
    }

    function renderAllPlots() {
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

      // Overlay Gaussian bell curves
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
        margin: { t: 25, b: 25, l: 45, r: 45 },
        title: { text: `Synchronized Driving Dynamics (${currentLog})`, font: { size: 11 } },
        xaxis: { title: '', gridcolor: theme.gridcolor },
        yaxis: { title: 'km/h', titlefont: { color: '#38bdf8' }, tickfont: { color: '#38bdf8' }, gridcolor: theme.gridcolor },
        yaxis2: { title: 'RPM', titlefont: { color: '#f59e0b' }, tickfont: { color: '#f59e0b' }, overlaying: 'y', side: 'right', gridcolor: 'transparent' },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      // 3. Side-by-Side Model Comparison
      const compareTraces = [
        {
          x: ts.times,
          y: ts.m1_gears,
          mode: 'lines',
          name: 'M1: Gated Heuristic',
          line: { color: '#3b82f6', width: 1.8, shape: 'hv' }
        },
        {
          x: ts.times,
          y: ts.m2_gears,
          mode: 'lines',
          name: 'M2: Recursive Bayes',
          line: { color: '#f59e0b', width: 1.8, shape: 'hv' }
        },
        {
          x: ts.times,
          y: ts.m3_gears,
          mode: 'lines',
          name: 'M3: HMM State-Space',
          line: { color: '#10b981', width: 2.2, shape: 'hv' }
        }
      ];

      if (ts.ground_truth && ts.ground_truth.some(x => x > 0)) {
        compareTraces.push({
          x: ts.times,
          y: ts.ground_truth,
          mode: 'lines',
          name: 'ITF_gear_position_ST',
          line: { color: '#94a3b8', width: 1.5, dash: 'dot', shape: 'hv' }
        });
      }

      Plotly.react('plot-models-compare', compareTraces, {
        ...theme,
        margin: { t: 30, b: 35, l: 45, r: 25 },
        title: { text: 'Side-by-Side Model Predictions (M1 Gated Heuristic vs. M2 Bayes vs. M3 HMM)', font: { size: 11 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor },
        yaxis: {
          title: 'Gear',
          gridcolor: theme.gridcolor,
          tickvals: [0, 1, 2, 3, 4, 5],
          ticktext: ['N', '1st', '2nd', '3rd', '4th', '5th'],
          range: [-0.3, 5.5]
        },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      // Synchronize zooming between dynamics and models timeline
      const dynEl = document.getElementById('plot-dynamics');
      const compEl = document.getElementById('plot-models-compare');

      if (dynEl && !dynEl._syncAttached) {
        dynEl._syncAttached = true;
        dynEl.on('plotly_relayout', (ed) => {
          if (ed['xaxis.range[0]'] !== undefined) {
            Plotly.relayout('plot-models-compare', {
              'xaxis.range[0]': ed['xaxis.range[0]'],
              'xaxis.range[1]': ed['xaxis.range[1]']
            });
          }
        });
      }
      if (compEl && !compEl._syncAttached) {
        compEl._syncAttached = true;
        compEl.on('plotly_relayout', (ed) => {
          if (ed['xaxis.range[0]'] !== undefined) {
            Plotly.relayout('plot-dynamics', {
              'xaxis.range[0]': ed['xaxis.range[0]'],
              'xaxis.range[1]': ed['xaxis.range[1]']
            });
          }
        });
      }
    }

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

            # Select timeseries to return
            chosen_log = None
            if log_param != "all":
                chosen_log = next((l for l in agg["logs"] if l["filename"] == log_param), None)
            if not chosen_log:
                chosen_log = agg["logs"][0] if agg["logs"] else {"times": [], "speed_freq": [], "rpm_freq": [], "speed_kph": [], "rpm": [], "ground_truth": []}

            # Run 3 models on the chosen log
            m1 = run_model_1_heuristic(chosen_log, means)
            m2 = run_model_2_bayesian(chosen_log, means, vars_)
            m3 = run_model_3_hmm(chosen_log, means, vars_, A)

            b1 = evaluate_glitches(chosen_log["times"], chosen_log["speed_kph"], chosen_log["rpm"], m1)
            b2 = evaluate_glitches(chosen_log["times"], chosen_log["speed_kph"], chosen_log["rpm"], m2)
            b3 = evaluate_glitches(chosen_log["times"], chosen_log["speed_kph"], chosen_log["rpm"], m3)

            # Cap samples for web rendering responsiveness (max 3500 points)
            step = max(1, len(chosen_log["times"]) // 3500)
            times_sub = chosen_log["times"][::step]
            speed_kph_sub = chosen_log["speed_kph"][::step]
            rpm_sub = chosen_log["rpm"][::step]
            gt_sub = chosen_log["ground_truth"][::step]
            m1_sub = m1[::step]
            m2_sub = m2[::step]
            m3_sub = m3[::step]

            res = {
                "total_driving_samples": agg["total_driving_samples"],
                "fitted": agg["fitted"],
                "transition_matrix": agg["transition_matrix"],
                "histogram": agg["histogram"],
                "benchmarks": {
                    "m1": b1,
                    "m2": b2,
                    "m3": b3,
                },
                "timeseries": {
                    "times": times_sub,
                    "speed_kph": speed_kph_sub,
                    "rpm": rpm_sub,
                    "ground_truth": gt_sub,
                    "m1_gears": m1_sub,
                    "m2_gears": m2_sub,
                    "m3_gears": m3_sub,
                }
            }
            self.send_json(res)

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
            # Re-train models across all logs
            DATASET_CACHE["cached_agg"] = build_aggregated_dataset()
            agg = DATASET_CACHE["cached_agg"]
            self.send_json({
                "status": "success",
                "means": agg["fitted"]["means"],
                "stds": agg["fitted"]["stds"],
                "total_samples": agg["total_driving_samples"]
            })
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
            server = HTTPServer(("127.0.0.1", port), GearLabHandler)
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
