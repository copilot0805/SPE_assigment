import math
from typing import Any, Dict
from bkitevsim.core import Event, BkSysLogicalProcess
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import CarRecord, MonitorState


class MonitorLP(BkSysLogicalProcess):
    """LP5: Ghi nhận kết quả toàn cục (completed, dropped, T, P95(T), P(T > 8), W_f, P_f)."""

    def __init__(
        self,
        lp_id: int = LPID.MONITOR,
        t_warmup: float = 2000.0,
        t_end: float = 10000.0,
        sla_threshold: float = 8.0,
    ):
        super().__init__(lp_id, MonitorState())
        self.t_warmup = t_warmup
        self.t_end = t_end
        self.sla_threshold = sla_threshold

    def initialize(self) -> None:
        if 0.0 < self.t_warmup <= self.t_end:
            self.send_event(Event(self.t_warmup, self.lp_id, self.lp_id, EventType.WARMUP_END.value))

    @property
    def total_completed(self) -> int:
        return self.state.total_completed

    @property
    def total_dropped(self) -> int:
        return self.state.total_dropped

    @property
    def t_samples(self):
        return self.state.t_samples

    def handle_event(self, event: Event) -> None:
        t = event.timestamp
        self.local_virt_time = t

        if event.event_type == EventType.WARMUP_END.value:
            self.state.window_completed = 0
            self.state.window_dropped = 0
            self.state.t_samples.clear()
            self.state.wf_samples.clear()
            return

        car: CarRecord = event.payload
        if event.event_type == EventType.DROP.value:
            self.state.total_dropped += 1
            if car.t_arrive >= self.t_warmup:
                self.state.window_dropped += 1
        elif event.event_type == EventType.DEPARTURE.value:
            self.state.total_completed += 1
            if car.t_arrive >= self.t_warmup:
                self.state.window_completed += 1
                self.state.t_samples.append(t - car.t_arrive)
                self.state.wf_samples.append(car.food_wait_time)

    def get_statistics(self) -> Dict[str, Any]:
        tm = max(1e-9, self.t_end - self.t_warmup)
        samples = sorted(self.state.t_samples)
        n = len(samples)
        if n > 0:
            t_mean = sum(samples) / n
            idx_95 = min(n - 1, max(0, math.ceil(0.95 * n) - 1))
            p95_t = samples[idx_95]
            p_gt_8 = sum(1 for x in samples if x > self.sla_threshold) / n
            wf_mean = sum(self.state.wf_samples) / n
            p_f = sum(1 for w in self.state.wf_samples if w > 1e-12) / n
        else:
            t_mean = p95_t = p_gt_8 = wf_mean = p_f = 0.0

        total_window_in = self.state.window_completed + self.state.window_dropped
        p_b_global = self.state.window_dropped / total_window_in if total_window_in > 0 else 0.0

        return {
            "total_completed": self.state.total_completed,
            "total_dropped": self.state.total_dropped,
            "window_completed": self.state.window_completed,
            "window_dropped": self.state.window_dropped,
            "X": n / tm,
            "T": t_mean,
            "P95_T": p95_t,
            "P_T_gt_8": p_gt_8,
            "W_f": wf_mean,
            "P_f": p_f,
            "P_b": p_b_global,
        }
