import math
import time
from typing import Any, Dict, Iterable, List

from bkitevsim.core import BkSysLogicalProcess, Simulation, SimulationOptions
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.core.event_types import EventType, LPID
from drivethru.metrics.analytical import analytical_fork_join_network
from drivethru.metrics.stats_utils import check_littles_law
from drivethru.models.car_source import CarSourceLP
from drivethru.models.monitor import MonitorLP
from drivethru.models.pickup import PickupLP
from drivethru.models.station import StationLP


def attach_global_monotonic_guard(lps: Iterable[BkSysLogicalProcess]) -> List[float]:
    """Chốt chặn lúc chạy toàn cục: bọc handle_event() của mọi LP bằng 1 biến thời gian chung."""
    last_global_t = [-math.inf]
    for lp in lps:
        orig_handle = lp.handle_event

        def _guarded(ev, _orig=orig_handle, _lp_id=lp.lp_id):
            if ev.timestamp < last_global_t[0] - 1e-12:
                raise RuntimeError(
                    f"Thời gian toàn cục đi lùi tại LP {_lp_id}: "
                    f"t={ev.timestamp:.6f} < global_last_t={last_global_t[0]:.6f} "
                    f"({ev.event_type}) — kiểm tra bucket_width!"
                )
            last_global_t[0] = ev.timestamp
            return _orig(ev)

        lp.handle_event = _guarded
    return last_global_t


def attach_event_logger(lps: Iterable[BkSysLogicalProcess], monitor: MonitorLP) -> None:
    """Gắn móc ghi nhật ký mọi event qua MonitorLP.log_event() khi record_event_log=True."""
    for lp in lps:
        orig_handle = lp.handle_event

        def _logged(ev, _orig=orig_handle):
            monitor.log_event(ev)
            return _orig(ev)

        lp.handle_event = _logged


