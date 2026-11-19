import math
import time
from typing import Any, Dict

from bkitevsim.core import Simulation, SimulationOptions
from drivethru.config.simulation_config import DriveThruParams, safe_bucket_width
from drivethru.core.event_types import EventType, LPID
from drivethru.metrics.analytical import analytical_fork_join_network
from drivethru.metrics.statistics import check_littles_law
from drivethru.models.car_source import CarSourceLP
from drivethru.models.monitor import MonitorLP
from drivethru.models.pickup import PickupLP
from drivethru.models.station import StationLP


def run_drivethru_network(
    params: DriveThruParams,
    seed: int = 1,
    dispatcher: str = "sequential",
    reverse_fork_order: bool = False,
    deterministic: bool = False,
    verify_invariants: bool = True,
) -> Dict[str, Any]:
    """
    Khởi tạo một đối tượng Simulation mới, ghép mạng Drive-thru 4 trạm (6 LPs)
    và thực thi 1 lượt mô phỏng hoàn chỉnh.
    """
    t0 = time.perf_counter()
    options = SimulationOptions(
        end_time=params.t_end,
        dispatcher=dispatcher,
        bucket_width=safe_bucket_width(params.t_end),
        log_level="ERROR",
    )
    sim = Simulation(
        options,
        models={
            "Source": CarSourceLP,
            "Station": StationLP,
            "Pickup": PickupLP,
            "Monitor": MonitorLP,
        },
    )

    mean_services = {
        1: params.mean_s1,
        2: params.mean_s2,
        3: params.mean_s3,
        4: params.mean_s4,
    }

    # LP0: CarSourceLP
    src = sim.create_lp(
        LPID.CAR_SOURCE,
        "Source",
        lam=params.lam,
        mean_services=mean_services,
        target_lp_id=LPID.ORDER,
        t_warmup=params.t_warmup,
        t_end=params.t_end,
        seed=seed,
        deterministic=deterministic,
    )

    # LP1: Order (M/M/c1/K1) — hỗ trợ đảo thứ tự gửi event trễ 0 để kiểm thử tính bất biến
    order_targets = [
        (LPID.PAYMENT, EventType.TRANSFER.value),
        (LPID.KITCHEN, EventType.ORDER_PLACED.value),
    ]
    if reverse_fork_order:
        order_targets.reverse()

    order = sim.create_lp(
        LPID.ORDER,
        "Station",
        station_idx=1,
        c=params.c1,
        K=params.K1,
        mean_service_time=params.mean_s1,
        out_targets=order_targets,
        monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup,
        t_end=params.t_end,
        blocking_order=params.blocking_order,
    )

    # LP2: Payment (M/M/c2)
    payment = sim.create_lp(
        LPID.PAYMENT,
        "Station",
        station_idx=2,
        c=params.c2,
        K=math.inf,
        mean_service_time=params.mean_s2,
        out_targets=[(LPID.PICKUP, EventType.TRANSFER.value)],
        monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup,
        t_end=params.t_end,
    )

    # LP3: Kitchen (M/M/c3) — nếu blocking_order=True thì gửi FOOD_READY về cả Order lẫn Pickup
    kitchen_targets = [(LPID.PICKUP, EventType.FOOD_READY.value)]
    if params.blocking_order:
        kitchen_targets = [
            (LPID.ORDER, EventType.FOOD_READY.value),
            (LPID.PICKUP, EventType.FOOD_READY.value),
        ]

    kitchen = sim.create_lp(
        LPID.KITCHEN,
        "Station",
        station_idx=3,
        c=params.c3,
        K=math.inf,
        mean_service_time=params.mean_s3,
        out_targets=kitchen_targets,
        monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup,
        t_end=params.t_end,
    )

    # LP4: PickupLP(StationLP) (M/M/c4 kèm bảng Join)
    pickup = sim.create_lp(
        LPID.PICKUP,
        "Pickup",
        station_idx=4,
        c=params.c4,
        K=math.inf,
        mean_service_time=params.mean_s4,
        out_targets=[(LPID.MONITOR, EventType.DEPARTURE.value)],
        monitor_lp_id=LPID.MONITOR,
        t_warmup=params.t_warmup,
        t_end=params.t_end,
    )

    # LP5: MonitorLP
    monitor = sim.create_lp(
        LPID.MONITOR,
        "Monitor",
        t_warmup=params.t_warmup,
        t_end=params.t_end,
    )

    sim_stats = sim.run()
    wall_time = time.perf_counter() - t0

    s1 = order.get_statistics()
    s2 = payment.get_statistics()
    s3 = kitchen.get_statistics()
    s4 = pickup.get_statistics()
    sm = monitor.get_statistics()

    # Tổng số xe chưa hoàn thành trên đường xe vật lý: Order + Payment + bãi chờ đồ (xe_den==True) + Pickup
    n_unfinished_total = (
        s1["n_unfinished"]
        + s2["n_unfinished"]
        + s4["n_unfinished_join"]
        + s4["n_unfinished"]
    )
    flow_balance_car = (
        src.total_generated == s1["total_arrived"]
        and s1["total_arrived"] == (sm["total_completed"] + sm["total_dropped"] + n_unfinished_total)
    )

    # Cân bằng riêng nhánh đơn hàng tại Kitchen
    orders_sent_to_kitchen = s1["total_served"] + len(order.state.waiting_food_cars)
    flow_balance_kitchen = (
        orders_sent_to_kitchen == s3["total_arrived"]
        and s3["total_arrived"] == (s3["total_served"] + s3["n_unfinished"])
    )

    # Độ dài trung bình toàn mạng vật lý: L_system = L1 + L2 + L_f + L4
    l_system = s1["L"] + s2["L"] + s4["L_f"] + s4["L"]
    little_s1 = check_littles_law(s1["L"], s1["X"], s1["W"], tol=0.01)
    little_s2 = check_littles_law(s2["L"], s2["X"], s2["W"], tol=0.01)
    little_s3 = check_littles_law(s3["L"], s3["X"], s3["W"], tol=0.01)
    little_s4 = check_littles_law(s4["L"], s4["X"], s4["W"], tol=0.01)
    little_sys = check_littles_law(l_system, sm["X"], sm["T"], tol=0.01)

    if verify_invariants:
        assert flow_balance_car, (
            f"Vi phạm cân bằng dòng xe: gen={src.total_generated}, arr1={s1['total_arrived']}, "
            f"comp={sm['total_completed']}, drop={sm['total_dropped']}, unfin={n_unfinished_total}"
        )
        assert flow_balance_kitchen, (
            f"Vi phạm cân bằng đơn Kitchen: sent={orders_sent_to_kitchen}, "
            f"k_arr={s3['total_arrived']}, k_srv={s3['total_served']}, k_unfin={s3['n_unfinished']}"
        )

    events_processed = sim_stats.get("events_processed", 0) if isinstance(sim_stats, dict) else 0

    return {
        "seed": seed,
        "dispatcher": dispatcher,
        "blocking_order": params.blocking_order,
        "lam": params.lam,
        "c2": params.c2,
        "K1": params.K1,
        # Các chỉ số chính toàn hệ thống (P_b chuẩn lấy từ trạm Order)
        "T": sm["T"],
        "P95_T": sm["P95_T"],
        "P_T_gt_8": sm["P_T_gt_8"],
        "P_b": s1["P_b"],
        "X": sm["X"],
        "W_f": s4["W_f"],
        "P_f": s4["P_f"],
        "L_f": s4["L_f"],
        "L_system": l_system,
        # Chỉ số từng trạm
        "U1": s1["U"], "U2": s2["U"], "U3": s3["U"], "U4": s4["U"],
        "W1": s1["W"], "W2": s2["W"], "W3": s3["W"], "W4": s4["W"],
        "Wq1": s1["W_q"], "Wq2": s2["W_q"], "Wq3": s3["W_q"], "Wq4": s4["W_q"],
        "L1": s1["L"], "L2": s2["L"], "L3": s3["L"], "L4": s4["L"],
        "X1": s1["X"], "X2": s2["X"], "X3": s3["X"], "X4": s4["X"],
        # Bộ đếm bảo toàn dòng & Little
        "total_generated": src.total_generated,
        "total_completed": sm["total_completed"],
        "total_dropped": sm["total_dropped"],
        "n_unfinished_total": n_unfinished_total,
        "n_unfinished_join": s4["n_unfinished_join"],
        "flow_balance_ok": flow_balance_car and flow_balance_kitchen,
        "little_err_s1": little_s1["rel_error"],
        "little_err_s2": little_s2["rel_error"],
        "little_err_s3": little_s3["rel_error"],
        "little_err_s4": little_s4["rel_error"],
        "little_err_sys": little_sys["rel_error"],
        # Hiệu năng trình mô phỏng
        "events_processed": events_processed,
        "wall_time": wall_time,
    }


