import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

from drivethru.metrics.stats_utils import compute_ci95

REPORTS_DIR = Path("reports")
EXP_C_CSV = REPORTS_DIR / "exp_c_summary.csv"
RAW_BCD_CSV = REPORTS_DIR / "exp_bcd_raw_runs.csv"


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy {path}. Hãy chạy Exp B/C/D trước.")
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def run_allocation_of_variation_with_sse(
    raw_bcd: List[Dict[str, str]],
    n_reps: int = 30,
) -> List[Dict[str, Any]]:
    """
    Phân bổ phương sai (Allocation of Variation, pe9 & pe10) cho thiết kế giai thừa đầy đủ
    có lặp cân bằng: 4 mức lam x 3 mức c2 x 4 mức K1 x 30 seeds = 1,440 lượt từ exp_bcd_raw_runs.csv.
    Phân rã chính xác: SST = SS_lam + SS_c2 + SS_K1 + SS_lam_c2 + SS_lam_K1 + SS_c2_K1 + SS_lam_c2_K1 + SSE.
    """
    exp_c_raw = [r for r in raw_bcd if "ExpC" in r["exp_tags"] and int(r["seed"]) <= n_reps]
    lams = sorted({float(r["lam"]) for r in exp_c_raw})
    c2s = sorted({int(r["c2"]) for r in exp_c_raw})
    k1s = sorted({int(r["K1"]) for r in exp_c_raw})
    a, b, c = len(lams), len(c2s), len(k1s)

    lookup = {
        (float(r["lam"]), int(r["c2"]), int(r["K1"]), int(r["seed"])): r
        for r in exp_c_raw
    }

    metrics = [
        ("T", "T (Thời gian E2E)"),
        ("P_b", "P_b (Xác suất từ chối)"),
        ("X", "X (Thông lượng)"),
        ("W_f", "W_f (Thời gian chờ đồ)"),
        ("U2", "U2 (Độ sử dụng Payment)"),
        ("P95_T", "P95(T) (Phân vị 95%)"),
    ]

    out_rows: List[Dict[str, Any]] = []
    print("=" * 118)
    print(f"BƯỚC 9.1 - PHÂN BỔ PHƯƠNG SAI CÓ SAI SỐ THÍ NGHIỆM SSE (pe9/pe10 - {a}x{b}x{c}x{n_reps} = {a*b*c*n_reps} lượt)")
    print("=" * 118)
    print(
        f"{'Chỉ số':<24} | {'lam(%)':>6} | {'c2 (%)':>6} | {'K1 (%)':>6} | "
        f"{'lam*c2':>6} | {'lam*K1':>6} | {'c2*K1':>6} | {'3-way':>6} | {'SSE(%)':>6} | {'Top tác động'}"
    )
    print("-" * 118)

    for m_col, m_label in metrics:
        y = np.zeros((a, b, c, n_reps), dtype=float)
        for i, l_val in enumerate(lams):
            for j, c2_val in enumerate(c2s):
                for k, k1_val in enumerate(k1s):
                    for s_idx in range(n_reps):
                        y[i, j, k, s_idx] = float(lookup[(l_val, c2_val, k1_val, s_idx + 1)][m_col])

        grand = float(y.mean())
        ss_tot = float(np.sum((y - grand) ** 2))
        if ss_tot <= 1e-18:
            ss_tot = 1.0

        cell_mean = y.mean(axis=3)  # shape (a, b, c)
        ss_err = float(np.sum((y - cell_mean[:, :, :, None]) ** 2))
        ss_cells = float(n_reps * np.sum((cell_mean - grand) ** 2))

        m_a = cell_mean.mean(axis=(1, 2))
        m_b = cell_mean.mean(axis=(0, 2))
        m_c = cell_mean.mean(axis=(0, 1))
        m_ab = cell_mean.mean(axis=2)
        m_ac = cell_mean.mean(axis=1)
        m_bc = cell_mean.mean(axis=0)

        ss_a = float(b * c * n_reps * np.sum((m_a - grand) ** 2))
        ss_b = float(a * c * n_reps * np.sum((m_b - grand) ** 2))
        ss_c = float(a * b * n_reps * np.sum((m_c - grand) ** 2))
        ss_ab = float(c * n_reps * np.sum((m_ab - m_a[:, None] - m_b[None, :] + grand) ** 2))
        ss_ac = float(b * n_reps * np.sum((m_ac - m_a[:, None] - m_c[None, :] + grand) ** 2))
        ss_bc = float(a * n_reps * np.sum((m_bc - m_b[:, None] - m_c[None, :] + grand) ** 2))
        ss_abc = max(0.0, ss_cells - (ss_a + ss_b + ss_c + ss_ab + ss_ac + ss_bc))

        pcts = {
            "lam": 100.0 * ss_a / ss_tot,
            "c2": 100.0 * ss_b / ss_tot,
            "K1": 100.0 * ss_c / ss_tot,
            "lam_x_c2": 100.0 * ss_ab / ss_tot,
            "lam_x_K1": 100.0 * ss_ac / ss_tot,
            "c2_x_K1": 100.0 * ss_bc / ss_tot,
            "lam_x_c2_x_K1": 100.0 * ss_abc / ss_tot,
            "error_sse": 100.0 * ss_err / ss_tot,
        }
        ranked = sorted([(k, v) for k, v in pcts.items() if k != "error_sse"], key=lambda x: x[1], reverse=True)
        top_str = ", ".join(f"{k}({v:.1f}%)" for k, v in ranked[:3] if v >= 1.0)

        out_rows.append({
            "metric_col": m_col,
            "metric_label": m_label,
            "n_runs": a * b * c * n_reps,
            "pct_lam": round(pcts["lam"], 2),
            "pct_c2": round(pcts["c2"], 2),
            "pct_K1": round(pcts["K1"], 2),
            "pct_lam_x_c2": round(pcts["lam_x_c2"], 2),
            "pct_lam_x_K1": round(pcts["lam_x_K1"], 2),
            "pct_c2_x_K1": round(pcts["c2_x_K1"], 2),
            "pct_lam_x_c2_x_K1": round(pcts["lam_x_c2_x_K1"], 2),
            "pct_error_sse": round(pcts["error_sse"], 2),
            "top_effects": top_str,
        })
        print(
            f"{m_label:<24} | {pcts['lam']:6.2f} | {pcts['c2']:6.2f} | {pcts['K1']:6.2f} | "
            f"{pcts['lam_x_c2']:6.2f} | {pcts['lam_x_K1']:6.2f} | {pcts['c2_x_K1']:6.2f} | "
            f"{pcts['lam_x_c2_x_K1']:6.2f} | {pcts['error_sse']:6.2f} | {top_str}"
        )

    out_path = REPORTS_DIR / "exp_c_sensitivity_anova.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"[OK] Đã xuất: {out_path}\n")
    return out_rows


