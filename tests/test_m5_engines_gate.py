import unittest

from bkitevsim.core import Event, Simulation, SimulationOptions
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.engines.base import compute_fidelity_error
from drivethru.engines.coroutine_engine import run_coroutine_engine
from drivethru.engines.multithread_engine import run_multithread_engine
from drivethru.engines.safe_co_base import SafeCoLogicalProcess, check_and_raise_errors
from drivethru.engines.sequential_engine import run_sequential_engine


class TestM5EnginesGate(unittest.TestCase):
    """Cổng kiểm chứng M5: vá Lỗi 3 & 4, và độ khớp < 1e-9 giữa 3 kiến trúc Engine."""

    def test_1_safe_co_fixes_bug3_early_pending_event(self):
        """Kiểm chứng SafeCoLogicalProcess vá Lỗi 3: wait_for() không bỏ sót _pending_events."""

        class EarlyPingLP(SafeCoLogicalProcess):
            def __init__(self, lp_id, t_end=10.0, error_sink=None):
                super().__init__(lp_id=lp_id, t_end=t_end, error_sink=error_sink)
                self.received = None

            async def on_coroutine_run(self):
                self.send_event(Event(1.0, self.lp_id, self.lp_id, "EARLY_PING", payload="OK_B3"))
                await self.wait_until(2.0)
                ev = await self.wait_for("EARLY_PING")
                self.received = ev.payload
                await self.wait_until(self.t_end)

        sink = []
        sim = Simulation(
            SimulationOptions(end_time=10.0, bucket_width=safe_bucket_width(10.0), log_level="ERROR"),
            models={"Early": EarlyPingLP},
        )
        lp = sim.create_lp(0, "Early", t_end=10.0, error_sink=sink)
        sim.run()
        check_and_raise_errors(sink)
        self.assertEqual(lp.received, "OK_B3")

    def test_2_safe_co_fixes_bug4_exception_propagation(self):
        """Kiểm chứng SafeCoLogicalProcess vá Lỗi 4: không nuốt Exception trong handle_event."""

        class BoomLP(SafeCoLogicalProcess):
            def initialize(self):
                self.send_event(Event(1.0, self.lp_id, self.lp_id, "BOOM"))

            def on_event_safe(self, event):
                if event.event_type == "BOOM":
                    raise ValueError("M5_BUG4_SENTINEL")

        sink = []
        sim = Simulation(
            SimulationOptions(end_time=10.0, bucket_width=safe_bucket_width(10.0), log_level="ERROR"),
            models={"Boom": BoomLP},
        )
        sim.create_lp(0, "Boom", t_end=10.0, error_sink=sink)
        sim.run()
        with self.assertRaises(RuntimeError) as ctx:
            check_and_raise_errors(sink)
        self.assertIn("M5_BUG4_SENTINEL", str(ctx.exception))

    def test_3_three_engines_exact_fidelity_non_blocking(self):
        """Cả 3 engine (Sequential, Coroutine+BkSysFuture, OS-MT) khớp < 1e-9 trên Non-blocking."""
        params = DriveThruParams(lam=0.6, c2=2, K1=6, t_warmup=500.0, t_end=2000.0, blocking_order=False)
        seq = run_sequential_engine(params, seed=1, measure_memory=False)
        co = run_coroutine_engine(params, seed=1, measure_memory=False)
        mt = run_multithread_engine(params, seed=1, measure_memory=False)

        for eng in (co, mt):
            fid = compute_fidelity_error(eng.to_dict(), seq.to_dict(), tol=1e-9)
            self.assertTrue(fid["passed"], f"{eng.engine_name} mismatch: {fid}")
            self.assertEqual(eng.events_processed, seq.events_processed)
            self.assertTrue(eng.flow_balance_ok)
            self.assertLessEqual(eng.little_err_sys, 0.01)
            self.assertEqual(eng.causality_violations, 0)
            self.assertFalse(eng.deadlocked)

    def test_4_three_engines_exact_fidelity_blocking_exp_d(self):
        """Cả 3 engine khớp < 1e-9 trên chế độ Blocking (Exp D)."""
        params = DriveThruParams(lam=0.6, c2=2, K1=8, t_warmup=500.0, t_end=2000.0, blocking_order=True)
        seq = run_sequential_engine(params, seed=2, measure_memory=False)
        co = run_coroutine_engine(params, seed=2, measure_memory=False)
        mt = run_multithread_engine(params, seed=2, measure_memory=False)

        for eng in (co, mt):
            fid = compute_fidelity_error(eng.to_dict(), seq.to_dict(), tol=1e-9)
            self.assertTrue(fid["passed"], f"{eng.engine_name} blocking mismatch: {fid}")
            self.assertEqual(eng.events_processed, seq.events_processed)
            self.assertTrue(eng.flow_balance_ok)

    def test_5_simultaneous_join_and_reverse_fork_invariance(self):
        """Khớp < 1e-9 khi trùng timestamp tại Join (t_p == t_f) và bất biến khi đảo thứ tự Fork."""
        p_det = DriveThruParams(lam=0.4, c2=2, K1=8, mean_s2=1.5, mean_s3=1.5, t_warmup=100.0, t_end=500.0)
        seq_det = run_sequential_engine(p_det, seed=3, deterministic=True, measure_memory=False)
        co_det = run_coroutine_engine(p_det, seed=3, deterministic=True, measure_memory=False)
        mt_det = run_multithread_engine(p_det, seed=3, deterministic=True, measure_memory=False)
        for eng in (co_det, mt_det):
            fid = compute_fidelity_error(eng.to_dict(), seq_det.to_dict(), tol=1e-9)
            self.assertTrue(fid["passed"], f"Simultaneous join mismatch ({eng.engine_name}): {fid}")
            self.assertAlmostEqual(eng.W_f, 0.0, places=9)

        p_fork = DriveThruParams(lam=0.6, c2=2, K1=6, t_warmup=200.0, t_end=1000.0)
        seq_ref = run_sequential_engine(p_fork, seed=5, reverse_fork_order=False, measure_memory=False)
        co_rev = run_coroutine_engine(p_fork, seed=5, reverse_fork_order=True, measure_memory=False)
        mt_rev = run_multithread_engine(p_fork, seed=5, reverse_fork_order=True, measure_memory=False)
        for eng in (co_rev, mt_rev):
            fid = compute_fidelity_error(eng.to_dict(), seq_ref.to_dict(), tol=1e-9)
            self.assertTrue(fid["passed"], f"Reverse fork mismatch ({eng.engine_name}): {fid}")


if __name__ == "__main__":
    unittest.main()
