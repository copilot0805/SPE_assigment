import bkitevsim.core  # Né Lỗi 5

import asyncio
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from bkitevsim.core import BkSysFuture, Event, Simulation, SimulationOptions
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.core.event_types import EventType, LPID
from drivethru.core.state import CarRecord, JoinEntry
from drivethru.engines.base import EngineRunResult, measure_hardware_run
from drivethru.engines.safe_co_base import SafeCoLogicalProcess, check_and_raise_errors
from drivethru.metrics.stats_utils import check_littles_law
from drivethru.models.car_source import CarSourceLP
from drivethru.models.monitor import MonitorLP
from drivethru.models.pickup import PickupLP
from drivethru.models.station import StationLP


class CoCarSourceLP(SafeCoLogicalProcess):
    """LP0 (Coroutine): Bọc trực tiếp CarSourceLP (không nhân bản logic sinh xe CRN)."""

    def __init__(self, lp_id: int = LPID.CAR_SOURCE, t_end: float = 10000.0, error_sink=None, **kwargs):
        self._inner = CarSourceLP(lp_id=lp_id, t_end=t_end, **kwargs)
        super().__init__(lp_id=lp_id, initial_state=self._inner.state, t_end=t_end, error_sink=error_sink)
        self._inner.send_event = self.send_event

    @property
    def total_generated(self) -> int:
        return self._inner.total_generated

    def initialize(self) -> None:
        self._inner.initialize()

    def on_event_safe(self, event: Event) -> None:
        self.local_virt_time = event.timestamp
        self._inner.handle_event(event)

    def finalize(self) -> None:
        self._inner.finalize()


class CoStationLP(SafeCoLogicalProcess):
    """LP1..LP3 (Coroutine): Bọc trực tiếp StationLP (tự kế thừa mọi bản vá & fail-fast của StationLP)."""

    def __init__(self, lp_id: int, t_end: float = 10000.0, error_sink=None, **kwargs):
        self._inner = StationLP(lp_id=lp_id, t_end=t_end, **kwargs)
        super().__init__(lp_id=lp_id, initial_state=self._inner.state, t_end=t_end, error_sink=error_sink)
        self._inner.send_event = self.send_event

    def initialize(self) -> None:
        self._inner.initialize()

    def on_event_safe(self, event: Event) -> None:
        self.local_virt_time = event.timestamp
        self._inner.handle_event(event)

    def finalize(self) -> None:
        self._inner.finalize()

    def get_statistics(self) -> Dict[str, Any]:
        return self._inner.get_statistics()


