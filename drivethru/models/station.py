import math
from typing import Any, Dict, List, Optional, Tuple
from bkitevsim.core import Event, BkSysLogicalProcess
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import CarRecord, StationState


class StationLP(BkSysLogicalProcess):
    """
    Lớp trạm hàng đợi tổng quát M/M/c/K dùng chung cho:
    - Cả 6 mô hình hàng đợi đơn trong Thí nghiệm A (M/M/1, M/M/1/K, M/M/inf, M/M/n/n, M/M/c, M/M/c/K)
    - Các trạm Order (LP1), Payment (LP2), Kitchen (LP3) và lớp cha của PickupLP (LP4)
    - Hỗ trợ chế độ chặn (blocking_order=True) tại Order cho Thí nghiệm D.
    """

    def __init__(
        self,
        lp_id: int,
        station_idx: int = 1,
        c: float = 1,
        K: float = math.inf,
        mean_service_time: float = 1.0,
        out_targets: Optional[List[Tuple[int, str]]] = None,
        monitor_lp_id: int = LPID.MONITOR,
        t_warmup: float = 2000.0,
        t_end: float = 10000.0,
        blocking_order: bool = False,
        record_timestamps: bool = False,
        state: Optional[StationState] = None,
    ):
        super().__init__(lp_id, state if state is not None else StationState())
        self.station_idx = station_idx
        self.c = c
        self.K = K
        self.mean_service_time = mean_service_time
        self.out_targets = out_targets if out_targets is not None else [(monitor_lp_id, EventType.DEPARTURE.value)]
        self.monitor_lp_id = monitor_lp_id
        self.t_warmup = t_warmup
        self.t_end = t_end
        self.blocking_order = blocking_order
        self.record_timestamps = record_timestamps
        self.event_timestamps: List[float] = []

    def initialize(self) -> None:
        if 0.0 < self.t_warmup <= self.t_end:
            self.send_event(Event(self.t_warmup, self.lp_id, self.lp_id, EventType.WARMUP_END.value))

    def _update_integrals(self, now: float) -> None:
        dt = now - self.state.last_t
        if dt > 0.0:
            b = self.state.busy
            q = len(self.state.queue)
            self.state.area_busy += b * dt
            self.state.area_queue += q * dt
            self.state.area_system += (b + q) * dt
            self.state.last_t = now

    def handle_event(self, event: Event) -> None:
        t = event.timestamp
        self.local_virt_time = t
        if self.record_timestamps:
            self.event_timestamps.append(t)
        self._update_integrals(t)

        et = event.event_type
        if et in (EventType.ARRIVAL.value, EventType.TRANSFER.value, EventType.ORDER_PLACED.value):
            self._handle_arrival(event.payload, t)
        elif et == EventType.BEGIN_SERVICE.value:
            self._handle_begin_service(event.payload, t)
        elif et == EventType.END_SERVICE.value:
            self._handle_end_service(event.payload, t)
        elif et == EventType.FOOD_READY.value:
            self._handle_food_ready_at_order(event.payload, t)
        elif et == EventType.WARMUP_END.value:
            self._handle_warmup_end(t)

    def _handle_arrival(self, car: CarRecord, t: float) -> None:
        self.state.total_arrived += 1
        if t >= self.t_warmup:
            self.state.arrived += 1

        if self.state.busy + len(self.state.queue) >= self.K:
            self.state.total_dropped += 1
            if t >= self.t_warmup:
                self.state.dropped += 1
            self.send_event(Event(t, self.lp_id, self.monitor_lp_id, EventType.DROP.value, payload=car))
            return

        car.t_enter[self.station_idx] = t
        if self.state.busy < self.c:
            self.state.busy += 1
            self.send_event(Event(t, self.lp_id, self.lp_id, EventType.BEGIN_SERVICE.value, payload=car))
        else:
            self.state.queue.append(car)

    def _handle_begin_service(self, car: CarRecord, t: float) -> None:
        car.t_start[self.station_idx] = t
        s_i = car.service_times.get(self.station_idx, self.mean_service_time)
        self.send_event(Event(t + s_i, self.lp_id, self.lp_id, EventType.END_SERVICE.value, payload=car))

    def _record_completion_metrics(self, car: CarRecord, t: float) -> None:
        car.t_end[self.station_idx] = t
        self.state.total_served += 1
        if car.t_arrive >= self.t_warmup:
            self.state.served += 1
            wq = car.t_start[self.station_idx] - car.t_enter[self.station_idx]
            w = t - car.t_enter[self.station_idx]
            self.state.sum_wq += wq
            self.state.sum_w += w
            if wq > 1e-12:
                self.state.waited_count += 1

    def _release_server_or_serve_next(self, t: float) -> None:
        if self.state.queue:
            next_car = self.state.queue.popleft()
            self.send_event(Event(t, self.lp_id, self.lp_id, EventType.BEGIN_SERVICE.value, payload=next_car))
        else:
            self.state.busy -= 1

    def _handle_end_service(self, car: CarRecord, t: float) -> None:
        if self.blocking_order:
            self.state.waiting_food_cars[car.car_id] = car
            for target_id, out_type in self.out_targets:
                if out_type == EventType.ORDER_PLACED.value:
                    self.send_event(Event(t, self.lp_id, target_id, out_type, payload=car.copy_for_branch()))
            return

        self._record_completion_metrics(car, t)
        for target_id, out_type in self.out_targets:
            payload = car.copy_for_branch() if out_type == EventType.ORDER_PLACED.value else car
            self.send_event(Event(t, self.lp_id, target_id, out_type, payload=payload))

        self._release_server_or_serve_next(t)

    def _handle_food_ready_at_order(self, kitchen_car: CarRecord, t: float) -> None:
        if not self.blocking_order:
            return
        car = self.state.waiting_food_cars.pop(kitchen_car.car_id, None)
        if car is None:
            return

        self._record_completion_metrics(car, t)
        for target_id, out_type in self.out_targets:
            if out_type != EventType.ORDER_PLACED.value:
                self.send_event(Event(t, self.lp_id, target_id, out_type, payload=car))

        self._release_server_or_serve_next(t)

    def _handle_warmup_end(self, t: float) -> None:
        self.state.arrived = 0
        self.state.served = 0
        self.state.dropped = 0
        self.state.waited_count = 0
        self.state.area_busy = 0.0
        self.state.area_queue = 0.0
        self.state.area_system = 0.0
        self.state.sum_w = 0.0
        self.state.sum_wq = 0.0
        self.state.last_t = t

    def finalize(self) -> None:
        self._update_integrals(self.t_end)

    @property
    def n_unfinished(self) -> int:
        return self.state.busy + len(self.state.queue)

    def get_statistics(self) -> Dict[str, Any]:
        self._update_integrals(self.t_end)
        tm = max(1e-9, self.t_end - self.t_warmup)

        avg_busy = self.state.area_busy / tm
        if math.isinf(self.c):
            u_val = avg_busy
        else:
            u_val = avg_busy / self.c

        l_q = self.state.area_queue / tm
        l_sys = self.state.area_system / tm
        x_tput = self.state.served / tm

        w_q = self.state.sum_wq / self.state.served if self.state.served > 0 else 0.0
        w_sys = self.state.sum_w / self.state.served if self.state.served > 0 else 0.0
        p_b = self.state.dropped / self.state.arrived if self.state.arrived > 0 else 0.0
        p_w = self.state.waited_count / self.state.served if self.state.served > 0 else 0.0

        return {
            "station_idx": self.station_idx,
            "total_arrived": self.state.total_arrived,
            "total_served": self.state.total_served,
            "total_dropped": self.state.total_dropped,
            "n_unfinished": self.n_unfinished,
            "arrived": self.state.arrived,
            "served": self.state.served,
            "dropped": self.state.dropped,
            "U": u_val,
            "avg_busy": avg_busy,
            "L_q": l_q,
            "L": l_sys,
            "W_q": w_q,
            "W": w_sys,
            "X": x_tput,
            "P_b": p_b,
            "P_w": p_w,
        }
