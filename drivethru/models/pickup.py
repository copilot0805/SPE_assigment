import math
from typing import Any, Dict, List, Optional, Tuple
from bkitevsim.core import Event
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import CarRecord, JoinEntry, PickupState
from drivethru.models.station import StationLP


class PickupLP(StationLP):
    def __init__(
        self,
        lp_id: int = LPID.PICKUP,
        station_idx: int = 4,
        c: float = 2,
        K: float = math.inf,
        mean_service_time: float = 1.0,
        out_targets: Optional[List[Tuple[int, str]]] = None,
        monitor_lp_id: int = LPID.MONITOR,
        t_warmup: float = 2000.0,
        t_end: float = 10000.0,
        record_timestamps: bool = False,
    ):
        super().__init__(
            lp_id=lp_id, station_idx=station_idx, c=c, K=K,
            mean_service_time=mean_service_time,
            out_targets=out_targets if out_targets is not None else [(monitor_lp_id, EventType.DEPARTURE.value)],
            monitor_lp_id=monitor_lp_id,
            t_warmup=t_warmup, t_end=t_end,
            blocking_order=False, record_timestamps=record_timestamps,
            state=PickupState(),
        )

    def _update_join_integral(self, now: float) -> None:
        dt = now - self.state.last_join_t
        if dt > 0.0:
            self.state.area_food_wait += self.state.waiting_food_count * dt
            self.state.last_join_t = now

    def handle_event(self, event: Event) -> None:
        t = event.timestamp
        self._guard_monotonic_time(t, event.event_type)
        self.local_virt_time = t
        if self.record_timestamps:
            self.event_timestamps.append(t)
        self._update_integrals(t)
        self._update_join_integral(t)

        et = event.event_type
        if et == EventType.TRANSFER.value:
            self._handle_car_arrival_at_join(event.payload, t)
        elif et == EventType.FOOD_READY.value:
            self._handle_food_ready_at_join(event.payload, t)
        elif et == EventType.BEGIN_SERVICE.value:
            self._handle_begin_service(event.payload, t)
        elif et == EventType.END_SERVICE.value:
            self._handle_end_service(event.payload, t)
        elif et == EventType.WARMUP_END.value:
            self._handle_warmup_end(t)

    def _handle_car_arrival_at_join(self, car: CarRecord, t: float) -> None:
        entry = self.state.join_table.get(car.car_id)
        if entry is None:
            entry = JoinEntry()
            self.state.join_table[car.car_id] = entry
        entry.car = car
        entry.xe_den = True
        entry.t_p = t
        car.t_payment_done = t
        if not entry.do_xong:
            self.state.waiting_food_count += 1
            return
        self._complete_join(car.car_id, entry, t)

    def _handle_food_ready_at_join(self, food_car: CarRecord, t: float) -> None:
        entry = self.state.join_table.get(food_car.car_id)
        if entry is None:
            entry = JoinEntry()
            self.state.join_table[food_car.car_id] = entry
        entry.do_xong = True
        entry.t_f = t
        if entry.xe_den:
            self.state.waiting_food_count -= 1
            self._complete_join(food_car.car_id, entry, t)

    def _complete_join(self, car_id: int, entry: JoinEntry, t: float) -> None:
        self.state.join_table.pop(car_id, None)
        car = entry.car
        assert car is not None
        w_f = max(0.0, entry.t_f - entry.t_p)
        car.t_food_ready = entry.t_f
        car.food_wait_time = w_f
        if car.t_arrive >= self.t_warmup:
            self.state.food_wait_samples.append(w_f)
            if entry.t_f > entry.t_p + 1e-12:
                self.state.food_waited_count += 1
        super()._handle_arrival(car, t)

    def _handle_warmup_end(self, t: float) -> None:
        super()._handle_warmup_end(t)
        self.state.area_food_wait = 0.0
        self.state.last_join_t = t
        self.state.food_wait_samples.clear()
        self.state.food_waited_count = 0

    def finalize(self) -> None:
        super().finalize()
        self._update_join_integral(self.t_end)

    @property
    def n_unfinished_join(self) -> int:
        return sum(1 for e in self.state.join_table.values() if e.xe_den)

    def get_statistics(self) -> Dict[str, Any]:
        self._update_join_integral(self.t_end)
        stats = super().get_statistics()
        tm = max(1e-9, self.t_end - self.t_warmup)
        n_wf = len(self.state.food_wait_samples)
        stats.update({
            "L_f": self.state.area_food_wait / tm,
            "W_f": sum(self.state.food_wait_samples) / n_wf if n_wf > 0 else 0.0,
            "P_f": self.state.food_waited_count / n_wf if n_wf > 0 else 0.0,
            "n_unfinished_join": self.n_unfinished_join,
            "join_table_entries": len(self.state.join_table),
        })
        return stats
