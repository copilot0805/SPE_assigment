import bkitevsim.core  # Né Lỗi 5

from drivethru.config.simulation_config import DriveThruParams
from drivethru.engines.base import EngineRunResult, measure_hardware_run
from drivethru.experiments.run_single import run_drivethru_network


def run_sequential_engine(
    params: DriveThruParams,
    seed: int = 1,
    dispatcher: str = "sequential",
    reverse_fork_order: bool = False,
    deterministic: bool = False,
    verify_invariants: bool = True,
    measure_memory: bool = True,
    record_trace: bool = False,
) -> EngineRunResult:
    raw, hw = measure_hardware_run(
        lambda: run_drivethru_network(
            params=params,
            seed=seed,
            dispatcher=dispatcher,
            reverse_fork_order=reverse_fork_order,
            deterministic=deterministic,
            verify_invariants=verify_invariants,
            record_trace=record_trace,
        ),
        measure_memory=measure_memory,
    )

    events_processed = int(raw["events_processed"])
    wall_time = hw["wall_time"]
    events_per_sec = events_processed / wall_time if wall_time > 0.0 else 0.0
    car_trace = None
    if record_trace and "car_records" in raw:
        car_trace = [
            (st, c.car_id, c.t_arrive, t_done, c.food_wait_time)
            for st, t_done, c in raw["car_records"]
        ]

    return EngineRunResult(
        engine_name="sequential",
        seed=seed,
        dispatcher=dispatcher,
        blocking_order=params.blocking_order,
        lam=params.lam, c2=params.c2, K1=params.K1,
        t_warmup=params.t_warmup, t_end=params.t_end,
        T=raw["T"], P95_T=raw["P95_T"], P_T_gt_8=raw["P_T_gt_8"],
        P_b=raw["P_b"], X=raw["X"], W_f=raw["W_f"], P_f=raw["P_f"],
        L_f=raw["L_f"], L_system=raw["L_system"],
        U1=raw["U1"], U2=raw["U2"], U3=raw["U3"], U4=raw["U4"],
        W1=raw["W1"], W2=raw["W2"], W3=raw["W3"], W4=raw["W4"],
        Wq1=raw["Wq1"], Wq2=raw["Wq2"], Wq3=raw["Wq3"], Wq4=raw["Wq4"],
        L1=raw["L1"], L2=raw["L2"], L3=raw["L3"], L4=raw["L4"],
        X1=raw["X1"], X2=raw["X2"], X3=raw["X3"], X4=raw["X4"],
        total_generated=raw["total_generated"], total_completed=raw["total_completed"],
        total_dropped=raw["total_dropped"], n_unfinished_total=raw["n_unfinished_total"],
        n_unfinished_join=raw["n_unfinished_join"], flow_balance_ok=raw["flow_balance_ok"],
        little_err_s1=raw["little_err_s1"], little_err_s2=raw["little_err_s2"],
        little_err_s3=raw["little_err_s3"], little_err_s4=raw["little_err_s4"],
        little_err_sys=raw["little_err_sys"],
        events_processed=events_processed,
        wall_time=wall_time, cpu_time=hw["cpu_time"], cpu_wall_ratio=hw["cpu_wall_ratio"],
        events_per_sec=events_per_sec, peak_mem_mb=hw["peak_mem_mb"],
        rss_mb=hw["rss_mb"], delta_rss_mb=hw["delta_rss_mb"],
        causality_violations=0, deadlocked=False, car_trace=car_trace,
    )
