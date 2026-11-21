import bkitevsim.core  # Né Lỗi 5: luôn nạp bkitevsim.core trước mọi module queues

import asyncio
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from bkitevsim.core import BkSysFuture, Event, Simulation, SimulationOptions
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.core.distributions import MultiStreamRNG
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import (
    CarRecord,
    JoinEntry,
    MonitorState,
    PickupState,
    StationState,
)
from drivethru.engines.base import EngineRunResult, measure_hardware_run
from drivethru.engines.safe_co_base import SafeCoLogicalProcess, check_and_raise_errors
from drivethru.metrics.statistics import check_littles_law


class CoCarSourceLP(SafeCoLogicalProcess):
    """LP0 (Coroutine): Sinh xe Poisson kèm thời gian phục vụ CRN (s1..s4)."""

    def __init__(
        self,
        lp_id: int = LPID.CAR_SOURCE,
        lam: float = 0.6,
        mean_services: Optional[Dict[int, float]] = None,
        target_lp_id: int = LPID.ORDER,
        t_warmup: float = 2000.0,
        t_end: float = 10000.0,
        seed: int = 1,
        deterministic: bool = False,
        error_sink: Optional[List[Exception]] = None,
    ):
        super().__init__(lp_id=lp_id, t_end=t_end, error_sink=error_sink)
        self.lam = lam
        self.mean_services = mean_services or {1: 1.5, 2: 1.25, 3: 1.5, 4: 1.0}
        self.target_lp_id = target_lp_id
        self.t_warmup = t_warmup
        self.rng = MultiStreamRNG(
            base_seed=seed,
            station_indices=tuple(self.mean_services.keys()),
            deterministic=deterministic,
        )
        self.next_car_id = 1
        self.total_generated = 0
        self.window_generated = 0

    def initialize(self) -> None:
        if 0.0 < self.t_warmup <= self.t_end:
            self.send_event(Event(self.t_warmup, self.lp_id, self.lp_id, EventType.WARMUP_END.value))
        first_t = self.rng.sample_interarrival(self.lam)
        if first_t <= self.t_end:
            self.send_event(Event(first_t, self.lp_id, self.lp_id, EventType.GENERATE.value))

    def on_event_safe(self, event: Event) -> None:
        t = event.timestamp
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


class CoStationLP(SafeCoLogicalProcess):
    """LP1..LP3 (Coroutine): Hàng đợi M/M/c/K dùng chung cho Order, Payment, Kitchen."""

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
        error_sink: Optional[List[Exception]] = None,
        state: Optional[StationState] = None,
    ):
        super().__init__(
            lp_id=lp_id,
            initial_state=state if state is not None else StationState(),
            t_end=t_end,
            error_sink=error_sink,
        )
        self.station_idx = station_idx
        self.c = c
        self.K = K
        self.mean_service_time = mean_service_time
        self.out_targets = out_targets if out_targets is not None else [(monitor_lp_id, EventType.DEPARTURE.value)]
        self.monitor_lp_id = monitor_lp_id
        self.t_warmup = t_warmup
        self.blocking_order = blocking_order

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

    def on_event_safe(self, event: Event) -> None:
        t = event.timestamp
        self.local_virt_time = t
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
        u_val = avg_busy if math.isinf(self.c) else (avg_busy / self.c)
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
            "U": u_val, "avg_busy": avg_busy,
            "L_q": l_q, "L": l_sys,
            "W_q": w_q, "W": w_sys,
            "X": x_tput, "P_b": p_b, "P_w": p_w,
        }


