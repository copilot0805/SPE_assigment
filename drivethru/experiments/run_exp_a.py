import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bkitevsim.core import Simulation, SimulationOptions
from drivethru.config.experiment_config import ExpAConfig, get_exp_a_configs
from drivethru.config.simulation_config import safe_bucket_width
from drivethru.experiments.run_single import attach_global_monotonic_guard
from drivethru.metrics.analytical import analytical_single_station
from drivethru.metrics.stats_utils import check_littles_law, compute_ci95
from drivethru.models.car_source import CarSourceLP
from drivethru.models.monitor import MonitorLP
from drivethru.models.station import StationLP


def _run_one_seed_worker(args: Tuple[ExpAConfig, int]) -> Tuple[int, Dict[str, Any]]:
    cfg, seed = args
    options = SimulationOptions(
        end_time=cfg.t_end,
        dispatcher="sequential",
        bucket_width=safe_bucket_width(cfg.t_end),
        log_level="ERROR",
    )
    sim = Simulation(
        options,
        models={"Source": CarSourceLP, "Station": StationLP, "Monitor": MonitorLP},
    )

    mean_s = 1.0 / cfg.mu
    src = sim.create_lp(
        0, "Source",
        lam=cfg.lam, mean_services={1: mean_s},
        target_lp_id=1, t_warmup=cfg.t_warmup, t_end=cfg.t_end, seed=seed,
    )
    stn = sim.create_lp(
        1, "Station",
        station_idx=1, c=cfg.c, K=cfg.K, mean_service_time=mean_s,
        out_targets=[(5, "DEPARTURE")], monitor_lp_id=5,
        t_warmup=cfg.t_warmup, t_end=cfg.t_end, record_timestamps=False,
    )
    mon = sim.create_lp(
        5, "Monitor",
        t_warmup=cfg.t_warmup, t_end=cfg.t_end,
    )

    attach_global_monotonic_guard((src, stn, mon))
    sim.run()
    stats = stn.get_statistics()
    stats["flow_balance_ok"] = (
        src.total_generated == stats["total_arrived"]
        and stats["total_arrived"] == (mon.total_completed + mon.total_dropped + stats["n_unfinished"])
    )
    return seed, stats


