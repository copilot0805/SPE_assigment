import csv
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

from drivethru.config.simulation_config import DriveThruParams
from drivethru.engines.base import EngineRunResult, compute_fidelity_error
from drivethru.engines.coroutine_engine import run_coroutine_engine
from drivethru.engines.multithread_engine import run_multithread_engine
from drivethru.engines.sequential_engine import run_sequential_engine
from drivethru.metrics.statistics import compute_ci95

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
T_END_LEVELS = (2000.0, 5000.0, 10000.0)
T_WARMUP = 500.0
SEEDS = tuple(range(1, 11))       # R = 10 seeds (Bước 8 PE)
MEM_SEEDS = (1, 2, 3)             # 3 seeds đo tracemalloc riêng (tránh observer effect vào wall_time)
WARMUP_SEED = 999                 # 1 lượt warm-up bị loại bỏ đầu mỗi cấu hình

RAW_TIMING_FIELDS = [
    "engine_name", "t_end", "seed", "events_processed",
    "wall_time", "cpu_time", "cpu_wall_ratio", "events_per_sec",
    "T", "P_b", "U1", "U2", "U3", "U4", "W_f", "X", "P95_T", "L_system",
    "flow_balance_ok", "little_err_sys", "causality_violations", "deadlocked",
    "max_fidelity_err", "fidelity_passed",
]

RAW_MEM_FIELDS = [
    "engine_name", "t_end", "seed", "events_processed", "peak_mem_mb",
]

SUMMARY_FIELDS = [
    "engine_name", "t_end", "n_runs", "events_mean",
    "wall_time_mean", "wall_time_std", "wall_time_ci95", "slowdown_vs_seq",
    "events_per_sec_mean", "events_per_sec_ci95",
    "cpu_time_mean", "cpu_time_ci95", "cpu_wall_ratio_mean",
    "peak_mem_mb_mean", "peak_mem_mb_ci95",
    "max_fidelity_err", "fidelity_pass_rate_pct",
    "causality_error_rate_pct", "deadlock_rate_pct",
]


def _make_params(t_end: float) -> DriveThruParams:
    """Cấu hình tối ưu M4 (c1=c2=c3=c4=2, K1=6) tại Peak lam=0.6."""
    return DriveThruParams(
        lam=0.6, c1=2, K1=6, c2=2, c3=2, c4=2,
        t_warmup=T_WARMUP, t_end=t_end, blocking_order=False,
    )


