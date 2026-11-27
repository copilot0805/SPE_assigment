import unittest
from typing import List, Tuple

from bkitevsim.core import Event, BkSysLogicalProcess, Simulation, SimulationOptions
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import CarRecord
from drivethru.experiments.run_single import run_drivethru_network
from drivethru.metrics.analytical import analytical_fork_join_network
from drivethru.models.monitor import MonitorLP
from drivethru.models.pickup import PickupLP


class ScriptedJoinInjectorLP(BkSysLogicalProcess):
    """LP phát kịch bản định sẵn để kiểm thử 3 trường hợp bảng Join của PickupLP."""

    def __init__(self, lp_id: int, events_spec: List[Tuple[float, str, CarRecord]], target_lp_id: int = LPID.PICKUP):
        super().__init__(lp_id)
        self.events_spec = events_spec
        self.target_lp_id = target_lp_id

    def initialize(self) -> None:
        for ts, ev_type, payload in self.events_spec:
            self.send_event(Event(ts, self.lp_id, self.target_lp_id, ev_type, payload=payload))

    def handle_event(self, event: Event) -> None:
        self.local_virt_time = event.timestamp


class TestM3NetworkGate(unittest.TestCase):
    def _run_join_unit_case(self, t_payment: float, t_food: float, s4: float = 1.0):
        t_end = 50.0
        options = SimulationOptions(
            end_time=t_end,
            dispatcher="sequential",
            bucket_width=safe_bucket_width(t_end),
            log_level="ERROR",
        )
        sim = Simulation(
            options,
            models={"Injector": ScriptedJoinInjectorLP, "Pickup": PickupLP, "Monitor": MonitorLP},
        )
        car = CarRecord(car_id=1, t_arrive=1.0, service_times={4: s4})
        events_spec = [
            (t_payment, EventType.TRANSFER.value, car),
            (t_food, EventType.FOOD_READY.value, car.copy_for_branch()),
        ]
        sim.create_lp(0, "Injector", events_spec=events_spec, target_lp_id=LPID.PICKUP)
        pickup = sim.create_lp(
            LPID.PICKUP, "Pickup", station_idx=4, c=2, mean_service_time=s4,
            out_targets=[(LPID.MONITOR, EventType.DEPARTURE.value)],
            monitor_lp_id=LPID.MONITOR, t_warmup=0.0, t_end=t_end,
        )
        mon = sim.create_lp(LPID.MONITOR, "Monitor", t_warmup=0.0, t_end=t_end)
        sim.run()
        return car, pickup.get_statistics(), mon.get_statistics()

    def test_1_join_car_arrives_before_food(self):
        """Ca Join 1: Xe đến trước (t_p=5.0), đồ xong sau (t_f=8.0) -> W_f=3.0, P_f=1.0."""
        car, p_stats, m_stats = self._run_join_unit_case(t_payment=5.0, t_food=8.0, s4=1.5)
        self.assertAlmostEqual(car.food_wait_time, 3.0, places=9)
        self.assertAlmostEqual(p_stats["W_f"], 3.0, places=9)
        self.assertAlmostEqual(p_stats["P_f"], 1.0, places=9)
        self.assertAlmostEqual(p_stats["L_f"] * 50.0, 3.0, places=9)
        self.assertEqual(p_stats["join_table_entries"], 0)
        self.assertEqual(m_stats["total_completed"], 1)
        self.assertAlmostEqual(m_stats["T"], (8.0 + 1.5) - 1.0, places=9)

    def test_2_join_food_ready_before_car(self):
        """Ca Join 2: Đồ xong trước (t_f=4.0), xe đến sau (t_p=7.0) -> W_f=0.0, P_f=0.0, L_f=0.0."""
        car, p_stats, m_stats = self._run_join_unit_case(t_payment=7.0, t_food=4.0, s4=1.5)
        self.assertAlmostEqual(car.food_wait_time, 0.0, places=9)
        self.assertAlmostEqual(p_stats["W_f"], 0.0, places=9)
        self.assertAlmostEqual(p_stats["P_f"], 0.0, places=9)
        self.assertAlmostEqual(p_stats["L_f"], 0.0, places=9)
        self.assertEqual(p_stats["join_table_entries"], 0)
        self.assertAlmostEqual(m_stats["T"], (7.0 + 1.5) - 1.0, places=9)

    def test_3_join_simultaneous_timestamp(self):
        """Ca Join 3: Xe và đồ đến cùng thời điểm (t_p=t_f=6.0) -> W_f=0.0, P_f=0.0."""
        car, p_stats, m_stats = self._run_join_unit_case(t_payment=6.0, t_food=6.0, s4=2.0)
        self.assertAlmostEqual(car.food_wait_time, 0.0, places=9)
        self.assertAlmostEqual(p_stats["W_f"], 0.0, places=9)
        self.assertAlmostEqual(p_stats["P_f"], 0.0, places=9)
        self.assertAlmostEqual(p_stats["L_f"], 0.0, places=9)
        self.assertEqual(p_stats["join_table_entries"], 0)
        self.assertAlmostEqual(m_stats["T"], (6.0 + 2.0) - 1.0, places=9)

    def test_4_zero_delay_fork_order_invariance(self):
        """Kiểm chứng đảo thứ tự gửi event trễ 0 (TRANSFER vs ORDER_PLACED) không làm đổi kết quả."""
        params = DriveThruParams(lam=0.6, c2=2, K1=8, t_warmup=2000.0, t_end=10000.0)
        res_normal = run_drivethru_network(params, seed=7, reverse_fork_order=False)
        res_reversed = run_drivethru_network(params, seed=7, reverse_fork_order=True)

        for key in ("T", "P95_T", "P_b", "W_f", "P_f", "L_f", "L_system", "U1", "U2", "U3", "U4", "X"):
            self.assertAlmostEqual(
                res_normal[key], res_reversed[key], places=10,
                msg=f"Kết quả bị lệch ở chỉ số {key} khi đảo thứ tự gửi event trễ 0!"
            )
        self.assertEqual(res_normal["total_completed"], res_reversed["total_completed"])
        self.assertEqual(res_normal["total_dropped"], res_reversed["total_dropped"])

    def test_5_network_flow_balance_throughput_and_littles_law(self):
        """Kiểm chứng cân bằng dòng toàn mạng, cân bằng thông lượng và Little's Law L_system = L1+L2+Lf+L4 <= 1%."""
        params = DriveThruParams(lam=0.6, c2=2, K1=4, t_warmup=2000.0, t_end=10000.0)
        res = run_drivethru_network(params, seed=3)

        self.assertTrue(res["flow_balance_ok"])
        # Định luật Little cho từng trạm và toàn hệ thống (L_system = L1 + L2 + L_f + L4) đều <= 1%
        for key in ("little_err_s1", "little_err_s2", "little_err_s3", "little_err_s4", "little_err_sys"):
            self.assertLessEqual(res[key], 0.01, f"{key} vượt ngưỡng 1%: {res[key]:.4%}")

        # Cân bằng thông lượng các trạm sau Order: X2 ~ X3 ~ X4 ~ X1
        x1 = res["X1"]
        for x_other in (res["X2"], res["X3"], res["X4"], res["X"]):
            self.assertLessEqual(abs(x_other - x1) / x1, 0.01)

    def test_6_degeneracy_no_kitchen_and_fork_join_approximation(self):
        """Kiểm chứng (a) Thu gọn 1/mu3=0.01 khớp Jackson <5% và (b) Cơ sở K1=30 khớp xấp xỉ Fork-Join <5%."""
        # (a) Kiểm tra thu gọn: 1/mu3 = 0.01 phút -> W_f ~ 0 và T khớp W1 + W2 + W4
        p_deg = DriveThruParams(lam=0.6, c2=2, K1=30, mean_s3=0.01, t_warmup=2000.0, t_end=10000.0)
        approx_deg = analytical_fork_join_network(
            p_deg.lam, p_deg.c1, p_deg.K1, p_deg.mean_s1,
            p_deg.c2, p_deg.mean_s2, p_deg.c3, p_deg.mean_s3, p_deg.c4, p_deg.mean_s4,
        )
        deg_runs = [run_drivethru_network(p_deg, seed=s) for s in range(1, 6)]
        t_deg_mean = sum(r["T"] for r in deg_runs) / len(deg_runs)
        wf_deg_mean = sum(r["W_f"] for r in deg_runs) / len(deg_runs)

        self.assertLess(wf_deg_mean, 0.02)
        err_deg = abs(t_deg_mean - approx_deg["T_jackson_no_kitchen"]) / approx_deg["T_jackson_no_kitchen"]
        self.assertLess(err_deg, 0.05, f"Thu gọn 1/mu3=0.01 lệch Jackson > 5%: {err_deg:.2%}")

        # (b) Mạng cơ sở K1=30, lam=0.6 (Exp B đối chiếu xấp xỉ Fork-Join)
        p_fj = DriveThruParams(lam=0.6, c2=1, K1=30, t_warmup=2000.0, t_end=10000.0)
        approx_fj = analytical_fork_join_network(
            p_fj.lam, p_fj.c1, p_fj.K1, p_fj.mean_s1,
            p_fj.c2, p_fj.mean_s2, p_fj.c3, p_fj.mean_s3, p_fj.c4, p_fj.mean_s4,
        )
        fj_runs = [run_drivethru_network(p_fj, seed=s) for s in range(1, 6)]
        t_fj_mean = sum(r["T"] for r in fj_runs) / len(fj_runs)
        err_fj = abs(t_fj_mean - approx_fj["T_approx"]) / approx_fj["T_approx"]
        self.assertLess(err_fj, 0.05, f"Mạng cơ sở K1=30 lệch xấp xỉ Fork-Join > 5%: {err_fj:.2%}")

    def test_7_two_dispatchers_match_and_blocking_exp_d(self):
        """Kiểm chứng (a) Sequential == DistributedSequential cùng seed và (b) Chế độ Blocking của Exp D."""
        params_nb = DriveThruParams(lam=0.6, c2=2, K1=8, t_warmup=2000.0, t_end=10000.0, blocking_order=False)
        res_seq = run_drivethru_network(params_nb, seed=5, dispatcher="sequential")
        res_dist = run_drivethru_network(params_nb, seed=5, dispatcher="distributed_sequential")

        for key in ("T", "P95_T", "P_b", "W_f", "P_f", "L_system", "U1", "U2", "U3", "U4"):
            self.assertAlmostEqual(
                res_seq[key], res_dist[key], places=10,
                msg=f"Hai dispatcher lệch nhau ở chỉ số {key}!"
            )
        self.assertEqual(res_seq["total_completed"], res_dist["total_completed"])

        # Biến thể Chặn (Exp D): Kitchen gửi FOOD_READY về cả Order lẫn Pickup
        params_blk = DriveThruParams(lam=0.6, c2=2, K1=8, t_warmup=2000.0, t_end=10000.0, blocking_order=True)
        res_blk = run_drivethru_network(params_blk, seed=5, dispatcher="sequential")

        self.assertTrue(res_blk["flow_balance_ok"])
        self.assertEqual(res_blk["n_unfinished_join"], 0)
        self.assertAlmostEqual(res_blk["W_f"], 0.0, places=9)
        self.assertLessEqual(res_blk["little_err_sys"], 0.01)
        # Chế độ chặn làm tăng rõ rệt U1, P_b và T so với không chặn
        self.assertGreater(res_blk["U1"], res_seq["U1"] + 0.20)
        self.assertGreater(res_blk["P_b"], res_seq["P_b"] + 0.02)
        self.assertGreater(res_blk["T"], res_seq["T"] + 1.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