if __name__ == "__main__":
    params = DriveThruParams(lam=0.6, c2=2, K1=8, t_warmup=2000.0, t_end=10000.0)
    res = run_drivethru_network(params, seed=1)
    approx = analytical_fork_join_network(
        params.lam,
        params.c1, params.K1, params.mean_s1,
        params.c2, params.mean_s2,
        params.c3, params.mean_s3,
        params.c4, params.mean_s4,
    )
    print("=" * 72)
    print(f"CHẠY THỬ 1 LƯỢT MẠNG DRIVE-THRU 4 TRẠM (lam={params.lam}, c2={params.c2}, K1={params.K1}, seed=1)")
    print("=" * 72)
    print(f"Thời gian end-to-end T  : {res['T']:.4f} phút (Xấp xỉ Fork-Join: {approx['T_approx']:.4f} phút)")
    print(f"P95(T)                  : {res['P95_T']:.4f} phút | P(T > 8): {res['P_T_gt_8']*100:.2f}%")
    print(f"Xác suất từ chối P_b    : {res['P_b']*100:.3f}% (Lý thuyết Order: {approx['P_b']*100:.3f}%)")
    print(f"Chờ đồ tại Join W_f     : {res['W_f']:.4f} phút | P_f: {res['P_f']*100:.2f}% | L_f: {res['L_f']:.4f}")
    print(f"Utilization U1..U4      : U1={res['U1']:.3f}, U2={res['U2']:.3f}, U3={res['U3']:.3f}, U4={res['U4']:.3f}")
    print(f"L_system = L1+L2+Lf+L4  : {res['L_system']:.4f} | X * T = {res['X']*res['T']:.4f} (Little lệch {res['little_err_sys']*100:.3f}%)")
    print(f"Cân bằng dòng           : {'PASS' if res['flow_balance_ok'] else 'FAIL'} "
          f"(gen={res['total_generated']}, comp={res['total_completed']}, drop={res['total_dropped']}, unfin={res['n_unfinished_total']})")
    print(f"Wall time               : {res['wall_time']:.3f}s")
    print("=" * 72)
