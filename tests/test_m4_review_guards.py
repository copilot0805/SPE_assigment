import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bkitevsim.core import Event
from drivethru.config.experiment_config import NetworkExpConfig
from drivethru.config.simulation_config import DriveThruParams
from drivethru.core.state import CarRecord
from drivethru.experiments.run_hand_trace import verify_and_export_hand_trace
from drivethru.experiments.run_single import attach_global_monotonic_guard
from drivethru.experiments.runner import (
    check_precision_criteria,
    check_precision_details,
    compute_config_fingerprint,
    run_batch_with_checkpoint,
)
from drivethru.metrics.stats_utils import evaluate_sla_status
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