def _load_existing_rows(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_row(csv_path: Path, fieldnames: List[str], row: Dict[str, Any]) -> None:
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run_m5_benchmark() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("M5 BENCHMARK (1-CORE SEQUENTIAL PROCESS — NO ProcessPoolExecutor)")
    print(f"Python: {platform.python_version()} | OS: {platform.platform()}")
    print(f"Config: Peak lam=0.6, c2=2, K1=6, t_warmup={T_WARMUP:.0f} | t_end={T_END_LEVELS} | R={len(SEEDS)} seeds")
    print("=" * 84)

    # ---- PHA 1: TIMING & FIDELITY RUN (tracemalloc TẮT để tránh observer effect) ----
    existing_timing = _load_existing_rows(RAW_TIMING_CSV)
    done_timing: Set[Tuple[str, float, int]] = {
        (r["engine_name"], float(r["t_end"]), int(r["seed"])) for r in existing_timing
    }
    baseline_cache: Dict[Tuple[float, int], Dict[str, Any]] = {
        (float(r["t_end"]), int(r["seed"])): {
            k: float(r[k]) for k in ("T", "P_b", "U1", "U2", "U3", "U4", "W_f", "X", "P95_T", "L_system")
        }
        for r in existing_timing
        if r["engine_name"] == "sequential"
    }

    print("\n[PHA 1] TIMING & FIDELITY RUN (measure_memory=False -> đo tốc độ sạch 100%)")
    for t_end in T_END_LEVELS:
        params = _make_params(t_end)
        for engine_name in ENGINE_ORDER:
            runner = ENGINE_RUNNERS[engine_name]
            missing_seeds = [s for s in SEEDS if (engine_name, t_end, s) not in done_timing]
            if not missing_seeds:
                print(f"  [SKIP] {engine_name:11s} | t_end={t_end:7.0f} (đã đủ {len(SEEDS)}/{len(SEEDS)} seeds trong checkpoint)")
                continue

            # 1 lượt warm-up bỏ đi để ổn định CPU cache / Python allocator
            _ = runner(params, seed=WARMUP_SEED, measure_memory=False)
            print(f"  [RUN ] {engine_name:11s} | t_end={t_end:7.0f} | warm-up OK -> đo {len(missing_seeds)} seeds...")

            for seed in missing_seeds:
                res = runner(params, seed=seed, measure_memory=False)
                res_dict = res.to_dict()

                if engine_name == "sequential":
                    baseline_cache[(t_end, seed)] = res_dict
                    max_fid_err = 0.0
                    fid_passed = True
                else:
                    base = baseline_cache[(t_end, seed)]
                    fid = compute_fidelity_error(res_dict, base, tol=1e-9)
                    max_fid_err = fid["max_abs_err"]
                    fid_passed = fid["passed"]
                    if not fid_passed:
                        raise AssertionError(
                            f"Fidelity FAILED: engine={engine_name}, t_end={t_end}, seed={seed}, err={max_fid_err}"
                        )

                row = {
                    "engine_name": engine_name,
                    "t_end": t_end,
                    "seed": seed,
                    "events_processed": res.events_processed,
                    "wall_time": res.wall_time,
                    "cpu_time": res.cpu_time,
                    "cpu_wall_ratio": res.cpu_wall_ratio,
                    "events_per_sec": res.events_per_sec,
                    "T": res.T, "P_b": res.P_b,
                    "U1": res.U1, "U2": res.U2, "U3": res.U3, "U4": res.U4,
                    "W_f": res.W_f, "X": res.X, "P95_T": res.P95_T, "L_system": res.L_system,
                    "flow_balance_ok": int(res.flow_balance_ok),
                    "little_err_sys": res.little_err_sys,
                    "causality_violations": res.causality_violations,
                    "deadlocked": int(res.deadlocked),
                    "max_fidelity_err": max_fid_err,
                    "fidelity_passed": int(fid_passed),
                }
                _append_row(RAW_TIMING_CSV, RAW_TIMING_FIELDS, row)
                done_timing.add((engine_name, t_end, seed))
                print(
                    f"         seed={seed:2d} | ev={res.events_processed:6d} | "
                    f"wall={res.wall_time:.4f}s | cpu/wall={res.cpu_wall_ratio:.2f} | "
                    f"thr={res.events_per_sec:9,.0f} ev/s | fid_err={max_fid_err:.1e}"
                )

    # ---- PHA 2: MEMORY PROFILING RUN (tracemalloc BẬT riêng biệt) ----
    existing_mem = _load_existing_rows(RAW_MEM_CSV)
    done_mem: Set[Tuple[str, float, int]] = {
        (r["engine_name"], float(r["t_end"]), int(r["seed"])) for r in existing_mem
    }

    print(f"\n[PHA 2] MEMORY PROFILING RUN (tracemalloc=ON, seeds={MEM_SEEDS})")
    for t_end in T_END_LEVELS:
        params = _make_params(t_end)
        for engine_name in ENGINE_ORDER:
            runner = ENGINE_RUNNERS[engine_name]
            missing_mem = [s for s in MEM_SEEDS if (engine_name, t_end, s) not in done_mem]
            if not missing_mem:
                print(f"  [SKIP] {engine_name:11s} | t_end={t_end:7.0f} (đã đủ memory profile)")
                continue
            for seed in missing_mem:
                res = runner(params, seed=seed, measure_memory=True)
                _append_row(
                    RAW_MEM_CSV,
                    RAW_MEM_FIELDS,
                    {
                        "engine_name": engine_name,
                        "t_end": t_end,
                        "seed": seed,
                        "events_processed": res.events_processed,
                        "peak_mem_mb": res.peak_mem_mb,
                    },
                )
                done_mem.add((engine_name, t_end, seed))
                print(f"  [MEM ] {engine_name:11s} | t_end={t_end:7.0f} | seed={seed} | peak_mem={res.peak_mem_mb:.3f} MB")

    # ---- TỔNG HỢP MEAN ± CI 95% VÀ XUẤT exp_m5_benchmark.csv ----
    all_timing = _load_existing_rows(RAW_TIMING_CSV)
    all_mem = _load_existing_rows(RAW_MEM_CSV)

    seq_wall_mean: Dict[float, float] = {}
    for t_end in T_END_LEVELS:
        vals = [
            float(r["wall_time"]) for r in all_timing
            if r["engine_name"] == "sequential" and float(r["t_end"]) == t_end
        ]
        seq_wall_mean[t_end] = compute_ci95(vals)["mean"]

    summary_rows: List[Dict[str, Any]] = []
    print("\n" + "=" * 108)
    print(
        f"{'Engine':11s} | {'t_end':>6s} | {'Events':>8s} | {'Wall (s) ± CI95':>19s} | "
        f"{'Slowdown':>8s} | {'Thr (ev/s)':>11s} | {'CPU/Wall':>8s} | {'Mem (MB)':>9s} | {'MaxFidErr':>9s}"
    )
    print("-" * 108)

    for t_end in T_END_LEVELS:
        for engine_name in ENGINE_ORDER:
            t_rows = [
                r for r in all_timing
                if r["engine_name"] == engine_name and float(r["t_end"]) == t_end
            ]
            m_rows = [
                r for r in all_mem
                if r["engine_name"] == engine_name and float(r["t_end"]) == t_end
            ]
            ci_wall = compute_ci95([float(r["wall_time"]) for r in t_rows])
            ci_thr = compute_ci95([float(r["events_per_sec"]) for r in t_rows])
            ci_cpu = compute_ci95([float(r["cpu_time"]) for r in t_rows])
            ci_ratio = compute_ci95([float(r["cpu_wall_ratio"]) for r in t_rows])
            ci_mem = compute_ci95([float(r["peak_mem_mb"]) for r in m_rows])
            ev_mean = sum(float(r["events_processed"]) for r in t_rows) / len(t_rows)
            slowdown = ci_wall["mean"] / seq_wall_mean[t_end] if seq_wall_mean[t_end] > 0 else 1.0
            max_fid = max(float(r["max_fidelity_err"]) for r in t_rows)
            fid_pass_pct = 100.0 * sum(int(r["fidelity_passed"]) for r in t_rows) / len(t_rows)
            caus_err_pct = 100.0 * sum(1 for r in t_rows if int(r["causality_violations"]) > 0) / len(t_rows)
            deadlock_pct = 100.0 * sum(int(r["deadlocked"]) for r in t_rows) / len(t_rows)

            srow = {
                "engine_name": engine_name,
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
                "max_fidelity_err": max_fid,
                "fidelity_pass_rate_pct": fid_pass_pct,
                "causality_error_rate_pct": caus_err_pct,
                "deadlock_rate_pct": deadlock_pct,
            }
            summary_rows.append(srow)
            print(
                f"{engine_name:11s} | {int(t_end):6d} | {ev_mean:8.0f} | "
                f"{ci_wall['mean']:8.4f} ± {ci_wall['half_width']:8.4f} | "
                f"{slowdown:7.2f}x | {ci_thr['mean']:11,.0f} | "
                f"{ci_ratio['mean']:8.3f} | {ci_mem['mean']:9.3f} | {max_fid:9.1e}"
            )
    print("=" * 108)

    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"[OK] Đã xuất bảng tổng hợp: {SUMMARY_CSV}")


if __name__ == "__main__":
    run_m5_benchmark()
