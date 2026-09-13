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
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    CanFrame,
    read_bin_file,
    find_bin_files,
    natural_sort_key,
    DbcSignal,
    DbcMessage,
    DbcDatabase,
    get_dbc,
    load_calibration,
    save_calibration,
    BaseAppHandler,
    start_server,
    RECORD_STRUCT as CAN_FRAME_STRUCT,
)

DBC_DEFAULT = SCRIPT_DIR / "binocan.dbc"


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

def generate_esp32_c_header(means: List[float], vars_: List[float], A: List[List[float]], min_speed_hz: float = 11.28, min_rpm_hz: float = 33.33, cal_data: Optional[Dict[str, Any]] = None) -> str:
    """Produces turnkey C99 header gear_estimator_params.h with parameters, inference routines, and embedded calibration snapshot."""
    c_means = ", ".join(f"{m:.4f}f" for m in means)
    c_vars = ", ".join(f"{v:.5f}f" for v in vars_)

    a_rows = []
    for row in A:
        a_rows.append("    { " + ", ".join(f"{x:.4f}f" for x in row) + " }")
    c_matrix = ",\n".join(a_rows)

    cal_file = SCRIPT_DIR / "gear_calibration.json"
    cal_lines = []
    if cal_data is not None:
        raw_json = json.dumps(cal_data, indent=2)
        cal_lines = [f" * {line}" for line in raw_json.splitlines()]
    elif cal_file.is_file():
        try:
            raw_json = cal_file.read_text(encoding="utf-8")
            cal_lines = [f" * {line}" for line in raw_json.splitlines()]
        except Exception:
            pass

    cal_comment_block = ""
    if cal_lines:
        cal_comment_block = (
            "/*\n"
            " * ============================================================================\n"
            " * Calibration Snapshot (decoder/gear_calibration.json):\n"
            " * ----------------------------------------------------------------------------\n"
            + "\n".join(cal_lines)
            + "\n * ============================================================================\n"
            " */\n\n"
        )

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

{cal_comment_block}#pragma once

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

# ==============================================================================
# HTML / CSS / JS WEB INTERFACE & HTTP REQUEST HANDLER
# ==============================================================================

def get_gear_lab_html() -> str:
    template_path = SCRIPT_DIR / "web" / "templates" / "gear_lab.html"
    return template_path.read_text(encoding="utf-8")


HTML_PAGE = get_gear_lab_html()


class GearLabHandler(BaseAppHandler):
    def do_GET(self):
        if self.path.startswith("/static/"):
            if self.serve_static(self.path):
                return

        path, query = self.parse_query()

        if path in ("/", "/index.html"):
            self.send_html(HTML_PAGE)

        elif path == "/api/logs":
            files = find_bin_files()
            res = [{"filename": f.name, "size": f.stat().st_size} for f in files if f.stat().st_size > 0]
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
            cal = load_calibration()
            self.send_json(cal)

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
        path, query = self.parse_query()
        if path == "/api/train":
            DATASET_CACHE["cached_agg"] = build_aggregated_dataset()
            agg = DATASET_CACHE["cached_agg"]
            self.send_json({
                "status": "success",
                "means": agg["fitted"]["means"],
                "stds": agg["fitted"]["stds"],
                "total_samples": agg["total_driving_samples"]
            })
        elif path == "/api/calibration":
            try:
                body_data = self.read_json_body()
                saved_path = save_calibration(body_data)
                saved = load_calibration(saved_path)
                self.send_json({"status": "ok", "saved": saved, "calibration": saved})
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)})

        elif path == "/api/auto_tune":
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

    start_server(
        GearLabHandler,
        port=args.port,
        open_browser=not args.no_browser,
        server_name="MiniGauge Gear Estimator Lab",
    )


if __name__ == "__main__":
    main()
