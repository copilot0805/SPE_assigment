import csv
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

from drivethru.config.experiment_config import NetworkExpConfig, get_exp_bcd_configs
from drivethru.experiments.runner import (
    check_precision_details,
    compute_config_fingerprint,
    run_batch_with_checkpoint,
)
from drivethru.metrics.analytical import analytical_fork_join_network
from drivethru.metrics.stats_utils import compute_ci95, evaluate_sla_status


def summarize_config(cfg: NetworkExpConfig, rep_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tổng hợp Mean và Half-width CI95% cho tất cả các chỉ số của 1 cấu hình."""
    metrics = [
        "T", "P95_T", "P_T_gt_8", "P_b", "X", "W_f", "P_f", "L_f", "L_system",
        "U1", "U2", "U3", "U4",
        "W1", "W2", "W3", "W4",
        "Wq1", "Wq2", "Wq3", "Wq4",
        "L1", "L2", "L3", "L4",
    ]
    det = check_precision_details(rep_rows)
    row: Dict[str, Any] = {
        "config_id": cfg.config_id,
        "config_hash": compute_config_fingerprint(cfg.params),
        "exp_tags": ";".join(cfg.exp_tags),
        "scenario": cfg.scenario_name,
        "lam": cfg.params.lam,
        "c2": cfg.params.c2,
        "K1": cfg.params.K1,
        "mean_s3": cfg.params.mean_s3,
        "blocking_order": cfg.params.blocking_order,
        "R": len(rep_rows),
        "flow_balance_all_ok": all(r["flow_balance_ok"] for r in rep_rows),
        "max_little_err_pct": max(r["little_err_sys"] for r in rep_rows) * 100.0,
        "T_rel_hw_pct": det["t_rel_hw_pct"],
        "Pb_hw_abs": det["pb_hw_abs"],
        "worst_precision_metric": det["worst_rel_metric"],
        "max_rel_hw_pct": det["worst_rel_hw_pct"],
        "precision_ok": det["precision_ok"],
    }
    ci_map: Dict[str, Dict[str, float]] = {}
    for m in metrics:
        ci = compute_ci95([r[m] for r in rep_rows])
        ci_map[m] = ci
        row[f"{m}_mean"] = ci["mean"]
        row[f"{m}_hw"] = ci["half_width"]

    sla_status = evaluate_sla_status(ci_map["T"], ci_map["P_b"], t_limit=8.0, pb_limit=0.05)
    row["sla_status"] = sla_status
    row["sla_pass"] = sla_status == "PASS"
    return row


def write_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def sync_exp_d_crn_pairs(
    configs: List[NetworkExpConfig],
    all_reps: Dict[str, List[Dict[str, Any]]],
    raw_csv: Path,
    max_workers: int,
) -> None:
    """
    Thực hiện đúng Mục 2.5 Thiết kế V2: khi so sánh các cấu hình bằng CRN (Exp D),
    cả biến thể không chặn và có chặn dùng chung tập seed 1..R lớn nhất của cặp đó.
    """
    cfg_by_id = {c.config_id: c for c in configs}
    sync_targets: List[NetworkExpConfig] = []

    for lam in (0.4, 0.6, 0.7):
        k = int(round(lam * 10))
        nb_id = f"C_lam{k}_c2_2_K1_8"
        blk_id = f"D_BLK_lam{k}_c2_2_K1_8"
        r_nb = len(all_reps[nb_id])
        r_blk = len(all_reps[blk_id])
        max_r = max(r_nb, r_blk)
        if r_nb < max_r:
            sync_targets.append(replace(cfg_by_id[nb_id], base_replications=max_r, max_replications=max_r))
        if r_blk < max_r:
            sync_targets.append(replace(cfg_by_id[blk_id], base_replications=max_r, max_replications=max_r))

    if sync_targets:
        print(
            "[Exp D CRN Sync] Đồng bộ tập seed chung 1..R lớn nhất theo §2.5 cho: "
            + ", ".join(f"{c.config_id}(->R={c.base_replications})" for c in sync_targets)
        )
        synced = run_batch_with_checkpoint(
            configs=sync_targets,
            raw_csv_path=raw_csv,
            max_workers=max_workers,
            auto_expand_ci=False,
        )
        all_reps.update(synced)


def main(max_workers: int = 4) -> None:
    reports_dir = Path("reports")
    raw_csv = reports_dir / "exp_bcd_raw_runs.csv"
    configs = get_exp_bcd_configs()

    all_reps = run_batch_with_checkpoint(
        configs=configs,
        raw_csv_path=raw_csv,
        max_workers=max_workers,
        auto_expand_ci=True,
    )

    # Đồng bộ CRN cho Exp D trước khi tổng hợp summary CSV
    sync_exp_d_crn_pairs(configs, all_reps, raw_csv, max_workers=max_workers)

    summaries = [summarize_config(cfg, all_reps[cfg.config_id]) for cfg in configs]
    summary_by_id = {s["config_id"]: s for s in summaries}

    # --- 1. TỔNG HỢP THÍ NGHIỆM B ---
    exp_b_rows = [s for s in summaries if "ExpB_Base" in s["exp_tags"] or "ExpB_FJ" in s["exp_tags"]]
    write_summary_csv(reports_dir / "exp_b_summary.csv", exp_b_rows)

    print("=" * 108)
    print("KẾT QUẢ THÍ NGHIỆM B — ĐƯỜNG CƠ SỞ (c2=1, K1=8) & ĐỐI CHIẾU XẤP XỈ FORK-JOIN (K1=30)")
    print("=" * 108)
    print(f"{'Cấu hình':<20} | {'lam':<4} | {'T (Mean±CI95)':>17} | {'P95(T)':>7} | {'Pb (%)':>7} | {'U1':>5} | {'U2':>5} | {'U3':>5} | {'U4':>5} | {'Wf':>5}")
    print("-" * 108)
    for r in exp_b_rows:
        t_str = f"{r['T_mean']:7.3f} ± {r['T_hw']:5.3f}"
        print(
            f"{r['config_id']:<20} | {r['lam']:<4.1f} | {t_str:>17} | {r['P95_T_mean']:7.3f} | "
            f"{r['P_b_mean']*100:6.2f}% | {r['U1_mean']:5.3f} | {r['U2_mean']:5.3f} | "
            f"{r['U3_mean']:5.3f} | {r['U4_mean']:5.3f} | {r['W_f_mean']:5.3f}"
        )

    for cid, key_approx, label in [
        ("B_FJ_K30_base", "T_approx", "Xấp xỉ Fork-Join (1/mu3=1.5)"),
        ("B_FJ_K30_deg", "T_jackson_no_kitchen", "Thu gọn Jackson (1/mu3=0.01)"),
    ]:
        r = summary_by_id[cid]
        approx = analytical_fork_join_network(
            r["lam"], 2, r["K1"], 1.5, r["c2"], 1.25, 2, r["mean_s3"], 2, 1.0
        )
        t_th = approx[key_approx]
        err = abs(r["T_mean"] - t_th) / t_th * 100.0
        print(f"  -> Đối chiếu {label}: Sim T = {r['T_mean']:.4f} vs Lý thuyết = {t_th:.4f} (Sai lệch = {err:.2f}% | {'PASS' if err < 5.0 else 'CHECK'})")

    # --- 2. TỔNG HỢP THÍ NGHIỆM C ---
    exp_c_rows = [s for s in summaries if "ExpC" in s["exp_tags"]]
    write_summary_csv(reports_dir / "exp_c_summary.csv", exp_c_rows)

    print("\n" + "=" * 112)
    print("KẾT QUẢ THÍ NGHIỆM C — CẤU HÌNH ĐẠT SLA TẠI CAO ĐIỂM PEAK (lam=0.6: T <= 8.0 phút & Pb <= 5%)")
    print("=" * 112)
    peak_c = [r for r in exp_c_rows if abs(r["lam"] - 0.6) < 1e-9]
    print(f"{'c2':<4} | {'K1':<4} | {'R':<3} | {'T (Mean±CI95)':>17} | {'P95(T)':>7} | {'P(T>8)':>7} | {'Pb (%)':>14} | {'U2':>6} | {'SLA':<8}")
    print("-" * 112)
    for r in peak_c:
        t_str = f"{r['T_mean']:7.3f} ± {r['T_hw']:5.3f}"
        pb_str = f"{r['P_b_mean']*100:5.2f} ± {r['P_b_hw']*100:4.2f}%"
        print(
            f"{r['c2']:<4} | {r['K1']:<4} | {r['R']:<3} | {t_str:>17} | {r['P95_T_mean']:7.3f} | "
            f"{r['P_T_gt_8_mean']*100:6.2f}% | {pb_str:>14} | {r['U2_mean']:6.3f} | {r['sla_status']:<8}"
        )

    # --- 3. TỔNG HỢP THÍ NGHIỆM D ---
    exp_d_rows = [s for s in summaries if "ExpD_NB" in s["exp_tags"] or "ExpD_BLK" in s["exp_tags"]]
    write_summary_csv(reports_dir / "exp_d_summary.csv", exp_d_rows)

    print("\n" + "=" * 112)
    print("KẾT QUẢ THÍ NGHIỆM D — SO SÁNH KHÔNG CHẶN (NON-BLOCKING) vs CHẶN (BLOCKING) TẠI c2=2, K1=8")
    print("=" * 112)
    print(f"{'lam':<5} | {'Biến thể':<14} | {'R':<3} | {'T (Mean±CI95)':>17} | {'Pb (%)':>14} | {'U1':>14} | {'Wf (phút)':>10}")
    print("-" * 112)
    for lam in (0.4, 0.6, 0.7):
        nb = summary_by_id[f"C_lam{int(round(lam * 10))}_c2_2_K1_8"]
        blk = summary_by_id[f"D_BLK_lam{int(round(lam * 10))}_c2_2_K1_8"]
        for label, r in [("Non-blocking", nb), ("Blocking", blk)]:
            t_str = f"{r['T_mean']:7.3f} ± {r['T_hw']:5.3f}"
            pb_str = f"{r['P_b_mean']*100:5.2f} ± {r['P_b_hw']*100:4.2f}%"
            u1_str = f"{r['U1_mean']:6.3f} ± {r['U1_hw']:5.3f}"
            print(f"{lam:<5.1f} | {label:<14} | {r['R']:<3} | {t_str:>17} | {pb_str:>14} | {u1_str:>14} | {r['W_f_mean']:10.4f}")
        print("-" * 112)

    all_prec_ok = all(s["precision_ok"] for s in summaries)
    print(f"\n[M4 Summary] Đã xuất 3 bảng CSV tại reports/ | Toàn bộ {len(summaries)} cấu hình đạt CI95% (U,L,W,T,Pb): {all_prec_ok}")


if __name__ == "__main__":
    main(max_workers=4)