class CoPickupLP(CoStationLP):
    """
    LP4 (Coroutine): Kế thừa CoStationLP, dùng BkSysFuture + coroutine task tại bảng Join:
    - Nhánh đến trước tạo BkSysFuture và sinh task tạm dừng tại `await join_future`.
    - Nhánh đến sau gọi `join_future.set_result(t)` để đánh thức tức thì (Completion Notification).
    """

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
        error_sink: Optional[List[Exception]] = None,
    ):
        super().__init__(
            lp_id=lp_id,
            station_idx=station_idx,
            c=c,
            K=K,
            mean_service_time=mean_service_time,
            out_targets=out_targets if out_targets is not None else [(monitor_lp_id, EventType.DEPARTURE.value)],
            monitor_lp_id=monitor_lp_id,
            t_warmup=t_warmup,
            t_end=t_end,
            blocking_order=False,
            error_sink=error_sink,
            state=PickupState(),
        )
        self._join_futures: Dict[int, BkSysFuture] = {}
        self._join_tasks: Set[asyncio.Task] = set()
        self.futures_resolved: int = 0

    def _update_join_integral(self, now: float) -> None:
        dt = now - self.state.last_join_t
        if dt > 0.0:
            self.state.area_food_wait += self.state.waiting_food_count * dt
            self.state.last_join_t = now

    async def on_coroutine_run(self) -> None:
        """Chạy initialize(), chờ đến t_end và hủy gọn mọi task bảng Join còn dang dở."""
        try:
            await super().on_coroutine_run()
        finally:
            pending = [t for t in self._join_tasks if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._join_tasks.clear()

    def on_event_safe(self, event: Event) -> None:
        t = event.timestamp
        self.local_virt_time = t
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

    def _register_join_future(self, car_id: int) -> None:
        fut = self.create_bksys_future()
        self._join_futures[car_id] = fut
        task = asyncio.create_task(self._await_join_future(car_id, fut))
        self._join_tasks.add(task)
        task.add_done_callback(self._join_tasks.discard)

    async def _await_join_future(self, car_id: int, fut: BkSysFuture) -> None:
        try:
            join_t: float = await fut
            entry = self.state.join_table.get(car_id)
            if entry is not None and entry.xe_den and entry.do_xong:
                self._update_integrals(join_t)
                self._update_join_integral(join_t)
                self._complete_join(car_id, entry, join_t)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error_sink.append(exc)
            raise

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
            self._register_join_future(car.car_id)
            return

        # Đồ đã xong trước -> giải quyết BkSysFuture đang chờ nhánh xe đến
        fut = self._join_futures.pop(car.car_id, None)
        if fut is not None and not fut.done():
            self.futures_resolved += 1
            fut.set_result(t)
        else:
            self._complete_join(car.car_id, entry, t)

    def _handle_food_ready_at_join(self, food_car: CarRecord, t: float) -> None:
        entry = self.state.join_table.get(food_car.car_id)
        if entry is None:
            entry = JoinEntry()
            self.state.join_table[food_car.car_id] = entry
        entry.do_xong = True
        entry.t_f = t

        if not entry.xe_den:
            self._register_join_future(food_car.car_id)
            return

        # Xe đã đến trước -> giảm đếm chờ đồ và giải quyết BkSysFuture đánh thức xe
        self.state.waiting_food_count -= 1
        fut = self._join_futures.pop(food_car.car_id, None)
        if fut is not None and not fut.done():
            self.futures_resolved += 1
            fut.set_result(t)
        else:
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
            "futures_resolved": self.futures_resolved,
        })
        return stats


class CoMonitorLP(SafeCoLogicalProcess):
    """LP5 (Coroutine): Thống kê đầu-cuối toàn mạng (T, P95, P(T>8), X, DROP)."""

    def __init__(
        self,
        lp_id: int = LPID.MONITOR,
        t_warmup: float = 2000.0,
        t_end: float = 10000.0,
        sla_threshold: float = 8.0,
        error_sink: Optional[List[Exception]] = None,
    ):
        super().__init__(lp_id=lp_id, initial_state=MonitorState(), t_end=t_end, error_sink=error_sink)
        self.t_warmup = t_warmup
        self.sla_threshold = sla_threshold

    def initialize(self) -> None:
        if 0.0 < self.t_warmup <= self.t_end:
            self.send_event(Event(self.t_warmup, self.lp_id, self.lp_id, EventType.WARMUP_END.value))

    def on_event_safe(self, event: Event) -> None:
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
            "X": n / tm, "T": t_mean, "P95_T": p95_t,
            "P_T_gt_8": p_gt_8, "W_f": wf_mean, "P_f": p_f, "P_b": p_b_global,
        }


