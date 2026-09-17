#!/usr/bin/env python3
"""MiniGauge CAN Log Replayer & UDP Streamer.

Replays recorded MiniGauge .bin CAN bus logs and streams high-fidelity vehicle
telemetry datagrams over UDP to binocle-emulator.local:8888 running the
ESPHome vehicle emulator firmware (emulator-console.yaml / udp_receiver.h).

Zero pip dependencies (Python 3 stdlib only).
"""

import argparse
import bisect
import json
import math
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure decoder folder is on sys.path for common imports
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    BaseAppHandler,
    CanFrame,
    DbcDatabase,
    find_bin_files,
    get_dbc,
    natural_sort_key,
    read_bin_file,
    start_server,
)

# Constants & Coefficients (matching emulator-console.yaml & coefficients.h)
UDP_MAGIC = b"\xAA\x55"
DEFAULT_TARGET_HOST = "binocle-emulator.local"
DEFAULT_TARGET_PORT = 8888
DEFAULT_HTTP_PORT = 8090
DEFAULT_DISPATCH_RATE_HZ = 50.0

COEFF_SPEED_KPH_TO_FREQ = 4.088998
COEFF_FREQ_TO_SPEED_KPH = 0.2445587
COEFF_RPM_TO_FREQ = 1.0 / 30.0
COEFF_FREQ_TO_RPM = 30.0
COEFF_COOLANT_DEGC_TO_DUTY_M = 1.3939784
COEFF_COOLANT_DEGC_TO_DUTY_P = -89.741434
COEFF_DUTY_TO_COOLANT_DEGC_M = 0.7173712
COEFF_DUTY_TO_COOLANT_DEGC_P = 64.377923
COEFF_FUEL_PCT_TO_OHM = 2.5

# Standby Mask: 0xD940 (Ignition ON, inverted telltales HIGH/off, warnings LOW/off)
MASK_STANDBY = 0xD940

# Fuel resistance steps from resistor_ladder.h
FUEL_RES_VALUES = [
    30.2, 39.6, 50.0, 59.5, 70.9, 79.3, 90.0, 100.9, 112.3, 118.9,
    129.8, 138.8, 149.2, 161.2, 175.3, 192.2, 212.6, 237.9, 270.0,
]


def find_closest_fuel_step(target_ohm: float) -> int:
    """Finds the closest fuel step (1..19) for a target resistance in Ohms."""
    best_step = 1
    min_diff = 1e9
    for i, val in enumerate(FUEL_RES_VALUES):
        diff = abs(val - target_ohm)
        if diff < min_diff:
            min_diff = diff
            best_step = i + 1
    return best_step


def pack_udp_packet(
    telltales_mask: int,
    speed_freq: float,
    rpm_freq: float,
    coolant_duty: float,
    fuel_ohm: float,
) -> Tuple[bytes, int]:
    """Packs telemetry values into the 14-byte VehicleUdpPacket datagram."""
    # Clamp values to valid positive 16-bit ranges
    mask_val = telltales_mask & 0xFFFF
    spd_val = max(0, min(65535, int(round(speed_freq * 10.0))))
    rpm_val = max(0, min(65535, int(round(rpm_freq * 10.0))))
    cool_val = max(0, min(65535, int(round(coolant_duty * 100.0))))
    fuel_val = max(0, min(65535, int(round(fuel_ohm * 10.0))))

    raw_first_12 = struct.pack(
        "<2sHHHHH",
        UDP_MAGIC,
        mask_val,
        spd_val,
        rpm_val,
        cool_val,
        fuel_val,
    )
    checksum = sum(raw_first_12) & 0xFFFF
    packet = raw_first_12 + struct.pack("<H", checksum)
    return packet, checksum