def evaluate_exp_a(max_workers: int = 4) -> List[Dict[str, Any]]:
    configs = get_exp_a_configs()
    total_configs = len(configs)
    summary_rows: List[Dict[str, Any]] = []
    little_violations: List[Tuple[str, float]] = []
    flow_violations: List[str] = []
    metrics_to_check = ["U", "L", "L_q", "W", "W_q", "X", "P_b", "P_w"]

    t_start_all = time.perf_counter()
    print(
        f"[Exp A - Parallel Replications] Chạy {total_configs} cấu hình x 30 seeds "
        f"(Mô phỏng Sequential đơn luồng, chạy song song trên {max_workers} nhân CPU)..."
    )
    print("=" * 124)
    print(
        f"{'Mã':<6} | {'Mô hình':<18} | {'lambda':<6} | {'Chỉ số':<6} | "
        f"{'Lý thuyết':>10} | {'Mô phỏng (Mean ± CI95)':>25} | {'Sai số %':>9} | {'Little %':>8} | {'KQ':<5}"
    )
    print("-" * 124)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for c_idx, cfg in enumerate(configs, start=1):
            t0 = time.perf_counter()
            futures = [
                executor.submit(_run_one_seed_worker, (cfg, seed))
                for seed in range(1, cfg.num_replications + 1)
            ]

            seed_results: List[Tuple[int, Dict[str, Any]]] = []
            done_count = 0
            for fut in as_completed(futures):
                seed_id, st = fut.result()
                seed_results.append((seed_id, st))
                done_count += 1
                print(
                    f"  -> Đang chạy [{c_idx:02d}/{total_configs:02d}] {cfg.code} ({cfg.model_name}, "
                    f"lambda={cfg.lam:.2f}, t_end={int(cfg.t_end)}): xong {done_count:02d}/{cfg.num_replications} seeds...",
                    end="\r",
                    flush=True,
                )

            seed_results.sort(key=lambda x: x[0])
            rep_stats = [x[1] for x in seed_results]
            cfg_time = time.perf_counter() - t0
            print(" " * 118, end="\r", flush=True)

            flow_all_ok = all(r["flow_balance_ok"] for r in rep_stats)
            if not flow_all_ok:
                flow_violations.append(cfg.code)

            theory = analytical_single_station(cfg.lam, cfg.mu, cfg.c, cfg.K)

            l_mean = sum(r["L"] for r in rep_stats) / len(rep_stats)
            x_mean = sum(r["X"] for r in rep_stats) / len(rep_stats)
            w_mean = sum(r["W"] for r in rep_stats) / len(rep_stats)
            little_chk = check_littles_law(l_mean, x_mean, w_mean, tol=0.01)
            little_err_pct = little_chk["rel_error"] * 100.0
            little_passed = little_chk["passed"] == 1.0
            if not little_passed:
                little_violations.append((cfg.code, little_err_pct))

            for m in metrics_to_check:
                t_val = theory[m]
                samples = [r[m] for r in rep_stats]
                ci = compute_ci95(samples)
                s_mean = ci["mean"]
                hw = ci["half_width"]

                if abs(t_val) < 1e-12:
                    rel_err_pct = 0.0 if abs(s_mean) < 1e-9 else 100.0
                    in_ci = abs(s_mean) < 1e-9
                    precision_ok = True
                else:
                    rel_err_pct = abs(s_mean - t_val) / abs(t_val) * 100.0
                    in_ci = (ci["ci_low"] - 1e-9) <= t_val <= (ci["ci_high"] + 1e-9)
                    precision_ok = (hw <= 0.003) if m == "P_b" else (ci["rel_half_width_pct"] <= 5.0)

                passed = (in_ci or (rel_err_pct <= 5.0)) and precision_ok
                status_str = "PASS" if passed else "CHECK"

                row = {
                    "code": cfg.code,
                    "model": cfg.model_name,
                    "c": cfg.c,
                    "K": cfg.K,
                    "rho_or_a": cfg.rho_or_a,
                    "lambda": cfg.lam,
                    "mu": cfg.mu,
                    "t_end": cfg.t_end,
                    "metric": m,
                    "theory": t_val,
                    "sim_mean": s_mean,
                    "sim_std": ci["std"],
                    "ci95_half_width": hw,
                    "ci95_low": ci["ci_low"],
                    "ci95_high": ci["ci_high"],
                    "rel_error_pct": rel_err_pct,
                    "little_error_pct": little_err_pct,
                    "in_ci95": in_ci,
                    "passed": passed,
                    "ci95_rel_hw_pct": ci["rel_half_width_pct"],
                    "precision_ok": precision_ok,
                    "little_passed": little_passed,
                    "flow_balance_ok": flow_all_ok,
                }
                summary_rows.append(row)

                if m in ("U", "L", "W", "P_b", "P_w"):
                    if abs(t_val) < 1e-12 and m in ("P_b", "P_w"):
                        continue
                    ci_str = f"{s_mean:10.4f} ± {hw:7.4f}"
                    print(
                        f"{cfg.code:<6} | {cfg.model_name:<18} | {cfg.lam:<6.2f} | {m:<6} | "
                        f"{t_val:10.4f} | {ci_str:>25} | {rel_err_pct:8.2f}% | {little_err_pct:7.2f}% | {status_str:<5}",
                        flush=True,
                    )

            little_tag = "OK" if little_passed else "WARN (>1%)"
            print(
                f"  [Hoàn tất {cfg.code} trong {cfg_time:.2f}s | Cân bằng dòng: {'OK' if flow_all_ok else 'FAIL'} "
                f"| Little's Law lệch: {little_err_pct:.3f}% ({little_tag})]"
            )
            print("-" * 124, flush=True)

    total_elapsed = time.perf_counter() - t_start_all
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    out_csv = reports_dir / "exp_a_validation.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    total_checks = len(summary_rows)
    passed_checks = sum(1 for r in summary_rows if r["passed"])
    print(f"Tổng kết Validation Exp A: Đạt {passed_checks}/{total_checks} chỉ số trong {total_elapsed:.2f}s.")
    print(f"  - Cân bằng dòng PASS: {total_configs - len(flow_violations)}/{total_configs} cấu hình.")
    print(f"  - Little's Law PASS (<=1%): {total_configs - len(little_violations)}/{total_configs} cấu hình.")
    if little_violations:
        print(f"  - [WARN] Cấu hình lệch Little > 1%: {little_violations}")
    print(f"Đã lưu bảng kết quả CSV tại: {out_csv}")
    return summary_rows


if __name__ == "__main__":
    evaluate_exp_a(max_workers=4)
