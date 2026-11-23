import bkitevsim.core  # Né Lỗi 5

import math
import threading
from typing import Any, Dict, List, Optional

from bkitevsim.core import BkSysLogicalProcess, Event
from bkitevsim.queues import LadderQueue
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.core.event_types import EventType, LPID
from drivethru.engines.base import EngineRunResult, get_process_rss_mb, measure_hardware_run
from drivethru.metrics.stats_utils import check_littles_law
from drivethru.models.car_source import CarSourceLP
from drivethru.models.monitor import MonitorLP
from drivethru.models.pickup import PickupLP
from drivethru.models.station import StationLP


class LPWorkerThread(threading.Thread):
    def __init__(self, lp: BkSysLogicalProcess, coordinator: "ThreadedClockCoordinator"):
        super().__init__(name=f"LP-{lp.lp_id}-Thread", daemon=True)
        self.lp = lp
        self.coordinator = coordinator
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._inbox: List[Event] = []
        self._has_work: bool = False
        self._do_init: bool = False
        self._stop_requested: bool = False
        self.outbox: List[Event] = []
        self.lp.send_event = self.outbox.append

    def trigger_initialize(self) -> None:
        with self._cond:
            self._do_init = True
            self._cond.notify()

    def dispatch_batch(self, events: List[Event]) -> None:
        with self._cond:
            self._inbox = events
            self._has_work = True
            self._cond.notify()

    def request_stop(self) -> None:
        with self._cond:
            self._stop_requested = True
            self._cond.notify()

    def run(self) -> None:
        while True:
            with self._cond:
                while not (self._do_init or self._has_work or self._stop_requested):
                    self._cond.wait()
                if self._stop_requested:
                    return
                do_init = self._do_init
                self._do_init = False
                batch = self._inbox if self._has_work else []
                self._inbox = []
                self._has_work = False

            self.outbox.clear()
            err: Optional[Exception] = None
            try:
                if do_init:
                    self.lp.initialize()
                else:
                    for ev in batch:
                        self.lp.set_local_virt_time(ev.timestamp)
                        self.lp.handle_event(ev)
            except Exception as exc:
                err = exc
            finally:
                self.coordinator.notify_worker_done(self.lp.lp_id, self.outbox, err)


