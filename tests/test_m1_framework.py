import random
import unittest
from bkitevsim.core import Event, BkSysLogicalProcess, Simulation, SimulationOptions
from bkitevsim.queues import LadderQueue
from drivethru.config.simulation_config import safe_bucket_width


class TimestampProbeLP(BkSysLogicalProcess):
    """LP dò vết thời gian để kiểm tra tính đơn điệu không giảm của Dispatcher."""

    def __init__(self, lp_id: int, t_end: float, step_mean: float = 5.0, seed: int = 1):
        super().__init__(lp_id)
        self.t_end = t_end
        self.rng = random.Random(seed)
        self.step_mean = step_mean
        self.observed_timestamps = []

    def initialize(self) -> None:
        self.send_event(Event(0.0, self.lp_id, self.lp_id, "TICK"))

    def handle_event(self, event: Event) -> None:
        self.local_virt_time = event.timestamp
        self.observed_timestamps.append(event.timestamp)
        next_t = event.timestamp + self.rng.expovariate(1.0 / self.step_mean)
        if next_t <= self.t_end:
            self.send_event(Event(next_t, self.lp_id, self.lp_id, "TICK"))


class TestM1FrameworkGate(unittest.TestCase):
    def test_default_bucket_width_wrap_around_bug(self):
        """Chứng minh LadderQueue với bucket_width=1.0 rút sai thứ tự khi timestamp >= 1024."""
        q = LadderQueue(bucket_width=1.0, num_buckets=1024)
        q.push(Event(timestamp=500.0, sender_id=0, receiver_id=0, event_type="A"))
        q.push(Event(timestamp=1025.0, sender_id=0, receiver_id=0, event_type="B"))
        first_popped = q.pop()
        self.assertEqual(first_popped.timestamp, 1025.0)

    def test_safe_bucket_width_formula_and_monotonic_order(self):
        """Kiểm chứng safe_bucket_width(10000) == 11 và luôn giữ thứ tự thời gian không giảm."""
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
            self.assertGreaterEqual(
                ev.timestamp, prev_ts,
                f"Vi phạm thứ tự thời gian: {ev.timestamp} < {prev_ts}"
            )
            prev_ts = ev.timestamp

    def test_sequential_dispatcher_non_decreasing_time(self):
        """Kiểm chứng SequentialEventDispatcher chạy 10000 phút có timestamp tăng nghiêm ngặt."""
        t_end = 10000.0
        options = SimulationOptions(
            end_time=t_end,
            dispatcher="sequential",
            bucket_width=safe_bucket_width(t_end),
            log_level="ERROR",
        )
        sim = Simulation(options, models={"Probe": TimestampProbeLP})
        probe = sim.create_lp(0, "Probe", t_end=t_end, step_mean=2.0, seed=7)
        sim.run()

        ts_list = probe.observed_timestamps
        self.assertGreater(len(ts_list), 4000)
        for i in range(1, len(ts_list)):
            self.assertGreaterEqual(ts_list[i], ts_list[i - 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
