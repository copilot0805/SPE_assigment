import csv
import platform
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

from drivethru.config.simulation_config import DriveThruParams
from drivethru.engines.base import (
    EngineRunResult,
    compare_car_traces,
    compute_fidelity_error,
)
from drivethru.engines.coroutine_engine import run_coroutine_engine
from drivethru.engines.multithread_engine import run_multithread_engine
from drivethru.engines.sequential_engine import run_sequential_engine
from drivethru.metrics.stats_utils import compute_ci95

REPORTS_DIR = Path("reports")
RAW_TIMING_CSV = REPORTS_DIR / "exp_m5_raw_runs.csv"
RAW_MEM_CSV = REPORTS_DIR / "exp_m5_memory_runs.csv"
SUMMARY_CSV = REPORTS_DIR / "exp_m5_benchmark.csv"

ENGINE_RUNNERS: Dict[str, Callable[..., EngineRunResult]] = {
    "sequential": run_sequential_engine,
    "coroutine": run_coroutine_engine,
    "multithread": run_multithread_engine,
}
ENGINE_ORDER = ("sequential", "coroutine", "multithread")

# 5 kịch bản bao phủ cả 2 trục: Quy mô t_end (tại Peak lam=0.6) và Mức tải lam (tại t_end=5000)
SCENARIOS: Tuple[Tuple[str, float, float], ...] = (
    ("scale_t2000_lam06", 0.6, 2000.0),
    ("scale_t5000_lam06", 0.6, 5000.0),
    ("scale_t10000_lam06", 0.6, 10000.0),
    ("load_lam02_t5000", 0.2, 5000.0),
    ("load_lam07_t5000", 0.7, 5000.0),
)
T_WARMUP = 500.0
SEEDS = tuple(range(1, 11))   # R = 10 seeds
MEM_SEEDS = (1, 2, 3)         # 3 seeds đo heap tracemalloc + OS RSS riêng
WARMUP_SEED = 999

RAW_TIMING_FIELDS = [
    "scenario_id", "engine_name", "lam", "t_end", "seed", "events_processed",
    "wall_time", "cpu_time", "cpu_wall_ratio", "events_per_sec",
    "avg_active_lps_per_epoch", "pct_single_lp_epochs",
    "T", "P_b", "U1", "U2", "U3", "U4", "W_f", "X", "P95_T", "L_system",
    "flow_balance_ok", "little_err_sys", "causality_violations", "deadlocked",
    "max_fidelity_err", "fidelity_passed", "max_car_trace_err", "car_trace_passed",
]

RAW_MEM_FIELDS = [
    "scenario_id", "engine_name", "lam", "t_end", "seed",
    "events_processed", "peak_mem_mb",
]

SUMMARY_FIELDS = [
    "scenario_id", "engine_name", "lam", "t_end", "n_runs", "events_mean",
    "wall_time_mean", "wall_time_std", "wall_time_ci95", "slowdown_vs_seq",
    "events_per_sec_mean", "events_per_sec_ci95",
    "cpu_time_mean", "cpu_time_ci95", "cpu_wall_ratio_mean",
    "peak_mem_mb_mean", "peak_mem_mb_ci95",
    "avg_active_lps_mean", "pct_single_lp_epochs_mean",
    "max_fidelity_err", "max_car_trace_err", "fidelity_pass_rate_pct",
    "causality_error_rate_pct", "deadlock_rate_pct",
]


def _make_params(lam: float, t_end: float) -> DriveThruParams:
    return DriveThruParams(
        lam=lam, c1=2, K1=6, c2=2, c3=2, c4=2,
        t_warmup=T_WARMUP, t_end=t_end, blocking_order=False,
    )


def _load_existing_rows(csv_path: Path, required_col: str) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if required_col not in (reader.fieldnames or []):
            print(f"[WARN] File {csv_path} thiếu cột '{required_col}' (schema cũ) -> bỏ qua và đo mới.")
            return []
        return list(reader)