class CoPickupLP(SafeCoLogicalProcess):
    """
    LP4 (Coroutine): Bọc trực tiếp PickupLP và bổ sung cơ chế BkSysFuture + asyncio.Task tại bảng Join:
    - Nhánh đến trước tạo BkSysFuture và tạm dừng tại `await join_future`.
    - Nhánh đến sau gọi `join_future.set_result(t)` đánh thức coroutine hoàn tất join qua PickupLP._complete_join().
    """

    def __init__(self, lp_id: int = LPID.PICKUP, t_end: float = 10000.0, error_sink=None, **kwargs):
        self._inner = PickupLP(lp_id=lp_id, t_end=t_end, **kwargs)
        super().__init__(lp_id=lp_id, initial_state=self._inner.state, t_end=t_end, error_sink=error_sink)
        self._inner.send_event = self.send_event
        self._join_futures: Dict[int, BkSysFuture] = {}
        self._join_tasks: Set[asyncio.Task] = set()
        self.futures_resolved: int = 0

    def initialize(self) -> None:
        self._inner.initialize()

    async def on_coroutine_run(self) -> None:
        try:
            await super().on_coroutine_run()
        finally:
            pending = [t for t in self._join_tasks if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._join_tasks.clear()

    def _register_join_future(self, car_id: int) -> None:
        fut = self.create_bksys_future()
        self._join_futures[car_id] = fut
        task = asyncio.create_task(self._await_join_future(car_id, fut))
        self._join_tasks.add(task)
        task.add_done_callback(self._join_tasks.discard)

    async def _await_join_future(self, car_id: int, fut: BkSysFuture) -> None:
        try:
            join_t: float = await fut
            entry = self._inner.state.join_table.get(car_id)
            if entry is not None and entry.xe_den and entry.do_xong:
                self._inner._update_integrals(join_t)
                self._inner._update_join_integral(join_t)
                self._inner._complete_join(car_id, entry, join_t)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error_sink.append(exc)
            raise

    def on_event_safe(self, event: Event) -> None:
        et = event.event_type
        if et not in (EventType.TRANSFER.value, EventType.FOOD_READY.value):
            self.local_virt_time = event.timestamp
            self._inner.handle_event(event)
            return

        t = event.timestamp
        self._inner._guard_monotonic_time(t, et)
        self.local_virt_time = t
        self._inner.local_virt_time = t
        self._inner._update_integrals(t)
        self._inner._update_join_integral(t)

        if et == EventType.TRANSFER.value:
            car: CarRecord = event.payload
            entry = self._inner.state.join_table.get(car.car_id)
            if entry is None:
                entry = JoinEntry()
                self._inner.state.join_table[car.car_id] = entry
            entry.car = car
            entry.xe_den = True
            entry.t_p = t
            car.t_payment_done = t
            if not entry.do_xong:
                self._inner.state.waiting_food_count += 1
                self._register_join_future(car.car_id)
                return
            fut = self._join_futures.pop(car.car_id, None)
            if fut is not None and not fut.done():
                self.futures_resolved += 1
                fut.set_result(t)
            else:
                self._inner._complete_join(car.car_id, entry, t)
        else:
            food_car: CarRecord = event.payload
            entry = self._inner.state.join_table.get(food_car.car_id)
            if entry is None:
                entry = JoinEntry()
                self._inner.state.join_table[food_car.car_id] = entry
            entry.do_xong = True
            entry.t_f = t
            if not entry.xe_den:
                self._register_join_future(food_car.car_id)
                return
            self._inner.state.waiting_food_count -= 1
            fut = self._join_futures.pop(food_car.car_id, None)
            if fut is not None and not fut.done():
                self.futures_resolved += 1
                fut.set_result(t)
            else:
                self._inner._complete_join(food_car.car_id, entry, t)

    def finalize(self) -> None:
        self._inner.finalize()

    def get_statistics(self) -> Dict[str, Any]:
        stats = self._inner.get_statistics()
        stats["futures_resolved"] = self.futures_resolved
        return stats


class CoMonitorLP(SafeCoLogicalProcess):
    """LP5 (Coroutine): Bọc trực tiếp MonitorLP (hỗ trợ record_trace từng xe)."""

    def __init__(self, lp_id: int = LPID.MONITOR, t_end: float = 10000.0, error_sink=None, **kwargs):
        self._inner = MonitorLP(lp_id=lp_id, t_end=t_end, **kwargs)
        super().__init__(lp_id=lp_id, initial_state=self._inner.state, t_end=t_end, error_sink=error_sink)
        self._inner.send_event = self.send_event

    @property
    def car_records(self):
        return self._inner.car_records

    def initialize(self) -> None:
        self._inner.initialize()

    def on_event_safe(self, event: Event) -> None:
        self.local_virt_time = event.timestamp
        self._inner.handle_event(event)

    def finalize(self) -> None:
        self._inner.finalize()

    def get_statistics(self) -> Dict[str, Any]:
        return self._inner.get_statistics()


def _execute_coroutine_sim(
    params: DriveThruParams,
    seed: int,
    reverse_fork_order: bool,
    deterministic: bool,
    verify_invariants: bool,
    record_trace: bool,
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
        t_warmup=params.t_warmup, t_end=params.t_end,
        record_trace=record_trace, error_sink=error_sink,
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
    car_trace = None
    if record_trace:
        car_trace = [
            (st, c.car_id, c.t_arrive, t_done, c.food_wait_time)
            for st, t_done, c in monitor.car_records
        ]

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
        "car_trace": car_trace,
    }


def run_coroutine_engine(
    params: DriveThruParams,
    seed: int = 1,
    reverse_fork_order: bool = False,
    deterministic: bool = False,
    verify_invariants: bool = True,
    measure_memory: bool = True,
    record_trace: bool = False,
) -> EngineRunResult:
    raw, hw = measure_hardware_run(
        lambda: _execute_coroutine_sim(
            params=params,
            seed=seed,
            reverse_fork_order=reverse_fork_order,
            deterministic=deterministic,
            verify_invariants=verify_invariants,
            record_trace=record_trace,
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
        dispatcher="BkSysCoEventLoop(Composition)",
        blocking_order=params.blocking_order,
        lam=params.lam, c2=params.c2, K1=params.K1,
        t_warmup=params.t_warmup, t_end=params.t_end,
        T=sm["T"], P95_T=sm["P95_T"], P_T_gt_8=sm["P_T_gt_8"],
        P_b=s1["P_b"], X=sm["X"], W_f=s4["W_f"], P_f=s4["P_f"],
        L_f=s4["L_f"], L_system=raw["l_system"],
        U1=s1["U"], U2=s2["U"], U3=s3["U"], U4=s4["U"],
        W1=s1["W"], W2=s2["W"], W3=s3["W"], W4=s4["W"],
        Wq1=s1["W_q"], Wq2=s2["W_q"], Wq3=s3["W_q"], Wq4=s4["W_q"],
        L1=s1["L"], L2=s2["L"], L3=s3["L"], L4=s4["L"],
        X1=s1["X"], X2=s2["X"], X3=s3["X"], X4=s4["X"],
        total_generated=raw["total_generated"], total_completed=sm["total_completed"],
        total_dropped=sm["total_dropped"], n_unfinished_total=raw["n_unfinished_total"],
        n_unfinished_join=s4["n_unfinished_join"], flow_balance_ok=raw["flow_balance_ok"],
        little_err_s1=raw["little_err_s1"], little_err_s2=raw["little_err_s2"],
        little_err_s3=raw["little_err_s3"], little_err_s4=raw["little_err_s4"],
        little_err_sys=raw["little_err_sys"],
        events_processed=events_processed,
        wall_time=wall_time, cpu_time=hw["cpu_time"], cpu_wall_ratio=hw["cpu_wall_ratio"],
        events_per_sec=events_per_sec, peak_mem_mb=hw["peak_mem_mb"],
        rss_mb=hw["rss_mb"], delta_rss_mb=hw["delta_rss_mb"],
        causality_violations=0, deadlocked=False, car_trace=raw["car_trace"],
    )
