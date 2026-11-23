import math
from typing import Dict
from bkitevsim.core import Event, BkSysLogicalProcess
from drivethru.core.distributions import MultiStreamRNG
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import CarRecord


class CarSourceLP(BkSysLogicalProcess):
    def __init__(
        self,
        lp_id: int = LPID.CAR_SOURCE,
        lam: float = 0.6,
        mean_services: Dict[int, float] = None,
        target_lp_id: int = LPID.ORDER,
        t_warmup: float = 2000.0,
        t_end: float = 10000.0,
        seed: int = 1,
        deterministic: bool = False,
    ):
        super().__init__(lp_id)
        self.lam = lam
        self.mean_services = mean_services or {1: 1.5, 2: 1.25, 3: 1.5, 4: 1.0}
        self.target_lp_id = target_lp_id
        self.t_warmup = t_warmup
        self.t_end = t_end
        self.rng = MultiStreamRNG(
            base_seed=seed,
            station_indices=tuple(self.mean_services.keys()),
            deterministic=deterministic,
        )
        self.next_car_id = 1
        self.total_generated = 0
        self.window_generated = 0
        self._last_handled_time: float = -math.inf

    def initialize(self) -> None:
        if 0.0 < self.t_warmup <= self.t_end:
            self.send_event(Event(self.t_warmup, self.lp_id, self.lp_id, EventType.WARMUP_END.value))
        first_t = self.rng.sample_interarrival(self.lam)
        if first_t <= self.t_end:
            self.send_event(Event(first_t, self.lp_id, self.lp_id, EventType.GENERATE.value))

    def handle_event(self, event: Event) -> None:
        t = event.timestamp
        if t < self._last_handled_time - 1e-12:
            raise RuntimeError(
                f"Vi phạm thời gian không giảm tại LP {self.lp_id} (CarSource): "
                f"t={t:.6f} < last_t={self._last_handled_time:.6f} ({event.event_type})"
            )
        self._last_handled_time = t
        self.local_virt_time = t

        if event.event_type == EventType.WARMUP_END.value:
            self.window_generated = 0
            return

        if event.event_type == EventType.GENERATE.value:
            s_map = {k: self.rng.sample_service(k, m) for k, m in self.mean_services.items()}
            car = CarRecord(car_id=self.next_car_id, t_arrive=t, service_times=s_map)
            self.next_car_id += 1
            self.total_generated += 1
            if t >= self.t_warmup:
                self.window_generated += 1

            self.send_event(Event(t, self.lp_id, self.target_lp_id, EventType.ARRIVAL.value, payload=car))

            next_t = t + self.rng.sample_interarrival(self.lam)
            if next_t <= self.t_end:
                self.send_event(Event(next_t, self.lp_id, self.lp_id, EventType.GENERATE.value))