def plot_fig10_allocation_of_variation(anova_rows: List[Dict[str, Any]]) -> None:
    """Biểu đồ cột chồng Phân bổ Phương sai (Allocation of Variation, pe9/pe10) kèm SSE."""
    labels = [r["metric_col"] for r in anova_rows]
    x = np.arange(len(labels))

    components = [
        ("pct_lam", "Tải đến λ", "#1f77b4"),
        ("pct_c2", "Số cửa Payment c2", "#d62728"),
        ("pct_K1", "Sức chứa Order K1", "#2ca02c"),
        ("pct_lam_x_c2", "Tương tác λ × c2", "#ff7f0e"),
        ("pct_lam_x_K1", "Tương tác λ × K1", "#9467bd"),
        ("other_inter", "Tương tác khác (c2×K1, 3-way)", "#8c564b"),
        ("pct_error_sse", "Sai số thí nghiệm (SSE)", "#7f7f7f"),
    ]

    fig, ax = plt.subplots(figsize=(11.5, 5.6), dpi=300)
    bottom = np.zeros(len(labels), dtype=float)

    for key, comp_label, color in components:
        if key == "other_inter":
            vals = np.array([r["pct_c2_x_K1"] + r["pct_lam_x_c2_x_K1"] for r in anova_rows], dtype=float)
        else:
            vals = np.array([r[key] for r in anova_rows], dtype=float)

        bars = ax.bar(x, vals, width=0.58, bottom=bottom, label=comp_label, color=color, alpha=0.9)
        for i, v in enumerate(vals):
            if v >= 5.5:
                ax.text(
                    x[i], bottom[i] + v / 2.0, f"{v:.1f}%",
                    ha="center", va="center", fontsize=8.4, fontweight="bold", color="white",
                )
        bottom += vals

    ax.set_title(
        "Phân bổ phương sai — Exp C",
        fontsize=11.2, fontweight="bold",
    )
    ax.set_xticks(x)
    ax.set_xticklabels([r["metric_label"].replace(" (", "\n(") for r in anova_rows], fontsize=9.0)
    ax.set_ylabel("Tỷ lệ phần trăm tổng biến thiên giải thích (% SST)", fontsize=10)
    ax.set_ylim(0, 105)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=4, fontsize=8.6, framealpha=0.95)
    plt.tight_layout()
    out_png = REPORTS_DIR / "fig10_allocation_of_variation.png"
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_png.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ cột chồng phân bổ phương sai: {out_png}\n")


