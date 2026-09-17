import unittest
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECODER_DIR = REPO_ROOT / "decoder"
if str(DECODER_DIR) not in sys.path:
    sys.path.insert(0, str(DECODER_DIR))

from tuner import extract_algo_data, get_dbc


class TestGearAlgorithms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_dbc(DECODER_DIR / "binocan.dbc")
        cls.bin_file = DECODER_DIR / "20260906_log_172515.bin"
        cls.data = extract_algo_data(cls.bin_file, cls.db)
        cls.g = cls.data["gear"]
        cls.n = len(cls.g["times"])

    def _simulate(self, rpm_filter_enabled=False, rpm_filter_type='EMA', rpm_filter_tau=0.1, latch_enabled=False, latch_hold_ms=200):
        n = self.n
        g = self.g

        # 1. RPM pre-filter
        eff_rf = [0.0] * n
        if rpm_filter_enabled:
            if rpm_filter_type == 'EMA':
                tau = max(0.01, rpm_filter_tau)
                ema_rpm = g["rpm_freq"][0] if n > 0 else 0.0
                eff_rf[0] = ema_rpm
                for i in range(1, n):
                    dt = max(0.001, min(1.0, g["times"][i] - g["times"][i-1]))
                    alpha = dt / (tau + dt)
                    ema_rpm = alpha * g["rpm_freq"][i] + (1.0 - alpha) * ema_rpm
                    eff_rf[i] = ema_rpm
            else: # SMA
                win_sec = max(0.02, rpm_filter_tau)
                curr_sum = 0.0
                start_idx = 0
                for i in range(n):
                    curr_sum += g["rpm_freq"][i]
                    while start_idx < i and (g["times"][i] - g["times"][start_idx]) > win_sec:
                        curr_sum -= g["rpm_freq"][start_idx]
                        start_idx += 1
                    count = i - start_idx + 1
                    eff_rf[i] = curr_sum / count if count > 0 else g["rpm_freq"][i]
        else:
            eff_rf = list(g["rpm_freq"])

        # 2. Ratio & Gating
        r_nominal = [1.82, 2.73, 3.76, 4.54, 5.25]
        min_speed = 5.0
        min_rpm = 25.0
        stab_gate = 0.05
        alpha = 0.15
        tol = 8.0

        current_ema = None
        prev_raw = None
        cand_gears = [0] * n
        final_gears = [0] * n

        latched_gear = 0
        pending_gear = 0
        pending_start_t = 0.0

        for i in range(n):
            t = g["times"][i]
            sf = g["speed_freq"][i]
            rf = eff_rf[i]

            speed_valid = (sf >= min_speed)
            rpm_valid = (rf >= min_rpm)
            ratio = (sf / rf) if (rpm_valid and sf > 0) else None

            stable = False
            if ratio is not None and prev_raw is not None:
                stable = (abs(ratio - prev_raw) <= stab_gate)
            elif ratio is not None:
                stable = True
            prev_raw = ratio

            is_active = (speed_valid and rpm_valid and stable and ratio is not None)
            if is_active:
                if current_ema is None:
                    current_ema = ratio
                else:
                    current_ema = alpha * ratio + (1.0 - alpha) * current_ema
            else:
                current_ema = None

            cand_g = 0
            if current_ema is not None:
                for gi, nom in enumerate(r_nominal):
                    span = nom * (tol / 100.0)
                    if abs(current_ema - nom) <= span:
                        cand_g = gi + 1
                        break
            cand_gears[i] = cand_g

            # Output latch
            if not latch_enabled:
                final_gears[i] = cand_g
            else:
                if not speed_valid or not rpm_valid:
                    latched_gear = 0
                    pending_gear = 0
                    pending_start_t = t
                    final_gears[i] = 0
                else:
                    if cand_g != pending_gear:
                        pending_gear = cand_g
                        pending_start_t = t
                    elapsed_ms = (t - pending_start_t) * 1000.0
                    if elapsed_ms >= latch_hold_ms:
                        latched_gear = pending_gear
                    final_gears[i] = latched_gear

        transitions = sum(1 for i in range(1, n) if final_gears[i] != final_gears[i-1])
        return {
            "final_gears": final_gears,
            "transitions": transitions
        }

    def test_01_baseline_vs_latched_pipeline(self):
        res_baseline = self._simulate(rpm_filter_enabled=False, latch_enabled=False)
        res_latched = self._simulate(rpm_filter_enabled=True, rpm_filter_type='EMA', rpm_filter_tau=0.1, latch_enabled=True, latch_hold_ms=200)

        self.assertLessEqual(
            res_latched["transitions"],
            res_baseline["transitions"],
            "Latching should reduce transient transitions and chatter"
        )
        print(f"[test_gear_algorithms] ✓ Latching suppressed chatter: {res_baseline['transitions']} -> {res_latched['transitions']} transitions.")


if __name__ == "__main__":
    unittest.main()