class ThreadedClockCoordinator:
    """
    Bộ điều phối đồng bộ bảo thủ không có lookahead (zero-lookahead conservative barrier) cho 6 OS threads.
    Ghi nhận thêm số LP hoạt động trung bình mỗi nhịp đồng bộ (để phân tích trần song song hóa ~1.2x).
    """

    def __init__(self, lps: Dict[int, BkSysLogicalProcess], end_time: float, bucket_width: float):
        self.lps = lps
        self.end_time = end_time
        self.event_queue: LadderQueue[Event] = LadderQueue(bucket_width=bucket_width)
        self.current_time: float = 0.0
        self.events_processed: int = 0
        self.causality_violations: int = 0
        self.deadlocked: bool = False
        self.errors: List[Exception] = []

        self.epochs_count: int = 0
        self.single_lp_epochs: int = 0
        self.total_active_lps: int = 0
        self.live_rss_mb: float = 0.0

        self._barrier_lock = threading.Lock()
        self._barrier_cond = threading.Condition(self._barrier_lock)
        self._pending_workers: int = 0
        self._epoch_outboxes: Dict[int, List[Event]] = {}
        self.workers: Dict[int, LPWorkerThread] = {
            lp_id: LPWorkerThread(lp, self) for lp_id, lp in sorted(lps.items())
        }

    def notify_worker_done(self, lp_id: int, outbox: List[Event], err: Optional[Exception]) -> None:
        with self._barrier_cond:
            if outbox:
                self._epoch_outboxes[lp_id] = list(outbox)
            if err is not None:
                self.errors.append(err)
            self._pending_workers -= 1
            if self._pending_workers == 0:
                self._barrier_cond.notify()

    def _wait_epoch_done(self, timeout_sec: float = 30.0) -> None:
        with self._barrier_cond:
            ok = self._barrier_cond.wait_for(lambda: self._pending_workers == 0, timeout=timeout_sec)
            if not ok:
                self.deadlocked = True
                raise TimeoutError("Deadlock phát hiện tại barrier của ThreadedClockCoordinator!")

            for lp_id in sorted(self._epoch_outboxes.keys()):
                for ev in self._epoch_outboxes[lp_id]:
                    self.event_queue.push(ev)
            self._epoch_outboxes.clear()

            if self.errors:
                first_err = self.errors[0]
                raise RuntimeError(
                    f"[ThreadedClockCoordinator] Worker thread gặp lỗi: "
                    f"{type(first_err).__name__}: {first_err}"
                ) from first_err

    def _pop_min_timestamp_batch(self) -> Optional[Dict[int, List[Event]]]:
        first_ts = self.event_queue.peek_timestamp()
        if first_ts is None or first_ts > self.end_time:
            return None

        first_ev = self.event_queue.pop()
        if first_ev is None or first_ev.timestamp > self.end_time:
            return None

        t_min = first_ev.timestamp
        if t_min < self.current_time - 1e-12:
            self.causality_violations += 1
        self.current_time = t_min

        grouped: Dict[int, List[Event]] = {first_ev.receiver_id: [first_ev]}
        self.events_processed += 1

        while True:
            next_ts = self.event_queue.peek_timestamp()
            if next_ts is None or next_ts > t_min:
                break
            ev = self.event_queue.pop()
            if ev is None:
                break
            grouped.setdefault(ev.receiver_id, []).append(ev)
            self.events_processed += 1

        return grouped

    def run(self) -> Dict[str, Any]:
        for worker in self.workers.values():
            worker.start()

        try:
            with self._barrier_cond:
                self._pending_workers = len(self.workers)
                self._epoch_outboxes.clear()
            for worker in self.workers.values():
                worker.trigger_initialize()
            self._wait_epoch_done()

            while True:
                grouped = self._pop_min_timestamp_batch()
                if grouped is None:
                    break

                valid_targets = [
                    (lp_id, batch)
                    for lp_id, batch in grouped.items()
                    if lp_id in self.workers
                ]
                if not valid_targets:
                    continue

                n_active = len(valid_targets)
                self.epochs_count += 1
                self.total_active_lps += n_active
                if n_active == 1:
                    self.single_lp_epochs += 1

                with self._barrier_cond:
                    self._pending_workers = n_active
                    self._epoch_outboxes.clear()

                for lp_id, batch in valid_targets:
                    self.workers[lp_id].dispatch_batch(batch)

                self._wait_epoch_done()

            # Lấy mẫu OS RSS khi cả 6 OS threads vẫn đang sống (bao gồm stack của 6 thread)
            self.live_rss_mb = get_process_rss_mb()

        finally:
            for worker in self.workers.values():
                worker.request_stop()
            for worker in self.workers.values():
                worker.join(timeout=5.0)
                if worker.is_alive():
                    self.deadlocked = True

        for lp in self.lps.values():
            lp.finalize()

        avg_active = self.total_active_lps / self.epochs_count if self.epochs_count > 0 else 1.0
        pct_single = 100.0 * self.single_lp_epochs / self.epochs_count if self.epochs_count > 0 else 100.0
        return {
            "events_processed": self.events_processed,
            "causality_violations": self.causality_violations,
            "deadlocked": self.deadlocked,
            "avg_active_lps_per_epoch": avg_active,
            "pct_single_lp_epochs": pct_single,
            "live_rss_mb": self.live_rss_mb,
        }