def _append_row(csv_path: Path, fieldnames: List[str], row: Dict[str, Any]) -> None:
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run_m5_benchmark() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 102)
    print("M5 BENCHMARK (1-CORE SEQUENTIAL PROCESS — ĐA MỨC t_end & ĐA MỨC λ, PYTHON HEAP & CAR-BY-CAR TRACE)")
    print(f"Python: {platform.python_version()} | OS: {platform.platform()}")
    print(f"Scenarios: {len(SCENARIOS)} kịch bản x 3 engines x R={len(SEEDS)} seeds (c2=2, K1=6, t_warmup={T_WARMUP:.0f})")
    print("=" * 102)

    existing_timing = _load_existing_rows(RAW_TIMING_CSV, "scenario_id")
    if not existing_timing and RAW_TIMING_CSV.exists():
        RAW_TIMING_CSV.unlink()

    done_timing: Set[Tuple[str, str, int]] = {
        (r["scenario_id"], r["engine_name"], int(r["seed"])) for r in existing_timing
    }
    baseline_cache: Dict[Tuple[str, int], Dict[str, Any]] = {
        (r["scenario_id"], int(r["seed"])): {
            k: float(r[k]) for k in ("T", "P_b", "U1", "U2", "U3", "U4", "W_f", "X", "P95_T", "L_system")
        }
        for r in existing_timing
        if r["engine_name"] == "sequential"
    }
    car_trace_baseline: Dict[str, Any] = {}

    # ---- PHA 1: TIMING & FIDELITY (tracemalloc TẮT) ----
    print("\n[PHA 1] TIMING & FIDELITY RUN (measure_memory=False -> đo wall_time sạch + kiểm trace từng xe ở seed=1)")
    for sc_id, lam, t_end in SCENARIOS:
        params = _make_params(lam, t_end)
        # Kiểm chứng car-by-car trace trên seed=1 cho kịch bản này (tách khỏi vòng đo tốc độ sạch)
        seq_tr = run_sequential_engine(params, seed=1, measure_memory=False, record_trace=True)
        car_trace_baseline[sc_id] = seq_tr.car_trace
        car_err_by_engine: Dict[str, float] = {"sequential": 0.0}
        for eng in ("coroutine", "multithread"):
            cand_tr = ENGINE_RUNNERS[eng](params, seed=1, measure_memory=False, record_trace=True)
            cmp_res = compare_car_traces(cand_tr.car_trace, seq_tr.car_trace, tol=1e-9)
            if not cmp_res["passed"]:
                raise AssertionError(f"Car-by-car trace FAILED: {sc_id}, {eng}, {cmp_res}")
            car_err_by_engine[eng] = cmp_res["max_car_err"]
        print(
            f"  [TRACE OK] {sc_id:<20} | cars={len(seq_tr.car_trace)} | "
            f"co_err={car_err_by_engine['coroutine']:.1e} | mt_err={car_err_by_engine['multithread']:.1e}"
        )

        for engine_name in ENGINE_ORDER:
            runner = ENGINE_RUNNERS[engine_name]
            missing = [s for s in SEEDS if (sc_id, engine_name, s) not in done_timing]
            if not missing:
                print(f"  [SKIP] {sc_id:<20} | {engine_name:11s} (đã đủ {len(SEEDS)} seeds)")
                continue

            _ = runner(params, seed=WARMUP_SEED, measure_memory=False, record_trace=False)
            print(f"  [RUN ] {sc_id:<20} | {engine_name:11s} | lam={lam:.1f}, t_end={t_end:5.0f} -> đo {len(missing)} seeds...")

            for seed in missing:
                res = runner(params, seed=seed, measure_memory=False, record_trace=False)
                res_dict = res.to_dict()

                if engine_name == "sequential":
                    baseline_cache[(sc_id, seed)] = res_dict
                    max_fid_err = 0.0
                    fid_passed = True
                else:
                    fid = compute_fidelity_error(res_dict, baseline_cache[(sc_id, seed)], tol=1e-9)
                    max_fid_err = fid["max_abs_err"]
                    fid_passed = fid["passed"]
                    if not fid_passed:
                        raise AssertionError(f"Fidelity FAILED: {sc_id}, {engine_name}, seed={seed}, err={max_fid_err}")

                row = {
                    "scenario_id": sc_id,
                    "engine_name": engine_name,
                    "lam": lam,
                    "t_end": t_end,
                    "seed": seed,
                    "events_processed": res.events_processed,
                    "wall_time": res.wall_time,
                    "cpu_time": res.cpu_time,
                    "cpu_wall_ratio": res.cpu_wall_ratio,
                    "events_per_sec": res.events_per_sec,
                    "avg_active_lps_per_epoch": res.avg_active_lps_per_epoch,
                    "pct_single_lp_epochs": res.pct_single_lp_epochs,
                    "T": res.T, "P_b": res.P_b,
                    "U1": res.U1, "U2": res.U2, "U3": res.U3, "U4": res.U4,
                    "W_f": res.W_f, "X": res.X, "P95_T": res.P95_T, "L_system": res.L_system,
                    "flow_balance_ok": int(res.flow_balance_ok),
                    "little_err_sys": res.little_err_sys,
                    "causality_violations": res.causality_violations,
                    "deadlocked": int(res.deadlocked),
                    "max_fidelity_err": max_fid_err,
                    "fidelity_passed": int(fid_passed),
                    "max_car_trace_err": car_err_by_engine[engine_name],
                    "car_trace_passed": 1,
                }
                _append_row(RAW_TIMING_CSV, RAW_TIMING_FIELDS, row)
                done_timing.add((sc_id, engine_name, seed))

    # ---- PHA 2: MEMORY PROFILING (tracemalloc Python Heap) ----
    existing_mem = _load_existing_rows(RAW_MEM_CSV, "scenario_id")
    if not existing_mem and RAW_MEM_CSV.exists():
        RAW_MEM_CSV.unlink()
    done_mem: Set[Tuple[str, str, int]] = {
        (r["scenario_id"], r["engine_name"], int(r["seed"])) for r in existing_mem
    }

    print(f"\n[PHA 2] MEMORY PROFILING RUN (tracemalloc Python Heap, seeds={MEM_SEEDS})")
    for sc_id, lam, t_end in SCENARIOS:
        params = _make_params(lam, t_end)
        for engine_name in ENGINE_ORDER:
            runner = ENGINE_RUNNERS[engine_name]
            missing_mem = [s for s in MEM_SEEDS if (sc_id, engine_name, s) not in done_mem]
            for seed in missing_mem:
                res = runner(params, seed=seed, measure_memory=True, record_trace=False)
                _append_row(
                    RAW_MEM_CSV,
                    RAW_MEM_FIELDS,
                    {
                        "scenario_id": sc_id,
                        "engine_name": engine_name,
                        "lam": lam,
                        "t_end": t_end,
                        "seed": seed,
                        "events_processed": res.events_processed,
                        "peak_mem_mb": res.peak_mem_mb,
                        },
                )
                done_mem.add((sc_id, engine_name, seed))

    # ---- TỔNG HỢP & IN BẢNG ----
    all_timing = _load_existing_rows(RAW_TIMING_CSV, "scenario_id")
    all_mem = _load_existing_rows(RAW_MEM_CSV, "scenario_id")

    seq_wall_by_sc: Dict[str, float] = {}
    for sc_id, _lam, _tend in SCENARIOS:
        vals = [float(r["wall_time"]) for r in all_timing if r["scenario_id"] == sc_id and r["engine_name"] == "sequential"]
        seq_wall_by_sc[sc_id] = compute_ci95(vals)["mean"]

    summary_rows: List[Dict[str, Any]] = []
    print("\n" + "=" * 128)
    print(
        f"{'Scenario':<19} | {'Engine':<11} | {'Events':>7} | {'Wall (s) ± CI95':>18} | {'Slow':>6} | "
        f"{'Thr(ev/s)':>10} | {'CPU/W':>5} | {'HeapMB':>6} | {'1LP%':>5} | {'ActLP':>5} | {'CarErr':>7}"
    )
    print("-" * 128)

    for sc_id, lam, t_end in SCENARIOS:
        for engine_name in ENGINE_ORDER:
            t_rows = [r for r in all_timing if r["scenario_id"] == sc_id and r["engine_name"] == engine_name]
            m_rows = [r for r in all_mem if r["scenario_id"] == sc_id and r["engine_name"] == engine_name]

            ci_wall = compute_ci95([float(r["wall_time"]) for r in t_rows])
            ci_thr = compute_ci95([float(r["events_per_sec"]) for r in t_rows])
            ci_cpu = compute_ci95([float(r["cpu_time"]) for r in t_rows])
            ci_ratio = compute_ci95([float(r["cpu_wall_ratio"]) for r in t_rows])
            ci_mem = compute_ci95([float(r["peak_mem_mb"]) for r in m_rows])
            ev_mean = sum(float(r["events_processed"]) for r in t_rows) / len(t_rows)
            avg_act = sum(float(r["avg_active_lps_per_epoch"]) for r in t_rows) / len(t_rows)
            pct_1lp = sum(float(r["pct_single_lp_epochs"]) for r in t_rows) / len(t_rows)
            slowdown = ci_wall["mean"] / seq_wall_by_sc[sc_id] if seq_wall_by_sc[sc_id] > 0 else 1.0
            max_fid = max(float(r["max_fidelity_err"]) for r in t_rows)
            max_car = max(float(r["max_car_trace_err"]) for r in t_rows)
            fid_pass_pct = 100.0 * sum(int(r["fidelity_passed"]) for r in t_rows) / len(t_rows)
            caus_err_pct = 100.0 * sum(1 for r in t_rows if int(r["causality_violations"]) > 0) / len(t_rows)
            deadlock_pct = 100.0 * sum(int(r["deadlocked"]) for r in t_rows) / len(t_rows)

            srow = {
                "scenario_id": sc_id,
                "engine_name": engine_name,
                "lam": lam,
                "t_end": int(t_end),
                "n_runs": len(t_rows),
                "events_mean": round(ev_mean, 1),
                "wall_time_mean": ci_wall["mean"],
                "wall_time_std": ci_wall["std"],
                "wall_time_ci95": ci_wall["half_width"],
                "slowdown_vs_seq": slowdown,
                "events_per_sec_mean": ci_thr["mean"],
                "events_per_sec_ci95": ci_thr["half_width"],
                "cpu_time_mean": ci_cpu["mean"],
                "cpu_time_ci95": ci_cpu["half_width"],
                "cpu_wall_ratio_mean": ci_ratio["mean"],
                "peak_mem_mb_mean": ci_mem["mean"],
                "peak_mem_mb_ci95": ci_mem["half_width"],
                "avg_active_lps_mean": avg_act,
                "pct_single_lp_epochs_mean": pct_1lp,
                "max_fidelity_err": max_fid,
                "max_car_trace_err": max_car,
                "fidelity_pass_rate_pct": fid_pass_pct,
                "causality_error_rate_pct": caus_err_pct,
                "deadlock_rate_pct": deadlock_pct,
            }
            summary_rows.append(srow)
            print(
                f"{sc_id:<19} | {engine_name:<11} | {ev_mean:7.0f} | "
                f"{ci_wall['mean']:7.4f} ± {ci_wall['half_width']:7.4f} | {slowdown:5.2f}x | "
                f"{ci_thr['mean']:10,.0f} | {ci_ratio['mean']:5.2f} | {ci_mem['mean']:6.3f} | "
                f"{pct_1lp:5.1f} | {avg_act:5.2f} | {max_car:7.1e}"
            )
    print("=" * 128)

    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"[OK] Đã xuất bảng tổng hợp: {SUMMARY_CSV}")


if __name__ == "__main__":
    run_m5_benchmark()