class LogTimeline:
    """Decodes and indexes mapped signals from a .bin CAN log for random-access playback."""

    def __init__(self, log_path: Path, db: DbcDatabase):
        self.log_path = log_path
        self.filename = log_path.name
        self.size = log_path.stat().st_size
        self.frames = read_bin_file(log_path)
        self.frame_count = len(self.frames)
        self.duration_s = round(self.frames[-1].time_rel_s, 3) if self.frames else 0.0

        # Timeline event list: (time_rel_s, signal_type, value_payload)
        self.events: List[Tuple[float, str, Any]] = []
        self.event_times: List[float] = []

        # Synchronized telemetry traces for plotting
        self.trace_times: List[float] = []
        self.trace_speeds: List[float] = []
        self.trace_rpms: List[float] = []

        self._decode_signals(db)

    def _decode_signals(self, db: DbcDatabase) -> None:
        """Parses relevant frames and records timestamped state transitions."""
        if not self.frames:
            return

        msg_fast = db.get_message(256)
        msg_telltales = db.get_message(257)
        msg_slow = db.get_message(272)
        msg_dbg_spd = db.get_message(768)
        msg_dbg_rpm = db.get_message(769)
        msg_dbg_cool = db.get_message(770)
        msg_dbg_fuel = db.get_message(773)

        cur_trace_spd = 0.0
        cur_trace_rpm = 0.0

        for f in self.frames:
            t = f.time_rel_s
            cid = f.can_id

            if cid == 768 and msg_dbg_spd:
                dec = msg_dbg_spd.decode(f.data)
                if "DBG_speed_freq" in dec:
                    freq = float(dec["DBG_speed_freq"]["value"])
                    self.events.append((t, "dbg_speed_freq", freq))
                    cur_trace_spd = freq * COEFF_FREQ_TO_SPEED_KPH

            elif cid == 769 and msg_dbg_rpm:
                dec = msg_dbg_rpm.decode(f.data)
                if "DBG_RPM_freq" in dec:
                    freq = float(dec["DBG_RPM_freq"]["value"])
                    self.events.append((t, "dbg_rpm_freq", freq))
                    cur_trace_rpm = freq * COEFF_FREQ_TO_RPM

            elif cid == 770 and msg_dbg_cool:
                dec = msg_dbg_cool.decode(f.data)
                if "DBG_coolant_duty" in dec:
                    self.events.append((t, "dbg_coolant_duty", float(dec["DBG_coolant_duty"]["value"])))

            elif cid == 773 and msg_dbg_fuel:
                dec = msg_dbg_fuel.decode(f.data)
                if "DBG_fuel_r" in dec:
                    self.events.append((t, "dbg_fuel_r", float(dec["DBG_fuel_r"]["value"])))

            elif cid == 256 and msg_fast:
                dec = msg_fast.decode(f.data)
                if "ITF_speed_kph" in dec and "ITF_rpm" in dec:
                    spd = float(dec["ITF_speed_kph"]["value"])
                    rpm = float(dec["ITF_rpm"]["value"])
                    gear = int(dec.get("ITF_gear_position_ST", {}).get("value", 0))
                    self.events.append((t, "fast_metrics", (spd, rpm, gear)))

                    # Use standard CAN speed/rpm if not already driven by debug frequencies
                    if cur_trace_spd == 0.0 and spd > 0.0:
                        cur_trace_spd = spd
                    elif spd == 0.0 and cur_trace_spd < 0.1:
                        cur_trace_spd = 0.0
                    else:
                        cur_trace_spd = spd

                    cur_trace_rpm = rpm

                    self.trace_times.append(round(t, 3))
                    self.trace_speeds.append(round(cur_trace_spd, 1))
                    self.trace_rpms.append(round(cur_trace_rpm, 1))

            elif cid == 272 and msg_slow:
                dec = msg_slow.decode(f.data)
                if "ITF_coolant_temp" in dec and "ITF_fuel_level_pc" in dec:
                    self.events.append((t, "slow_metrics", (
                        float(dec["ITF_coolant_temp"]["value"]),
                        float(dec["ITF_fuel_level_pc"]["value"]),
                        float(dec.get("ITF_lv_voltage_v", {}).get("value", 12.0))
                    )))

            elif cid == 257 and msg_telltales:
                dec = msg_telltales.decode(f.data)
                mask = self._compute_telltales_mask(dec)
                self.events.append((t, "telltales_mask", mask))

        self.event_times = [e[0] for e in self.events]

    @staticmethod
    def _compute_telltales_mask(dec: Dict[str, Any]) -> int:
        """Converts decoded ITF_active_hi_lo signals to TCA9555 Expander 0 bitmask."""
        # Standby safe baseline:
        # Bit 15 = 1 (Ignition ON)
        # Bit 14 = 1 (High Beams OFF, inv=true)
        # Bit 12 = 1 (Left Turn OFF, inv=true)
        # Bit 11 = 1 (Right Turn OFF, inv=true)
        # Bit 8  = 1 (Low Coolant OFF, inv=true)
        # Bit 6  = 1 (Alarm Status)
        mask = 0xD940

        # Bit 0: Low Brake Fluid (inv=false, AL on car: 0 is warning)
        if "ITF_brake_low_AL_TT" in dec:
            if dec["ITF_brake_low_AL_TT"]["value"] == 0:
                mask |= (1 << 0)
            else:
                mask &= ~(1 << 0)

        # Bit 1: Parking Brake (inv=false, AL on car: 0 is engaged/pulled)
        if "ITF_parking_brake_AL_TT" in dec:
            if dec["ITF_parking_brake_AL_TT"]["value"] == 0:
                mask |= (1 << 1)
            else:
                mask &= ~(1 << 1)

        # Bit 2: Oil Pressure Low (inv=false, AL on car: 0 is warning)
        if "ITF_oil_pressure_AL_TT" in dec:
            if dec["ITF_oil_pressure_AL_TT"]["value"] == 0:
                mask |= (1 << 2)
            else:
                mask &= ~(1 << 2)

        # Bit 3: Airbag Warning (inv=false, AL on car: 0 is warning)
        if "ITF_airbag_AL_TT" in dec:
            if dec["ITF_airbag_AL_TT"]["value"] == 0:
                mask |= (1 << 3)
            else:
                mask &= ~(1 << 3)

        # Bit 4: Check Engine Light (inv=false, AL on car: 0 is warning)
        if "ITF_CEL_AL_TT" in dec:
            if dec["ITF_CEL_AL_TT"]["value"] == 0:
                mask |= (1 << 4)
            else:
                mask &= ~(1 << 4)

        # Bit 5: Cluster Backlight (inv=false, AH: 1 is active)
        if "ITF_backlight_AH" in dec:
            if dec["ITF_backlight_AH"]["value"] == 1:
                mask |= (1 << 5)
            else:
                mask &= ~(1 << 5)

        # Bit 6: Alarm Status (inv=false, AH: 1 is active)
        if "ITF_alarm_AH" in dec:
            if dec["ITF_alarm_AH"]["value"] == 1:
                mask |= (1 << 6)
            else:
                mask &= ~(1 << 6)

        # Bit 7: Cluster Button (inv=false, AL: 0 is pressed)
        if "ITF_button_AL" in dec:
            if dec["ITF_button_AL"]["value"] == 0:
                mask |= (1 << 7)
            else:
                mask &= ~(1 << 7)

        # Bit 8: Low Coolant (inv=true, AH: 1 is warning -> drives pin 0 / LOW)
        if "ITF_coolant_low_AH_TT" in dec:
            if dec["ITF_coolant_low_AH_TT"]["value"] == 1:
                mask &= ~(1 << 8)  # Active warning pulls pin LOW (0)
            else:
                mask |= (1 << 8)   # Normal keeps pin HIGH (1)

        # Bit 9: Door Ajar (inv=false, AL: 0 is door open)
        if "ITF_door_AL_TT" in dec:
            if dec["ITF_door_AL_TT"]["value"] == 0:
                mask |= (1 << 9)
            else:
                mask &= ~(1 << 9)

        # Bit 10: ABS Warning (inv=false, AL: 0 is warning)
        if "ITF_abs_AL_TT" in dec:
            if dec["ITF_abs_AL_TT"]["value"] == 0:
                mask |= (1 << 10)
            else:
                mask &= ~(1 << 10)

        # Bit 11: Right Turn Indicator (inv=true, AH: 1 is blinking -> drives pin 0 / LOW)
        if "ITF_right_turn_AH_TT" in dec:
            if dec["ITF_right_turn_AH_TT"]["value"] == 1:
                mask &= ~(1 << 11)  # Active blinker drives pin LOW (0)
            else:
                mask |= (1 << 11)   # Off keeps pin HIGH (1)

        # Bit 12: Left Turn Indicator (inv=true, AH: 1 is blinking -> drives pin 0 / LOW)
        if "ITF_left_turn_AH_TT" in dec:
            if dec["ITF_left_turn_AH_TT"]["value"] == 1:
                mask &= ~(1 << 12)  # Active blinker drives pin LOW (0)
            else:
                mask |= (1 << 12)   # Off keeps pin HIGH (1)

        # Bit 13: Alternator / Battery Warning (inv=false, AL: 0 is warning)
        if "ITF_alternator_AL_TT" in dec:
            if dec["ITF_alternator_AL_TT"]["value"] == 0:
                mask |= (1 << 13)
            else:
                mask &= ~(1 << 13)

        # Bit 14: High Beams (inv=true, AH: 1 is on -> drives pin 0 / LOW)
        if "ITF_hi_beams_AH_TT" in dec:
            if dec["ITF_hi_beams_AH_TT"]["value"] == 1:
                mask &= ~(1 << 14)  # Active high beams drive pin LOW (0)
            else:
                mask |= (1 << 14)   # Off keeps pin HIGH (1)

        # Bit 15: Ignition is ALWAYS forced ON to keep emulator board alive
        mask |= (1 << 15)
        return mask

    def sample_at(self, target_time_s: float) -> Dict[str, Any]:
        """Samples the latest known values of all mapped signals up to target_time_s."""
        idx = bisect.bisect_right(self.event_times, target_time_s)

        # Default initial state
        has_dbg_spd = False
        has_dbg_rpm = False
        has_dbg_cool = False
        has_dbg_fuel = False

        dbg_spd = 0.0
        dbg_rpm = 0.0
        dbg_cool = 20.0
        dbg_fuel = 270.0

        can_spd_kph = 0.0
        can_rpm = 0.0
        can_cool_degc = 70.0
        can_fuel_pct = 100.0
        can_voltage = 12.0
        can_gear = 0
        telltales = MASK_STANDBY

        for i in range(idx):
            _, ev_type, val = self.events[i]
            if ev_type == "dbg_speed_freq":
                has_dbg_spd = True
                dbg_spd = val
            elif ev_type == "dbg_rpm_freq":
                has_dbg_rpm = True
                dbg_rpm = val
            elif ev_type == "dbg_coolant_duty":
                has_dbg_cool = True
                dbg_cool = val
            elif ev_type == "dbg_fuel_r":
                has_dbg_fuel = True
                dbg_fuel = val
            elif ev_type == "fast_metrics":
                can_spd_kph, can_rpm, can_gear = val
            elif ev_type == "slow_metrics":
                can_cool_degc, can_fuel_pct, can_voltage = val
            elif ev_type == "telltales_mask":
                telltales = val

        # Resolve primary vs fallback
        speed_freq = dbg_spd if has_dbg_spd else (can_spd_kph * COEFF_SPEED_KPH_TO_FREQ)
        rpm_freq = dbg_rpm if has_dbg_rpm else (can_rpm * COEFF_RPM_TO_FREQ)

        if has_dbg_cool:
            coolant_duty = dbg_cool
        else:
            coolant_duty = (can_cool_degc * COEFF_COOLANT_DEGC_TO_DUTY_M) + COEFF_COOLANT_DEGC_TO_DUTY_P

        if has_dbg_fuel:
            fuel_ohm = dbg_fuel
        else:
            fuel_ohm = can_fuel_pct * COEFF_FUEL_PCT_TO_OHM

        # Clamp physical limits
        speed_freq = max(0.0, speed_freq)
        rpm_freq = max(0.0, rpm_freq)
        coolant_duty = max(0.0, min(100.0, coolant_duty))
        fuel_ohm = max(0.0, min(500.0, fuel_ohm))

        # Calculate equivalent human gauge readings
        disp_kph = speed_freq * COEFF_FREQ_TO_SPEED_KPH
        disp_rpm = rpm_freq * COEFF_FREQ_TO_RPM
        disp_cool_degc = (coolant_duty * COEFF_DUTY_TO_COOLANT_DEGC_M) + COEFF_DUTY_TO_COOLANT_DEGC_P
        disp_fuel_pct = min(100.0, (fuel_ohm / 250.0) * 100.0)

        fuel_step = find_closest_fuel_step(fuel_ohm)

        return {
            "speed_freq": round(speed_freq, 2),
            "rpm_freq": round(rpm_freq, 2),
            "coolant_duty": round(coolant_duty, 2),
            "fuel_ohm": round(fuel_ohm, 1),
            "fuel_step": fuel_step,
            "telltales_mask": telltales,
            "disp_kph": round(disp_kph, 1),
            "disp_mph": round(disp_kph / 1.609344, 1),
            "disp_rpm": round(disp_rpm),
            "disp_cool_degc": round(disp_cool_degc, 1),
            "disp_fuel_pct": round(disp_fuel_pct, 1),
            "gear": can_gear,
            "voltage_v": round(can_voltage, 1),
            "is_debug_source": has_dbg_spd or has_dbg_rpm,
        }

    def get_traces(self, max_points: int = 2500) -> Dict[str, Any]:
        """Returns time series of speed and rpm traces, optionally downsampled."""
        if not self.trace_times:
            return {"times": [], "speeds": [], "rpms": [], "duration_s": self.duration_s}

        n = len(self.trace_times)
        if n <= max_points:
            return {
                "times": self.trace_times,
                "speeds": self.trace_speeds,
                "rpms": self.trace_rpms,
                "duration_s": self.duration_s,
            }

        step = (n - 1) / (max_points - 1) if max_points > 1 else 1.0
        sampled_times = []
        sampled_speeds = []
        sampled_rpms = []
        for i in range(max_points - 1):
            idx = int(round(i * step))
            sampled_times.append(self.trace_times[idx])
            sampled_speeds.append(self.trace_speeds[idx])
            sampled_rpms.append(self.trace_rpms[idx])

        sampled_times.append(self.trace_times[-1])
        sampled_speeds.append(self.trace_speeds[-1])
        sampled_rpms.append(self.trace_rpms[-1])

        return {
            "times": sampled_times,
            "speeds": sampled_speeds,
            "rpms": sampled_rpms,
            "duration_s": self.duration_s,
        }