def _execute_coroutine_sim(
    params: DriveThruParams,
    seed: int,
    reverse_fork_order: bool,
    deterministic: bool,
    verify_invariants: bool,
) -> Dict[str, Any]:
    logging.getLogger("bkitevsim").setLevel(logging.ERROR)
    error_sink: List[Exception] = []

    options = SimulationOptions(
        end_time=params.t_end,
        dispatcher="coroutine",
        bucket_width=safe_bucket_width(params.t_end),
        log_level="ERROR",
    )
    sim = Simulation(
        options,
        models={
            "CoSource": CoCarSourceLP,
            "CoStation": CoStationLP,
            "CoPickup": CoPickupLP,
            "CoMonitor": CoMonitorLP,
        },
    )

    mean_services = {1: params.mean_s1, 2: params.mean_s2, 3: params.mean_s3, 4: params.mean_s4}
    src = sim.create_lp(
        LPID.CAR_SOURCE, "CoSource",
        lam=params.lam, mean_services=mean_services, target_lp_id=LPID.ORDER,
        t_warmup=params.t_warmup, t_end=params.t_end,
        seed=seed, deterministic=deterministic, error_sink=error_sink,
    )

    order_targets = [(LPID.PAYMENT, EventType.TRANSFER.value), (LPID.KITCHEN, EventType.ORDER_PLACED.value)]
    if reverse_fork_order:
        order_targets.reverse()

    order = sim.create_lp(
        LPID.ORDER, "CoStation",
        station_idx=1, c=params.c1, K=params.K1, mean_service_time=params.mean_s1,
        out_targets=order_targets, monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup, t_end=params.t_end,
        blocking_order=params.blocking_order, error_sink=error_sink,
    )
    payment = sim.create_lp(
        LPID.PAYMENT, "CoStation",
        station_idx=2, c=params.c2, K=math.inf, mean_service_time=params.mean_s2,
        out_targets=[(LPID.PICKUP, EventType.TRANSFER.value)], monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup, t_end=params.t_end, error_sink=error_sink,
    )
    kitchen_targets = [(LPID.PICKUP, EventType.FOOD_READY.value)]
    if params.blocking_order:
        kitchen_targets = [(LPID.ORDER, EventType.FOOD_READY.value), (LPID.PICKUP, EventType.FOOD_READY.value)]
    kitchen = sim.create_lp(
        LPID.KITCHEN, "CoStation",
        station_idx=3, c=params.c3, K=math.inf, mean_service_time=params.mean_s3,
        out_targets=kitchen_targets, monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup, t_end=params.t_end, error_sink=error_sink,
    )
    pickup = sim.create_lp(
        LPID.PICKUP, "CoPickup",
        station_idx=4, c=params.c4, K=math.inf, mean_service_time=params.mean_s4,
        out_targets=[(LPID.MONITOR, EventType.DEPARTURE.value)], monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup, t_end=params.t_end, error_sink=error_sink,
    )
    monitor = sim.create_lp(
        LPID.MONITOR, "CoMonitor",
        t_warmup=params.t_warmup, t_end=params.t_end, error_sink=error_sink,
    )

    sim_stats = sim.run()
    check_and_raise_errors(error_sink, context="CoDriveThruEngine")

    for lp in (src, order, payment, kitchen, pickup, monitor):
        lp.finalize()

    s1, s2, s3, s4, sm = (
        order.get_statistics(), payment.get_statistics(),
        kitchen.get_statistics(), pickup.get_statistics(), monitor.get_statistics(),
    )
    n_unfinished_total = s1["n_unfinished"] + s2["n_unfinished"] + s4["n_unfinished_join"] + s4["n_unfinished"]
    flow_balance_car = (
        src.total_generated == s1["total_arrived"]
        and s1["total_arrived"] == (sm["total_completed"] + sm["total_dropped"] + n_unfinished_total)
    )
    orders_sent_to_kitchen = s1["total_served"] + len(order.state.waiting_food_cars)
    flow_balance_kitchen = (
        orders_sent_to_kitchen == s3["total_arrived"]
        and s3["total_arrived"] == (s3["total_served"] + s3["n_unfinished"])
    )
    l_system = s1["L"] + s2["L"] + s4["L_f"] + s4["L"]
    little_s1 = check_littles_law(s1["L"], s1["X"], s1["W"], tol=0.01)
    little_s2 = check_littles_law(s2["L"], s2["X"], s2["W"], tol=0.01)
    little_s3 = check_littles_law(s3["L"], s3["X"], s3["W"], tol=0.01)
    little_s4 = check_littles_law(s4["L"], s4["X"], s4["W"], tol=0.01)
    little_sys = check_littles_law(l_system, sm["X"], sm["T"], tol=0.01)

    if verify_invariants:
        assert flow_balance_car, "Vi phạm cân bằng dòng xe ở Coroutine Engine!"
        assert flow_balance_kitchen, "Vi phạm cân bằng dòng đơn bếp ở Coroutine Engine!"

    events_processed = sim_stats.get("events_processed", 0) if isinstance(sim_stats, dict) else 0
    return {
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "sm": sm,
        "l_system": l_system,
        "total_generated": src.total_generated,
        "n_unfinished_total": n_unfinished_total,
        "flow_balance_ok": flow_balance_car and flow_balance_kitchen,
        "little_err_s1": little_s1["rel_error"],
        "little_err_s2": little_s2["rel_error"],
        "little_err_s3": little_s3["rel_error"],
        "little_err_s4": little_s4["rel_error"],
        "little_err_sys": little_sys["rel_error"],
        "events_processed": events_processed,
    }