def compute_exp_d_paired_crn(raw_bcd: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Tính khoảng tin cậy 95% ghép cặp (Paired-t CI) cho hiệu Delta = Blocking - Non-blocking
    theo từng seed CRN chung ở Exp D (c2=2, K1=8, lam in {0.4, 0.6, 0.7}).
    """
    by_cfg_seed: Dict[str, Dict[int, Dict[str, str]]] = {}
    for r in raw_bcd:
        by_cfg_seed.setdefault(r["config_id"], {})[int(r["seed"])] = r

    out_rows: List[Dict[str, Any]] = []
    print("=" * 116)
    print("BƯỚC 9.2 - SO SÁNH GHÉP CẶP CRN (PAIRED CI 95%) CHO EXP D: Delta = BLOCKING - NON-BLOCKING (c2=2, K1=8)")
    print("=" * 116)
    print(f"{'lam':<4} | {'n_pair':>6} | {'dT +/- CI95 (phút)':>19} | {'dP_b +/- CI95 (pp)':>19} | {'dU1 +/- CI95 (pp)':>19} | {'dW_f +/- CI95 (phút)':>20}")
    print("-" * 116)

    for lam in (0.4, 0.6, 0.7):
        nb_map = by_cfg_seed[f"C_lam{int(round(lam * 10))}_c2_2_K1_8"]
        blk_map = by_cfg_seed[f"D_BLK_lam{int(round(lam * 10))}_c2_2_K1_8"]
        common_seeds = sorted(set(nb_map.keys()) & set(blk_map.keys()))

        ci_dt = compute_ci95([float(blk_map[s]["T"]) - float(nb_map[s]["T"]) for s in common_seeds])
        ci_dpb = compute_ci95([(float(blk_map[s]["P_b"]) - float(nb_map[s]["P_b"])) * 100.0 for s in common_seeds])
        ci_du1 = compute_ci95([(float(blk_map[s]["U1"]) - float(nb_map[s]["U1"])) * 100.0 for s in common_seeds])
        ci_dwf = compute_ci95([float(blk_map[s]["W_f"]) - float(nb_map[s]["W_f"]) for s in common_seeds])

        out_rows.append({
            "lam": lam,
            "n_pairs": len(common_seeds),
            "dT_mean": round(ci_dt["mean"], 4), "dT_hw": round(ci_dt["half_width"], 4),
            "dPb_pp_mean": round(ci_dpb["mean"], 4), "dPb_pp_hw": round(ci_dpb["half_width"], 4),
            "dU1_pp_mean": round(ci_du1["mean"], 4), "dU1_pp_hw": round(ci_du1["half_width"], 4),
            "dWf_mean": round(ci_dwf["mean"], 4), "dWf_hw": round(ci_dwf["half_width"], 4),
            "stat_sig_T": int(ci_dt["ci_low"] > 0.0),
        })
        print(
            f"{lam:<4.1f} | {len(common_seeds):>6d} | "
            f"{ci_dt['mean']:+7.3f} +/- {ci_dt['half_width']:6.3f}  | "
            f"{ci_dpb['mean']:+7.3f} +/- {ci_dpb['half_width']:6.3f}  | "
            f"{ci_du1['mean']:+7.3f} +/- {ci_du1['half_width']:6.3f}  | "
            f"{ci_dwf['mean']:+7.4f} +/- {ci_dwf['half_width']:6.4f}"
        )

    out_path = REPORTS_DIR / "exp_d_paired_crn.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"[OK] Đã xuất bảng Paired CRN Exp D: {out_path}\n")
    return out_rows


def build_min_sla_table(exp_c: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    lams = sorted({float(r["lam"]) for r in exp_c})
    out_rows: List[Dict[str, Any]] = []

    print("=" * 114)
    print("BƯỚC 9.3 - BẢNG CẤU HÌNH TỐI THIỂU ĐẠT SLA & KHUYẾN NGHỊ VẬN HÀNH THEO TỪNG MỨC TẢI lam")
    print("=" * 114)
    print(
        f"{'Kịch bản':<10} | {'Đạt/12':>6} | {'Tối thiểu (SLA)':<16} | {'T +/- CI95':>16} | {'Pb (%)':>7} | {'U2':>5} | "
        f"{'Khuyến nghị (U2<0.8,Pb<1.5%)':<28}"
    )
    print("-" * 114)

    for lam in lams:
        sub = [r for r in exp_c if abs(float(r["lam"]) - lam) < 1e-9]
        sc_name = sub[0]["scenario"]
        passed = [r for r in sub if r.get("sla_status", "PASS" if r["sla_pass"] == "True" else "FAIL") == "PASS"]
        passed_sorted = sorted(passed, key=lambda r: (int(r["c2"]), int(r["K1"])))
        min_cfg = passed_sorted[0]

        robust = [r for r in passed_sorted if float(r["U2_mean"]) <= 0.80 and float(r["P_b_mean"]) <= 0.015]
        rec_cfg = robust[0] if robust else passed_sorted[-1]

        out_rows.append({
            "scenario": sc_name, "lam": lam, "n_pass_out_of_12": len(passed),
            "min_sla_c2": int(min_cfg["c2"]), "min_sla_K1": int(min_cfg["K1"]),
            "min_sla_T_mean": float(min_cfg["T_mean"]), "min_sla_T_hw": float(min_cfg["T_hw"]),
            "min_sla_Pb_pct": float(min_cfg["P_b_mean"]) * 100.0, "min_sla_U2": float(min_cfg["U2_mean"]),
            "rec_c2": int(rec_cfg["c2"]), "rec_K1": int(rec_cfg["K1"]),
            "rec_T_mean": float(rec_cfg["T_mean"]), "rec_T_hw": float(rec_cfg["T_hw"]),
            "rec_Pb_pct": float(rec_cfg["P_b_mean"]) * 100.0, "rec_U2": float(rec_cfg["U2_mean"]),
        })
        print(
            f"{sc_name:<10} | {len(passed):>2d}/12  | c2={int(min_cfg['c2'])}, K1={int(min_cfg['K1']):<8} | "
            f"{float(min_cfg['T_mean']):6.3f} +/- {float(min_cfg['T_hw']):5.3f} | "
            f"{float(min_cfg['P_b_mean'])*100:6.2f}% | {float(min_cfg['U2_mean']):5.3f} | "
            f"c2={int(rec_cfg['c2'])}, K1={int(rec_cfg['K1'])} (T={float(rec_cfg['T_mean']):.2f}p, Pb={float(rec_cfg['P_b_mean'])*100:.2f}%)"
        )

    out_path = REPORTS_DIR / "exp_c_min_sla_configs.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"[OK] Đã xuất: {out_path}\n")
    return out_rows


def audit_littles_law(raw_bcd: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    by_cfg: Dict[str, List[Dict[str, str]]] = {}
    for r in raw_bcd:
        by_cfg.setdefault(r["config_id"], []).append(r)

    audit_rows: List[Dict[str, Any]] = []
    single_gt1_runs = 0
    cfg_mean_gt1 = 0

    for cid, reps in by_cfg.items():
        r0 = reps[0]
        lam, c2, k1 = float(r0["lam"]), int(r0["c2"]), int(r0["K1"])
        tm = float(r0.get("t_end", 10000.0)) - float(r0.get("t_warmup", 2000.0))

        errs = [(int(r["seed"]), float(r["little_err_sys"]) * 100.0) for r in reps]
        worst_seed, max_single_pct = max(errs, key=lambda x: x[1])
        mean_single_pct = sum(e for _, e in errs) / len(errs)
        n_gt1 = sum(1 for _, e in errs if e > 1.0)
        single_gt1_runs += n_gt1

        l_mean = sum(float(r["L_system"]) for r in reps) / len(reps)
        x_mean = sum(float(r["X"]) for r in reps) / len(reps)
        t_mean = sum(float(r["T"]) for r in reps) / len(reps)
        ensemble_err_pct = abs(l_mean - x_mean * t_mean) / max(1e-12, l_mean) * 100.0
        if ensemble_err_pct > 1.0:
            cfg_mean_gt1 += 1
        boundary_order_pct = (2.0 * l_mean / max(1e-12, x_mean * tm)) * 100.0

        audit_rows.append({
            "config_id": cid, "lam": lam, "c2": c2, "K1": k1, "R": len(reps),
            "L_sys_mean": round(l_mean, 3),
            "ensemble_little_err_pct": round(ensemble_err_pct, 4),
            "mean_single_little_err_pct": round(mean_single_pct, 4),
            "max_single_little_err_pct": round(max_single_pct, 4),
            "worst_seed": worst_seed, "n_runs_gt_1pct": n_gt1,
            "boundary_order_2L_over_XTm_pct": round(boundary_order_pct, 4),
        })

    audit_rows.sort(key=lambda r: r["max_single_little_err_pct"], reverse=True)
    out_path = REPORTS_DIR / "exp_c_little_audit.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
        writer.writeheader()
        writer.writerows(audit_rows)

    print("=" * 114)
    print("BƯỚC 9.4 - KIỂM TOÁN SAI SỐ ĐỊNH LUẬT LITTLE (SINGLE-RUN MAX vs. ENSEMBLE MEAN & HIỆU ỨNG XE CÒN SÓT)")
    print("=" * 114)
    print(
        f"Tổng hợp {len(by_cfg)} cấu hình ({len(raw_bcd)} lượt chạy): "
        f"Ensemble Mean > 1%: {cfg_mean_gt1}/{len(by_cfg)} | Lượt đơn lẻ > 1%: {single_gt1_runs}/{len(raw_bcd)}"
    )
    print(f"[OK] Đã xuất: {out_path}\n")
    return audit_rows


def plot_fig9_pareto(exp_c: List[Dict[str, str]]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14.0, 5.6), dpi=300)
    colors = {1: "#d62728", 2: "#1f77b4", 3: "#2ca02c"}
    markers = {1: "o", 2: "s", 3: "^"}

    for ax, lam, title in [
        (axes[0], 0.6, "(a) Kịch bản Peak (λ = 0.6) — Đánh đổi ngược chiều T và P_b"),
        (axes[1], 0.7, "(b) Kịch bản Heavy (λ = 0.7) — Nút cổ chai c2 = 1 vỡ SLA hoàn toàn"),
    ]:
        sub = [r for r in exp_c if abs(float(r["lam"]) - lam) < 1e-9]
        max_pb = max(float(r["P_b_mean"]) * 100.0 for r in sub)
        max_t = max(float(r["T_mean"]) for r in sub)

        ax.fill_between([0.0, 5.0], 4.0, 8.0, color="#2ca02c", alpha=0.08, label="Vùng đạt SLA (T ≤ 8p & P_b ≤ 5%)")
        ax.axhline(8.0, color="black", linestyle="--", linewidth=1.3, label="Ngưỡng T = 8.0 phút")
        ax.axvline(5.0, color="#666666", linestyle=":", linewidth=1.4, label="Ngưỡng P_b = 5.0%")

        pts: List[Tuple[float, float, Dict[str, str]]] = []
        for c2 in (1, 2, 3):
            rows = sorted([r for r in sub if int(r["c2"]) == c2], key=lambda x: int(x["K1"]))
            xs = [float(r["P_b_mean"]) * 100.0 for r in rows]
            ys = [float(r["T_mean"]) for r in rows]
            xerr = [float(r["P_b_hw"]) * 100.0 for r in rows]
            yerr = [float(r["T_hw"]) for r in rows]
            ax.errorbar(
                xs, ys, xerr=xerr, yerr=yerr, color=colors[c2], marker=markers[c2],
                linewidth=1.9, capsize=3, markersize=6.5, label=f"c2 = {c2} cửa Payment (K1 = 3→8)",
            )
            for r, x_v, y_v in zip(rows, xs, ys):
                pts.append((x_v, y_v, r))
                dx = 5 if x_v < max_pb * 0.85 else -32
                dy = 6 if c2 != 3 else -12
                ax.annotate(f"K1={int(r['K1'])}", (x_v, y_v), xytext=(dx, dy), textcoords="offset points", fontsize=7.8, color=colors[c2])

        pareto = []
        for x_i, y_i, r_i in sorted(pts, key=lambda p: (p[0], p[1])):
            # dung sai: P_b chênh < 0,05 điểm % hoặc T chênh < 0,02 phút coi như hoà (CRN cho P_b gần như trùng giữa các c2)
            eps_x, eps_y = 0.05, 0.02
            dominated = any(
                (x_j <= x_i + eps_x and y_j <= y_i + eps_y) and (x_j < x_i - eps_x or y_j < y_i - eps_y)
                for x_j, y_j, _ in pts
            )
            if not dominated:
                pareto.append((x_i, y_i, r_i))
        if pareto:
            ax.plot([p[0] for p in pareto], [p[1] for p in pareto], linestyle="-.", color="#9467bd", linewidth=1.8, alpha=0.9, zorder=6, label="Đường đánh đổi Pareto (T, P_b)")

        if abs(lam - 0.6) < 1e-9:
            p_min = next(r for r in sub if int(r["c2"]) == 1 and int(r["K1"]) == 4)
            p_rec = next(r for r in sub if int(r["c2"]) == 2 and int(r["K1"]) == 6)
            ax.annotate(
                "Tối thiểu SLA\n(c2=1, K1=4)",
                xy=(float(p_min["P_b_mean"]) * 100.0, float(p_min["T_mean"])),
                xytext=(4.2, 6.9),
                arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.2),
                fontsize=8.2, fontweight="bold", color="#d62728",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#d62728", alpha=0.9),
            )
            ax.annotate(
                "Khuyến nghị vận hành\n(c2=2, K1=6)",
                xy=(float(p_rec["P_b_mean"]) * 100.0, float(p_rec["T_mean"])),
                xytext=(2.2, 4.4),
                arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=1.2),
                fontsize=8.2, fontweight="bold", color="#1f77b4",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#1f77b4", alpha=0.9),
            )

        ax.set_title(title, fontsize=10.5, fontweight="bold")
        ax.set_xlabel("Xác suất bị từ chối P_b (%) — Thấp hơn tốt hơn", fontsize=9.8)
        ax.set_ylabel("Thời gian end-to-end trung bình T (phút) — Thấp hơn tốt hơn", fontsize=9.8)
        ax.set_xlim(-0.3, max_pb * 1.15)
        ax.set_ylim(4.0, max_t * 1.12)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(loc="upper right", fontsize=7.6, framealpha=0.93)

    fig.suptitle(
        "Đánh đổi giữa T và P_b",
        fontsize=11.6, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    out_png = REPORTS_DIR / "fig9_pareto_T_vs_Pb.png"
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_png.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ Pareto: {out_png}")


def main() -> None:
    exp_c = _read_csv(EXP_C_CSV)
    raw_bcd = _read_csv(RAW_BCD_CSV)
    anova_rows = run_allocation_of_variation_with_sse(raw_bcd, n_reps=30)
    plot_fig10_allocation_of_variation(anova_rows)
    compute_exp_d_paired_crn(raw_bcd)
    build_min_sla_table(exp_c)
    audit_littles_law(raw_bcd)
    plot_fig9_pareto(exp_c)


if __name__ == "__main__":
    main()