def _execute_multithread_sim(
    params: DriveThruParams,
    seed: int,
    reverse_fork_order: bool,
    deterministic: bool,
    verify_invariants: bool,
    record_trace: bool,
) -> Dict[str, Any]:
    mean_services = {1: params.mean_s1, 2: params.mean_s2, 3: params.mean_s3, 4: params.mean_s4}
    src = CarSourceLP(
        lp_id=LPID.CAR_SOURCE, lam=params.lam, mean_services=mean_services,
        target_lp_id=LPID.ORDER, t_warmup=params.t_warmup, t_end=params.t_end,
        seed=seed, deterministic=deterministic,
    )

    order_targets = [(LPID.PAYMENT, EventType.TRANSFER.value), (LPID.KITCHEN, EventType.ORDER_PLACED.value)]
    if reverse_fork_order:
        order_targets.reverse()

    order = StationLP(
        lp_id=LPID.ORDER, station_idx=1, c=params.c1, K=params.K1,
        mean_service_time=params.mean_s1, out_targets=order_targets,
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
        blocking_order=params.blocking_order,
    )
    payment = StationLP(
        lp_id=LPID.PAYMENT, station_idx=2, c=params.c2, K=math.inf,
        mean_service_time=params.mean_s2, out_targets=[(LPID.PICKUP, EventType.TRANSFER.value)],
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
    )
    kitchen_targets = [(LPID.PICKUP, EventType.FOOD_READY.value)]
    if params.blocking_order:
        kitchen_targets = [(LPID.ORDER, EventType.FOOD_READY.value), (LPID.PICKUP, EventType.FOOD_READY.value)]
    kitchen = StationLP(
        lp_id=LPID.KITCHEN, station_idx=3, c=params.c3, K=math.inf,
        mean_service_time=params.mean_s3, out_targets=kitchen_targets,
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
    )
    pickup = PickupLP(
        lp_id=LPID.PICKUP, station_idx=4, c=params.c4, K=math.inf,
        mean_service_time=params.mean_s4, out_targets=[(LPID.MONITOR, EventType.DEPARTURE.value)],
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
    )
    monitor = MonitorLP(
        lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
        record_trace=record_trace,
    )

    lps: Dict[int, BkSysLogicalProcess] = {
        LPID.CAR_SOURCE: src, LPID.ORDER: order, LPID.PAYMENT: payment,
        LPID.KITCHEN: kitchen, LPID.PICKUP: pickup, LPID.MONITOR: monitor,
    }
    coordinator = ThreadedClockCoordinator(
        lps=lps, end_time=params.t_end, bucket_width=safe_bucket_width(params.t_end),
    )
    coord_stats = coordinator.run()

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
        assert flow_balance_car, "Vi phạm cân bằng dòng xe ở OS Multi-thread Engine!"
        assert flow_balance_kitchen, "Vi phạm cân bằng dòng đơn bếp ở OS Multi-thread Engine!"
        assert coord_stats["causality_violations"] == 0, "Phát hiện vi phạm nhân quả!"
        assert not coord_stats["deadlocked"], "Phát hiện Deadlock!"

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
        "events_processed": coord_stats["events_processed"],
        "causality_violations": coord_stats["causality_violations"],
        "deadlocked": coord_stats["deadlocked"],
        "avg_active_lps_per_epoch": coord_stats["avg_active_lps_per_epoch"],
        "pct_single_lp_epochs": coord_stats["pct_single_lp_epochs"],
        "live_rss_mb": coord_stats["live_rss_mb"],
        "car_trace": car_trace,
    }


def run_multithread_engine(
    params: DriveThruParams,
    seed: int = 1,
    reverse_fork_order: bool = False,
    deterministic: bool = False,
    verify_invariants: bool = True,
    measure_memory: bool = True,
    record_trace: bool = False,
) -> EngineRunResult:
    raw, hw = measure_hardware_run(
        lambda: _execute_multithread_sim(
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
    rss_peak = max(hw["rss_mb"], raw["live_rss_mb"])

    return EngineRunResult(
        engine_name="multithread",
        seed=seed,
        dispatcher="ThreadedClockCoordinator(6 OS Threads)",
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
        rss_mb=rss_peak, delta_rss_mb=hw["delta_rss_mb"],
        avg_active_lps_per_epoch=raw["avg_active_lps_per_epoch"],
        pct_single_lp_epochs=raw["pct_single_lp_epochs"],
        causality_violations=raw["causality_violations"],
        deadlocked=raw["deadlocked"], car_trace=raw["car_trace"],
    )
