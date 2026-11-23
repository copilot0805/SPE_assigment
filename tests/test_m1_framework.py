import random
import unittest

from bkitevsim.core import BkSysLogicalProcess, Event, Simulation, SimulationOptions
from bkitevsim.queues import LadderQueue
from drivethru.config.simulation_config import safe_bucket_width


class MultiChainTimestampProbeLP(BkSysLogicalProcess):
    """
    LP dò vết thời gian với nhiều chuỗi TICK đồng thời (mặc định 30 chuỗi)
    để hàng đợi sự kiện luôn có nhiều sự kiện chờ đồng thời -> thực sự bắt được lỗi wrap-around.
    """

    def __init__(
        self,
        lp_id: int,
        t_end: float,
        num_chains: int = 30,
        step_mean: float = 20.0,
        seed: int = 1,
    ):
        super().__init__(lp_id)
        self.t_end = t_end
        self.num_chains = num_chains
        self.step_mean = step_mean
        self.rng = random.Random(seed)
        self.observed_timestamps = []
        self.backward_jumps = 0
        self._prev_ts = -1.0

    def initialize(self) -> None:
        for chain_id in range(self.num_chains):
            t0 = self.rng.expovariate(1.0 / self.step_mean)
            if t0 <= self.t_end:
                self.send_event(Event(t0, self.lp_id, self.lp_id, "TICK", payload=chain_id))

    def handle_event(self, event: Event) -> None:
        t = event.timestamp
        self.local_virt_time = t
        if t < self._prev_ts - 1e-12:
            self.backward_jumps += 1
        self._prev_ts = t
        self.observed_timestamps.append(t)

        next_t = t + self.rng.expovariate(1.0 / self.step_mean)
        if next_t <= self.t_end:
            self.send_event(Event(next_t, self.lp_id, self.lp_id, "TICK", payload=event.payload))


class TestM1FrameworkGate(unittest.TestCase):
    def test_1_known_framework_bug_ladder_queue_wrap_around(self):
        """
        [Ghi nhận hiện trạng framework gốc] Xác nhận LadderQueue mặc định (bucket_width=1.0)
        trong bkitevsim/ vẫn còn lỗi wrap-around (rút t=1025.0 trước t=500.0).
        Lưu ý: Nếu giảng viên vá lỗi này trong bkitevsim/, test ghi nhận hiện trạng này sẽ báo đỏ.
        """
        q = LadderQueue(bucket_width=1.0, num_buckets=1024)
        q.push(Event(timestamp=500.0, sender_id=0, receiver_id=0, event_type="A"))
        q.push(Event(timestamp=1025.0, sender_id=0, receiver_id=0, event_type="B"))
        first_popped = q.pop()
        self.assertEqual(first_popped.timestamp, 1025.0)

    def test_2_safe_bucket_width_formula_and_monotonic_order(self):
        """Kiểm chứng safe_bucket_width(10000)==11 và LadderQueue giữ thứ tự không giảm khi rút hàng loạt."""
        self.assertEqual(safe_bucket_width(10000.0), 11.0)
        t_end = 20000.0
        bw = safe_bucket_width(t_end)
        q = LadderQueue(bucket_width=bw, num_buckets=1024)

        rng = random.Random(42)
        for _ in range(5000):
            ts = rng.uniform(0.0, t_end + 80.0)
            q.push(Event(timestamp=ts, sender_id=0, receiver_id=0, event_type="TEST"))

        prev_ts = -1.0
        while not q.is_empty():
            ev = q.pop()
            self.assertGreaterEqual(ev.timestamp, prev_ts, f"Vi phạm thứ tự: {ev.timestamp} < {prev_ts}")
            prev_ts = ev.timestamp

    def test_3_multi_chain_dispatcher_detects_bug_and_verifies_fix(self):
        """
        Kiểm chứng với 30 chuỗi TICK đồng thời trên 10000 phút:
        - bucket_width=1.0 PHẢI phát hiện được lỗi thời gian đi lùi (backward_jumps > 0).
        - safe_bucket_width(10000.0) PHẢI giữ đúng 0 lần đi lùi (backward_jumps == 0).
        """
        t_end = 10000.0

        # (a) Chứng minh bộ dò 30 chuỗi thực sự bắt được lỗi khi bucket_width=1.0
        sim_bad = Simulation(
            SimulationOptions(end_time=t_end, dispatcher="sequential", bucket_width=1.0, log_level="ERROR"),
            models={"Probe": MultiChainTimestampProbeLP},
        )
        probe_bad = sim_bad.create_lp(0, "Probe", t_end=t_end, num_chains=30, step_mean=20.0, seed=7)
        sim_bad.run()
        self.assertGreater(
            probe_bad.backward_jumps, 0,
            "Bộ dò 30 chuỗi không phát hiện được lỗi wrap-around ở bucket_width=1.0!"
        )

        # (b) Chứng minh safe_bucket_width(t_end) triệt tiêu hoàn toàn lỗi đi lùi
        sim_ok = Simulation(
            SimulationOptions(
                end_time=t_end, dispatcher="sequential",
                bucket_width=safe_bucket_width(t_end), log_level="ERROR",
            ),
            models={"Probe": MultiChainTimestampProbeLP},
        )
        probe_ok = sim_ok.create_lp(0, "Probe", t_end=t_end, num_chains=30, step_mean=20.0, seed=7)
        sim_ok.run()
        self.assertGreater(len(probe_ok.observed_timestamps), 10000)
        self.assertEqual(probe_ok.backward_jumps, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
