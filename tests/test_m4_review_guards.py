import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bkitevsim.core import Event
from drivethru.config.experiment_config import NetworkExpConfig
from drivethru.config.simulation_config import DriveThruParams
from drivethru.core.state import CarRecord
from drivethru.experiments.run_hand_trace import verify_and_export_hand_trace
from drivethru.experiments.run_single import attach_global_monotonic_guard, run_drivethru_network
from drivethru.experiments.runner import (
    check_precision_criteria,
    check_precision_details,
    compute_config_fingerprint,
    run_batch_with_checkpoint,
)
from drivethru.metrics.stats_utils import compute_ci95, evaluate_sla_status
from drivethru.models.monitor import MonitorLP
from drivethru.models.station import StationLP


class TestM4ReviewGuards(unittest.TestCase):
    def test_1_no_shadowing_stdlib_statistics(self):
        """Điểm 6: Không tồn tại drivethru/metrics/statistics.py gây trùng module chuẩn."""
        self.assertFalse(Path("drivethru/metrics/statistics.py").exists())

    def test_2_sla_three_state_pass_fail_boundary(self):
        """Điểm 2: Quy tắc 3 trạng thái PASS / FAIL / BOUNDARY theo §2.6."""
        self.assertEqual(
            evaluate_sla_status({"ci_low": 5.1, "ci_high": 5.5}, {"ci_low": 0.005, "ci_high": 0.010}),
            "PASS",
        )
        self.assertEqual(
            evaluate_sla_status({"ci_low": 8.1, "ci_high": 8.5}, {"ci_low": 0.005, "ci_high": 0.010}),
            "FAIL",
        )
        self.assertEqual(
            evaluate_sla_status({"ci_low": 7.8, "ci_high": 8.2}, {"ci_low": 0.005, "ci_high": 0.010}),
            "BOUNDARY",
        )
        self.assertEqual(
            evaluate_sla_status({"ci_low": 5.1, "ci_high": 5.5}, {"ci_low": 0.048, "ci_high": 0.052}),
            "BOUNDARY",
        )

    def test_3_runtime_monotonic_time_guard(self):
        """Điểm 5b: Chốt chặn lúc chạy ném RuntimeError ngay khi timestamp đi lùi."""
        stn = StationLP(lp_id=1, station_idx=1, c=1, K=10, t_warmup=0.0, t_end=100.0)
        stn.handle_event(Event(10.0, 0, 1, "WARMUP_END"))
        stn.set_local_virt_time(9.0)
        with self.assertRaises(RuntimeError):
            stn.handle_event(Event(9.0, 0, 1, "WARMUP_END"))

        mon = MonitorLP(lp_id=5, t_warmup=0.0, t_end=100.0)
        mon.handle_event(Event(5.0, 0, 5, "WARMUP_END"))
        mon.set_local_virt_time(4.0)
        with self.assertRaises(RuntimeError):
            mon.handle_event(Event(4.0, 0, 5, "WARMUP_END"))

    def test_4_checkpoint_hash_version_backup_and_ulwt_precision(self):
        """Kiểm chứng đổi t_end -> tự tạo .bak + chạy mới; đổi code_version -> đổi hash; kiểm đủ U,L,W,T,Pb."""
        p = DriveThruParams(lam=0.6, c2=2, K1=6, t_warmup=200.0, t_end=2000.0)
        self.assertNotEqual(
            compute_config_fingerprint(p, code_version="v2.1"),
            compute_config_fingerprint(p, code_version="v2.2"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "raw.csv"
            bak = Path(tmp) / "raw.csv.bak"
            cfg_2k = NetworkExpConfig("TEST_HASH", ("ExpC",), "Peak", p, base_replications=2, max_replications=2)
            rows_2k = run_batch_with_checkpoint([cfg_2k], ckpt, max_workers=2, auto_expand_ci=False)["TEST_HASH"]
            ev_2k = rows_2k[0]["events_processed"]
            self.assertFalse(bak.exists())

            cfg_4k = NetworkExpConfig(
                "TEST_HASH", ("ExpC",), "Peak",
                DriveThruParams(lam=0.6, c2=2, K1=6, t_warmup=200.0, t_end=4000.0),
                base_replications=2, max_replications=2,
            )
            rows_4k = run_batch_with_checkpoint([cfg_4k], ckpt, max_workers=2, auto_expand_ci=False)["TEST_HASH"]
            ev_4k = rows_4k[0]["events_processed"]

            self.assertTrue(bak.exists(), "Chưa sao lưu file checkpoint cũ ra .bak trước khi ghi đè!")
            self.assertGreater(ev_4k, ev_2k * 1.5)
            ok, _t_hw, _pb_hw = check_precision_criteria(rows_4k)
            det = check_precision_details(rows_4k)
            self.assertEqual(ok, det["precision_ok"])
            self.assertIn(det["worst_rel_metric"], ("T", "U1", "U2", "U3", "U4", "L1", "L2", "L3", "L4", "L_system", "W1", "W2", "W3", "W4"))

    def test_5_global_cross_lp_monotonic_guard(self):
        """Chốt chặn toàn cục bắt được thời gian đi lùi GIỮA hai LP khác nhau (LP1 t=10 -> LP5 t=5)."""
        stn = StationLP(lp_id=1, station_idx=1, c=1, K=10, t_warmup=0.0, t_end=100.0)
        mon = MonitorLP(lp_id=5, t_warmup=0.0, t_end=100.0)
        attach_global_monotonic_guard((stn, mon))
        stn.handle_event(Event(10.0, 0, 1, "WARMUP_END"))
        with self.assertRaises(RuntimeError):
            mon.handle_event(Event(5.0, 0, 5, "WARMUP_END"))

    def test_6_unmatched_food_ready_at_blocking_order_raises(self):
        """Order ở chế độ blocking nhận FOOD_READY của xe không tồn tại phải tăng đếm và ném RuntimeError."""
        order = StationLP(lp_id=1, station_idx=1, c=2, K=6, blocking_order=True, t_warmup=0.0, t_end=100.0)
        ghost_car = CarRecord(car_id=999, t_arrive=1.0)
        with self.assertRaises(RuntimeError):
            order.handle_event(Event(5.0, 3, 1, "FOOD_READY", payload=ghost_car))
        self.assertEqual(order.unmatched_food_ready_count, 1)

    def test_7_boundary_peak_triggers_auto_expansion(self):
        """Xác minh nhánh tự mở rộng seed kích hoạt thật khi cấu hình Peak Exp C có sla_status == BOUNDARY."""
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "bnd.csv"
            cfg = NetworkExpConfig(
                "TEST_BND", ("ExpC",), "Peak",
                DriveThruParams(lam=0.6, c2=2, K1=6, t_warmup=100.0, t_end=400.0),
                base_replications=2, max_replications=4,
            )
            fake_det = {
                "precision_ok": True,
                "t_rel_hw_pct": 1.0,
                "pb_hw_abs": 0.001,
                "worst_rel_metric": "T",
                "worst_rel_hw_pct": 1.0,
                "failed_metrics": [],
                "sla_status": "BOUNDARY",
            }
            with patch("drivethru.experiments.runner.check_precision_details", return_value=fake_det):
                rows = run_batch_with_checkpoint([cfg], ckpt, max_workers=2, auto_expand_ci=True)["TEST_BND"]
            self.assertEqual(len(rows), 4, "Nhánh BOUNDARY chưa tự mở rộng số seed từ 2 lên 4!")



    def test_8_hand_trace_10_cars_and_event_log(self):
        """Mục 1.9 & 1.8a: Kiểm chứng trace tay ~10 xe (có DROP & chờ đồ) + event_log đơn điệu."""
        with tempfile.TemporaryDirectory() as tmp:
            info = verify_and_export_hand_trace(Path(tmp) / "trace.md")
            self.assertGreaterEqual(info["n_generated"], 9)
            self.assertGreater(info["n_events"], 30)



    def test_9_pe7_deterministic_model_exact_hand_formula(self):
        """pe7 Verification (Deterministic model): Đầu vào cố định -> khớp chính xác công thức tay (<1e-9)."""
        # Interarrival cố định = 1/0.2 = 5.0p > mọi thời gian phục vụ (1.5, 1.25, 1.5, 1.0) -> không xếp hàng
        params = DriveThruParams(
            lam=0.2, c1=2, K1=8, mean_s1=1.5,
            c2=2, mean_s2=1.25, c3=2, mean_s3=1.5, c4=2, mean_s4=1.0,
            t_warmup=50.0, t_end=500.0, blocking_order=False,
        )
        res = run_drivethru_network(params, seed=1, deterministic=True, verify_invariants=True)
        # W_f = max(0, s3 - s2) = 1.5 - 1.25 = 0.25; T = s1 + max(s2, s3) + s4 = 1.5 + 1.5 + 1.0 = 4.0
        self.assertAlmostEqual(res["W_f"], 0.25, places=9)
        self.assertAlmostEqual(res["P_f"], 1.0, places=9)
        self.assertAlmostEqual(res["T"], 4.0, places=9)
        self.assertAlmostEqual(res["P_b"], 0.0, places=9)

    def test_10_pe7_continuity_test_small_lambda_perturbation(self):
        """pe7 Verification (Continuity test): Đổi nhẹ λ (0.60 -> 0.61) -> T và U2 biến thiên mượt, không nhảy cóc."""
        p60 = DriveThruParams(lam=0.60, c2=2, K1=8, t_warmup=500.0, t_end=3000.0)
        p61 = DriveThruParams(lam=0.61, c2=2, K1=8, t_warmup=500.0, t_end=3000.0)
        r60 = [run_drivethru_network(p60, seed=s) for s in range(1, 6)]
        r61 = [run_drivethru_network(p61, seed=s) for s in range(1, 6)]

        t60 = sum(r["T"] for r in r60) / len(r60)
        t61 = sum(r["T"] for r in r61) / len(r61)
        u60 = sum(r["U2"] for r in r60) / len(r60)
        u61 = sum(r["U2"] for r in r61) / len(r61)

        rel_dt = abs(t61 - t60) / t60
        rel_du = (u61 - u60) / u60
        self.assertLess(rel_dt, 0.08, f"T nhảy bất thường khi đổi nhẹ λ 0.60->0.61: {rel_dt:.2%}")
        self.assertGreater(rel_du, 0.0, "U2 phải tăng nhẹ khi λ tăng từ 0.60 lên 0.61")
        self.assertLess(rel_du, 0.06, f"U2 nhảy bất thường: {rel_du:.2%}")

    def test_11_pe7_seed_independence_two_disjoint_groups(self):
        """pe7 Verification (Seed independence): Hai nhóm seed rời nhau (1..10 vs 11..20) cho kết quả tương đương."""
        params = DriveThruParams(lam=0.6, c2=2, K1=6, t_warmup=500.0, t_end=3000.0)
        grp_a = [run_drivethru_network(params, seed=s)["T"] for s in range(1, 11)]
        grp_b = [run_drivethru_network(params, seed=s)["T"] for s in range(11, 21)]
        ci_a = compute_ci95(grp_a)
        ci_b = compute_ci95(grp_b)

        diff = abs(ci_a["mean"] - ci_b["mean"])
        se_diff = math.sqrt((ci_a["std"] ** 2) / len(grp_a) + (ci_b["std"] ** 2) / len(grp_b))
        self.assertLess(diff / ci_a["mean"], 0.05, f"Chênh lệch 2 nhóm seed > 5%: {diff / ci_a['mean']:.2%}")
        self.assertLessEqual(diff, 2.88 * se_diff, f"Hai nhóm seed khác biệt đáng kể: diff={diff:.4f}, SE={se_diff:.4f}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