def run_coroutine_engine(
    params: DriveThruParams,
    seed: int = 1,
    reverse_fork_order: bool = False,
    deterministic: bool = False,
    verify_invariants: bool = True,
    measure_memory: bool = True,
) -> EngineRunResult:
    """
    Kiến trúc 2 (Virtual Multi-thread / Coroutine):
    BkSysCoEventLoop + SafeCoLogicalProcess + BkSysFuture tại bảng Join của CoPickupLP.
    """
    raw, hw = measure_hardware_run(
        lambda: _execute_coroutine_sim(
            params=params,
            seed=seed,
            reverse_fork_order=reverse_fork_order,
            deterministic=deterministic,
            verify_invariants=verify_invariants,
        ),
        measure_memory=measure_memory,
    )

    s1, s2, s3, s4, sm = raw["s1"], raw["s2"], raw["s3"], raw["s4"], raw["sm"]
    events_processed = int(raw["events_processed"])
    wall_time = hw["wall_time"]
    events_per_sec = events_processed / wall_time if wall_time > 0.0 else 0.0

    return EngineRunResult(
        engine_name="coroutine",
        seed=seed,
        dispatcher="BkSysCoEventLoop",
        blocking_order=params.blocking_order,
        lam=params.lam,
        c2=params.c2,
        K1=params.K1,
        t_warmup=params.t_warmup,
        t_end=params.t_end,
        T=sm["T"],
        P95_T=sm["P95_T"],
        P_T_gt_8=sm["P_T_gt_8"],
        P_b=s1["P_b"],
        X=sm["X"],
        W_f=s4["W_f"],
        P_f=s4["P_f"],
        L_f=s4["L_f"],
        L_system=raw["l_system"],
        U1=s1["U"], U2=s2["U"], U3=s3["U"], U4=s4["U"],
        W1=s1["W"], W2=s2["W"], W3=s3["W"], W4=s4["W"],
        Wq1=s1["W_q"], Wq2=s2["W_q"], Wq3=s3["W_q"], Wq4=s4["W_q"],
        L1=s1["L"], L2=s2["L"], L3=s3["L"], L4=s4["L"],
        X1=s1["X"], X2=s2["X"], X3=s3["X"], X4=s4["X"],
        total_generated=raw["total_generated"],
        total_completed=sm["total_completed"],
        total_dropped=sm["total_dropped"],
        n_unfinished_total=raw["n_unfinished_total"],
        n_unfinished_join=s4["n_unfinished_join"],
        flow_balance_ok=raw["flow_balance_ok"],
        little_err_s1=raw["little_err_s1"],
        little_err_s2=raw["little_err_s2"],
        little_err_s3=raw["little_err_s3"],
        little_err_s4=raw["little_err_s4"],
        little_err_sys=raw["little_err_sys"],
        events_processed=events_processed,
        wall_time=wall_time,
        cpu_time=hw["cpu_time"],
        cpu_wall_ratio=hw["cpu_wall_ratio"],
        events_per_sec=events_per_sec,
        peak_mem_mb=hw["peak_mem_mb"],
        causality_violations=0,
        deadlocked=False,
    )
