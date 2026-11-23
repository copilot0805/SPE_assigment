import unittest
from bkitevsim.core import Simulation, SimulationOptions
from drivethru.config.simulation_config import safe_bucket_width
from drivethru.metrics.analytical import (
    analytical_mm1,
    analytical_mm1k,
    analytical_mmc,
    analytical_mmck,
    analytical_mminf,
    analytical_mmnn,
)
from drivethru.metrics.stats_utils import check_littles_law
from drivethru.models.car_source import CarSourceLP
from drivethru.models.monitor import MonitorLP
from drivethru.models.station import StationLP


class TestM2StationGate(unittest.TestCase):
    def test_station_monotonic_time_and_flow_balance(self):
        """Kiểm chứng (1) Thời gian không giảm, (2) Ràng buộc c và K, (3) Cân bằng dòng, (4) Định luật Little."""
        t_warmup = 2000.0
        t_end = 10000.0
        c, K = 2, 5

        options = SimulationOptions(
            end_time=t_end,
            dispatcher="sequential",
            bucket_width=safe_bucket_width(t_end),
            log_level="ERROR",
        )
        sim = Simulation(
            options,
            models={"Source": CarSourceLP, "Station": StationLP, "Monitor": MonitorLP},
        )

        src = sim.create_lp(
            0, "Source", lam=0.8, mean_services={1: 1.5},
            target_lp_id=1, t_warmup=t_warmup, t_end=t_end, seed=1
        )
        stn = sim.create_lp(
            1, "Station", station_idx=1, c=c, K=K, mean_service_time=1.5,
            out_targets=[(5, "DEPARTURE")], monitor_lp_id=5,
            t_warmup=t_warmup, t_end=t_end, record_timestamps=True
        )
        mon = sim.create_lp(5, "Monitor", t_warmup=t_warmup, t_end=t_end)

        sim.run()

        ts = stn.event_timestamps
        self.assertGreater(len(ts), 1000)
        for i in range(1, len(ts)):
            self.assertGreaterEqual(ts[i], ts[i - 1])

        n_unfinished = stn.n_unfinished
        self.assertLessEqual(stn.state.busy, c)
        self.assertLessEqual(n_unfinished, K)
        self.assertEqual(src.total_generated, stn.state.total_arrived)
        self.assertEqual(
            stn.state.total_arrived,
            mon.total_completed + mon.total_dropped + n_unfinished,
        )

        stats = stn.get_statistics()
        little = check_littles_law(stats["L"], stats["X"], stats["W"], tol=0.01)
        self.assertEqual(little["passed"], 1.0)

    def test_analytical_formulas_six_models_consistency(self):
        """Kiểm chứng tính nhất quán toán học và Định luật Little trên công thức giải tích của cả 6 mô hình đơn."""
        cases = [
            analytical_mm1(lam=0.8, mu=1.0),
            analytical_mm1k(lam=0.8, mu=1.0, K=4),
            analytical_mminf(lam=2.0, mu=1.0),
            analytical_mmnn(lam=2.4, mu=1.0, n=3),
            analytical_mmc(lam=1.6, mu=1.0, c=2),
            analytical_mmck(lam=1.6, mu=1.0, c=2, K=5),
        ]
        for res in cases:
            self.assertAlmostEqual(res["L"], res["X"] * res["W"], places=10)
            self.assertAlmostEqual(res["L_q"], res["X"] * res["W_q"], places=10)
            self.assertAlmostEqual(res["W"], res["W_q"] + 1.0, places=10)

        mm1k_ref = analytical_mm1k(0.8, 1.0, 4)
        mmck_c1 = analytical_mmck(0.8, 1.0, 1, 4)
        for k in mm1k_ref:
            self.assertAlmostEqual(mm1k_ref[k], mmck_c1[k], places=10)

        mmnn_ref = analytical_mmnn(2.4, 1.0, 3)
        mmck_cn = analytical_mmck(2.4, 1.0, 3, 3)
        for k in mmnn_ref:
            self.assertAlmostEqual(mmnn_ref[k], mmck_cn[k], places=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