def run_drivethru_network(
    params: DriveThruParams,
    seed: int = 1,
    dispatcher: str = "sequential",
    reverse_fork_order: bool = False,
    deterministic: bool = False,
    verify_invariants: bool = True,
    record_trace: bool = False,
    record_event_log: bool = False,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    options = SimulationOptions(
        end_time=params.t_end,
        dispatcher=dispatcher,
        bucket_width=safe_bucket_width(params.t_end),
        log_level="ERROR",
    )
    sim = Simulation(
        options,
        models={"Source": CarSourceLP, "Station": StationLP, "Pickup": PickupLP, "Monitor": MonitorLP},
    )

    mean_services = {1: params.mean_s1, 2: params.mean_s2, 3: params.mean_s3, 4: params.mean_s4}
    src = sim.create_lp(
        LPID.CAR_SOURCE, "Source", lam=params.lam, mean_services=mean_services,
        target_lp_id=LPID.ORDER, t_warmup=params.t_warmup, t_end=params.t_end,
        seed=seed, deterministic=deterministic,
    )

    order_targets = [(LPID.PAYMENT, EventType.TRANSFER.value), (LPID.KITCHEN, EventType.ORDER_PLACED.value)]
    if reverse_fork_order:
        order_targets.reverse()

    order = sim.create_lp(
        LPID.ORDER, "Station", station_idx=1, c=params.c1, K=params.K1,
        mean_service_time=params.mean_s1, out_targets=order_targets,
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
        blocking_order=params.blocking_order,
    )
    payment = sim.create_lp(
        LPID.PAYMENT, "Station", station_idx=2, c=params.c2, K=math.inf,
        mean_service_time=params.mean_s2, out_targets=[(LPID.PICKUP, EventType.TRANSFER.value)],
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
    )
    kitchen_targets = [(LPID.PICKUP, EventType.FOOD_READY.value)]
    if params.blocking_order:
        kitchen_targets = [(LPID.ORDER, EventType.FOOD_READY.value), (LPID.PICKUP, EventType.FOOD_READY.value)]
    kitchen = sim.create_lp(
        LPID.KITCHEN, "Station", station_idx=3, c=params.c3, K=math.inf,
        mean_service_time=params.mean_s3, out_targets=kitchen_targets,
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
    )
    pickup = sim.create_lp(
        LPID.PICKUP, "Pickup", station_idx=4, c=params.c4, K=math.inf,
        mean_service_time=params.mean_s4, out_targets=[(LPID.MONITOR, EventType.DEPARTURE.value)],
        monitor_lp_id=LPID.MONITOR, t_warmup=params.t_warmup, t_end=params.t_end,
    )
    monitor = sim.create_lp(
        LPID.MONITOR, "Monitor",
        t_warmup=params.t_warmup, t_end=params.t_end,
        record_trace=record_trace, record_event_log=record_event_log,
    )

    all_lps = (src, order, payment, kitchen, pickup, monitor)
    if record_event_log:
        attach_event_logger(all_lps, monitor)
    if verify_invariants:
        attach_global_monotonic_guard(all_lps)

    sim_stats = sim.run()
    wall_time = time.perf_counter() - t0

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
        assert flow_balance_car
        assert flow_balance_kitchen

    events_processed = sim_stats.get("events_processed", 0) if isinstance(sim_stats, dict) else 0
    out: Dict[str, Any] = {
        "seed": seed, "dispatcher": dispatcher, "blocking_order": params.blocking_order,
        "lam": params.lam, "c2": params.c2, "K1": params.K1,
        "T": sm["T"], "P95_T": sm["P95_T"], "P_T_gt_8": sm["P_T_gt_8"],
        "P_b": s1["P_b"], "X": sm["X"], "W_f": s4["W_f"], "P_f": s4["P_f"], "L_f": s4["L_f"], "L_system": l_system,
        "U1": s1["U"], "U2": s2["U"], "U3": s3["U"], "U4": s4["U"],
        "W1": s1["W"], "W2": s2["W"], "W3": s3["W"], "W4": s4["W"],
        "Wq1": s1["W_q"], "Wq2": s2["W_q"], "Wq3": s3["W_q"], "Wq4": s4["W_q"],
        "L1": s1["L"], "L2": s2["L"], "L3": s3["L"], "L4": s4["L"],
        "X1": s1["X"], "X2": s2["X"], "X3": s3["X"], "X4": s4["X"],
        "total_generated": src.total_generated, "total_completed": sm["total_completed"],
        "total_dropped": sm["total_dropped"], "n_unfinished_total": n_unfinished_total,
        "n_unfinished_join": s4["n_unfinished_join"],
        "flow_balance_ok": flow_balance_car and flow_balance_kitchen,
        "little_err_s1": little_s1["rel_error"], "little_err_s2": little_s2["rel_error"],
        "little_err_s3": little_s3["rel_error"], "little_err_s4": little_s4["rel_error"],
        "little_err_sys": little_sys["rel_error"],
        "events_processed": events_processed, "wall_time": wall_time,
    }
    if record_trace:
        out["departure_trace"] = monitor.departure_trace
        out["car_records"] = monitor.car_records
    if record_event_log:
        out["event_log"] = monitor.event_log
    return out


if __name__ == "__main__":
    p = DriveThruParams(lam=0.6, c2=2, K1=8, t_warmup=2000.0, t_end=10000.0)
    res = run_drivethru_network(p, seed=1)
    approx = analytical_fork_join_network(p.lam, p.c1, p.K1, p.mean_s1, p.c2, p.mean_s2, p.c3, p.mean_s3, p.c4, p.mean_s4)
    print(
        f"T={res['T']:.4f} (approx={approx['T_approx']:.4f}), Pb={res['P_b']*100:.2f}%, "
        f"Little_err={res['little_err_sys']*100:.3f}%, flow_ok={res['flow_balance_ok']}, wall={res['wall_time']:.3f}s"
    )