class PlaybackStreamer:
    """Threaded replayer and UDP streaming worker."""

    def __init__(self, target_host: str = DEFAULT_TARGET_HOST, target_port: int = DEFAULT_TARGET_PORT):
        self.target_host = target_host
        self.target_port = target_port
        self.dispatch_rate_hz = DEFAULT_DISPATCH_RATE_HZ
        self.dispatch_interval = 1.0 / self.dispatch_rate_hz

        self.timeline: Optional[LogTimeline] = None
        self.state: str = "STOPPED"  # STOPPED, PLAYING, PAUSED
        self.current_time_s: float = 0.0
        self.playback_speed: float = 1.0
        self.loop_enabled: bool = False
        self.freeze_on_pause: bool = True

        self.packets_sent: int = 0
        self.send_rate_hz: float = 0.0
        self.last_packet_hex: str = ""
        self.last_packet_fields: Dict[str, Any] = {}
        self.last_error: str = ""

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._resolved_addr: Optional[Tuple[str, int]] = None
        self._last_rate_calc_time = time.perf_counter()
        self._packets_in_period = 0

        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def set_target(self, host: str, port: int) -> None:
        """Updates remote UDP endpoint target host and port."""
        with self._lock:
            self.target_host = host.strip()
            self.target_port = int(port)
            self._resolved_addr = None

    def load_log(self, log_path: Path, db: DbcDatabase) -> bool:
        """Loads and indexes a .bin log file."""
        try:
            tl = LogTimeline(log_path, db)
            with self._lock:
                self.timeline = tl
                self.state = "STOPPED"
                self.current_time_s = 0.0
                self.last_error = ""
            return True
        except Exception as ex:
            with self._lock:
                self.last_error = f"Failed to load log: {ex}"
            return False

    def play(self) -> None:
        with self._lock:
            if self.timeline and self.timeline.duration_s > 0:
                if self.current_time_s >= self.timeline.duration_s:
                    self.current_time_s = 0.0
                self.state = "PLAYING"

    def pause(self) -> None:
        with self._lock:
            if self.state == "PLAYING":
                self.state = "PAUSED"
                if not self.freeze_on_pause:
                    self._send_standby_packet()

    def stop(self) -> None:
        with self._lock:
            self.state = "STOPPED"
            self.current_time_s = 0.0
            self._send_standby_packet()

    def seek(self, target_s: float) -> None:
        with self._lock:
            if self.timeline:
                self.current_time_s = max(0.0, min(self.timeline.duration_s, target_s))
                sample = self.timeline.sample_at(self.current_time_s)
                self._send_telemetry(sample)

    def set_speed(self, speed: float) -> None:
        with self._lock:
            self.playback_speed = max(0.1, min(20.0, speed))

    def set_loop(self, enabled: bool) -> None:
        with self._lock:
            self.loop_enabled = bool(enabled)

    def set_freeze_on_pause(self, enabled: bool) -> None:
        with self._lock:
            self.freeze_on_pause = bool(enabled)

    def get_status(self) -> Dict[str, Any]:
        """Returns snapshot of current player status, live signals, and stats."""
        with self._lock:
            duration = self.timeline.duration_s if self.timeline else 0.0
            cur_time = self.current_time_s
            filename = self.timeline.filename if self.timeline else ""
            frame_count = self.timeline.frame_count if self.timeline else 0

            # Current sample
            if self.timeline and duration > 0:
                sample = self.timeline.sample_at(cur_time)
            else:
                sample = {
                    "speed_freq": 0.0, "rpm_freq": 0.0, "coolant_duty": 20.0,
                    "fuel_ohm": 270.0, "fuel_step": 19, "telltales_mask": MASK_STANDBY,
                    "disp_kph": 0.0, "disp_mph": 0.0, "disp_rpm": 0,
                    "disp_cool_degc": 70.0, "disp_fuel_pct": 100.0,
                    "gear": 0, "voltage_v": 12.0, "is_debug_source": False
                }

            return {
                "state": self.state,
                "filename": filename,
                "frame_count": frame_count,
                "current_time_s": round(cur_time, 2),
                "duration_s": duration,
                "playback_speed": self.playback_speed,
                "loop_enabled": self.loop_enabled,
                "freeze_on_pause": self.freeze_on_pause,
                "target_host": self.target_host,
                "target_port": self.target_port,
                "packets_sent": self.packets_sent,
                "send_rate_hz": round(self.send_rate_hz, 1),
                "last_packet_hex": self.last_packet_hex,
                "last_packet_fields": self.last_packet_fields,
                "last_error": self.last_error,
                "telemetry": sample,
            }

    def get_traces(self) -> Dict[str, Any]:
        """Returns time-series traces for plotting Speed and RPM."""
        with self._lock:
            if self.timeline:
                return self.timeline.get_traces()
            return {"times": [], "speeds": [], "rpms": [], "duration_s": 0.0}

    def _resolve_endpoint(self) -> Optional[Tuple[str, int]]:
        """Resolves target host to IP address with caching."""
        if self._resolved_addr:
            return self._resolved_addr
        try:
            ip = socket.gethostbyname(self.target_host)
            self._resolved_addr = (ip, self.target_port)
            return self._resolved_addr
        except socket.gaierror as ex:
            self.last_error = f"Cannot resolve {self.target_host}: {ex}"
            return None

    def _send_standby_packet(self) -> None:
        """Sends the safe standby packet (0xD940, 0 speed, 0 RPM)."""
        standby_sample = {
            "speed_freq": 0.0,
            "rpm_freq": 0.0,
            "coolant_duty": 7.84,  # ~70 degC
            "fuel_ohm": 270.0,     # Full tank
            "telltales_mask": MASK_STANDBY,
        }
        self._send_telemetry(standby_sample)

    def _send_telemetry(self, sample: Dict[str, Any]) -> None:
        """Packs and sends a telemetry packet over UDP."""
        dest = self._resolve_endpoint()
        if not dest:
            return

        packet, checksum = pack_udp_packet(
            sample["telltales_mask"],
            sample["speed_freq"],
            sample["rpm_freq"],
            sample["coolant_duty"],
            sample["fuel_ohm"],
        )

        try:
            self._sock.sendto(packet, dest)
            self.packets_sent += 1
            self._packets_in_period += 1
            self.last_packet_hex = " ".join(f"{b:02X}" for b in packet)
            self.last_packet_fields = {
                "magic": "0xAA 0x55",
                "telltales_mask": f"0x{sample['telltales_mask']:04X}",
                "speed_freq_x10": int(round(sample["speed_freq"] * 10.0)),
                "rpm_freq_x10": int(round(sample["rpm_freq"] * 10.0)),
                "coolant_duty_x100": int(round(sample["coolant_duty"] * 100.0)),
                "fuel_ohm_x10": int(round(sample["fuel_ohm"] * 10.0)),
                "checksum": f"0x{checksum:04X}",
            }
        except OSError as ex:
            self.last_error = f"UDP send error: {ex}"

    def _worker_loop(self) -> None:
        """Fixed 50 Hz streaming loop with precise timing synchronization."""
        last_tick = time.perf_counter()

        while not self._stop_event.is_set():
            now = time.perf_counter()
            dt = now - last_tick
            last_tick = now

            with self._lock:
                # Update send rate every 500 ms
                if now - self._last_rate_calc_time >= 0.5:
                    period = now - self._last_rate_calc_time
                    self.send_rate_hz = self._packets_in_period / period
                    self._packets_in_period = 0
                    self._last_rate_calc_time = now

                if self.state == "PLAYING" and self.timeline:
                    # Advance playback time
                    self.current_time_s += dt * self.playback_speed

                    if self.current_time_s >= self.timeline.duration_s:
                        if self.loop_enabled:
                            self.current_time_s = 0.0
                        else:
                            self.current_time_s = self.timeline.duration_s
                            self.state = "STOPPED"
                            self._send_standby_packet()

                    if self.state == "PLAYING":
                        sample = self.timeline.sample_at(self.current_time_s)
                        self._send_telemetry(sample)

            # Sleep remainder of dispatch interval
            elapsed = time.perf_counter() - now
            sleep_time = self.dispatch_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def close(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self._sock.close()
        except OSError:
            pass


# Global streamer instance
GLOBAL_STREAMER: Optional[PlaybackStreamer] = None
GLOBAL_DBC: Optional[DbcDatabase] = None
INITIAL_LOG: Optional[Path] = None


class StreamerHandler(BaseAppHandler):
    """HTTP Request Handler for the Replayer & UDP Streamer Dashboard."""

    def do_GET(self) -> None:
        path, _ = self.parse_query()

        if path.startswith("/static/"):
            if self.serve_static(path):
                return
            self.send_error(404, f"Static asset not found: {path}")
            return

        try:
            if path in ("/", "/index.html"):
                template_path = SCRIPT_DIR / "web" / "templates" / "streamer.html"
                if not template_path.is_file():
                    self.send_error(404, "Template streamer.html not found")
                    return
                html = template_path.read_text(encoding="utf-8")
                self.send_html(html)

            elif path == "/favicon.ico":
                svg_icon = (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                    '<circle cx="16" cy="16" r="14" fill="#0b0e14" stroke="#00f0ff" stroke-width="2"/>'
                    '<polygon points="12,9 23,16 12,23" fill="#00ff66"/>'
                    '</svg>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(svg_icon)))
                self.end_headers()
                self.wfile.write(svg_icon)

            elif path == "/api/logs":
                bin_files = find_bin_files(SCRIPT_DIR)
                logs_info = []
                for p in bin_files:
                    logs_info.append({
                        "filename": p.name,
                        "size": p.stat().st_size,
                        "mtime": p.stat().st_mtime,
                        "is_initial": bool(INITIAL_LOG and INITIAL_LOG.name == p.name),
                    })
                self.send_json(logs_info)

            elif path == "/api/status":
                if GLOBAL_STREAMER:
                    status = GLOBAL_STREAMER.get_status()
                    self.send_json(status)
                else:
                    self.send_json({"error": "Streamer not initialized"}, status=500)

            elif path == "/api/traces":
                if GLOBAL_STREAMER:
                    self.send_json(GLOBAL_STREAMER.get_traces())
                else:
                    self.send_json({"times": [], "speeds": [], "rpms": [], "duration_s": 0.0})

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_error(500, f"Internal Server Error: {str(ex)}")

    def do_POST(self) -> None:
        path, _ = self.parse_query()

        if path != "/api/control":
            self.send_error(404, "Not Found")
            return

        try:
            body = self.read_json_body()
            action = body.get("action", "")

            if not GLOBAL_STREAMER:
                self.send_json({"error": "Streamer not ready"}, status=500)
                return

            if action == "play":
                GLOBAL_STREAMER.play()
            elif action == "pause":
                GLOBAL_STREAMER.pause()
            elif action == "stop":
                GLOBAL_STREAMER.stop()
            elif action == "seek":
                target_s = float(body.get("target_s", 0.0))
                GLOBAL_STREAMER.seek(target_s)
            elif action == "set_speed":
                speed = float(body.get("speed", 1.0))
                GLOBAL_STREAMER.set_speed(speed)
            elif action == "set_loop":
                enabled = bool(body.get("loop", False))
                GLOBAL_STREAMER.set_loop(enabled)
            elif action == "set_freeze":
                enabled = bool(body.get("freeze", True))
                GLOBAL_STREAMER.set_freeze_on_pause(enabled)
            elif action == "set_target":
                host = body.get("host", DEFAULT_TARGET_HOST)
                port = int(body.get("port", DEFAULT_TARGET_PORT))
                GLOBAL_STREAMER.set_target(host, port)
            elif action == "load":
                filename = body.get("filename", "")
                p = SCRIPT_DIR / filename
                if not p.is_file():
                    p = Path(filename)
                if not p.is_file():
                    self.send_json({"error": f"File not found: {filename}"}, status=404)
                    return
                ok = GLOBAL_STREAMER.load_log(p, GLOBAL_DBC)
                if not ok:
                    self.send_json({"error": GLOBAL_STREAMER.last_error}, status=500)
                    return
            else:
                self.send_json({"error": f"Unknown action: {action}"}, status=400)
                return

            self.send_json(GLOBAL_STREAMER.get_status())

        except Exception as ex:
            self.send_json({"error": f"Control command failed: {str(ex)}"}, status=500)


def main():
    parser = argparse.ArgumentParser(description="MiniGauge CAN Log Replayer & UDP Streamer to binocle-emulator")
    parser.add_argument("log_file", nargs="?", help="Specific .bin CAN log file to load initially")
    parser.add_argument("--dbc", "-d", help="Path to DBC database file (default: binocan.dbc)")
    parser.add_argument("--target-host", "-t", default=DEFAULT_TARGET_HOST, help=f"Target UDP host (default: {DEFAULT_TARGET_HOST})")
    parser.add_argument("--target-port", "-tp", type=int, default=DEFAULT_TARGET_PORT, help=f"Target UDP port (default: {DEFAULT_TARGET_PORT})")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_HTTP_PORT, help=f"Web server HTTP port (default: {DEFAULT_HTTP_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose HTTP request logging")
    args = parser.parse_args()

    global GLOBAL_STREAMER, GLOBAL_DBC, INITIAL_LOG

    # Load DBC
    dbc_path = Path(args.dbc) if args.dbc else (SCRIPT_DIR / "binocan.dbc")
    try:
        GLOBAL_DBC = get_dbc(dbc_path)
        print(f"[+] Loaded CAN DBC: {dbc_path.name} ({len(GLOBAL_DBC.messages)} messages)")
    except Exception as ex:
        print(f"[-] Error loading DBC {dbc_path}: {ex}")
        sys.exit(1)

    # Initialize streamer
    GLOBAL_STREAMER = PlaybackStreamer(target_host=args.target_host, target_port=args.target_port)

    # Locate initial log file
    if args.log_file:
        p = Path(args.log_file)
        if p.is_file():
            INITIAL_LOG = p.resolve()
        elif (SCRIPT_DIR / args.log_file).is_file():
            INITIAL_LOG = (SCRIPT_DIR / args.log_file).resolve()
        else:
            print(f"[-] Warning: Specified log file '{args.log_file}' was not found.")

    if not INITIAL_LOG:
        bin_files = find_bin_files(SCRIPT_DIR)
        if bin_files:
            INITIAL_LOG = bin_files[0]

    if INITIAL_LOG and INITIAL_LOG.is_file():
        print(f"[+] Indexing initial log: {INITIAL_LOG.name}...")
        GLOBAL_STREAMER.load_log(INITIAL_LOG, GLOBAL_DBC)
        print(f"[+] Ready to stream: {INITIAL_LOG.name} ({GLOBAL_STREAMER.timeline.duration_s:.2f}s, {GLOBAL_STREAMER.timeline.frame_count} frames)")

    StreamerHandler.verbose_logging = args.verbose

    try:
        start_server(
            StreamerHandler,
            port=args.port,
            open_browser=not args.no_browser,
            server_name="MiniGauge CAN Log Streamer",
        )
    finally:
        if GLOBAL_STREAMER:
            GLOBAL_STREAMER.close()


if __name__ == "__main__":
    main()
