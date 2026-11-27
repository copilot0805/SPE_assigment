import csv
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy tệp dữ liệu: {path}. Hãy chạy thí nghiệm tương ứng trước!")
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plot_fig1_e2e_time(exp_c: List[Dict[str, str]], out_dir: Path) -> None:
    """Biểu đồ 1: Thời gian end-to-end T và phân vị P95(T) theo lambda với từng mức c2 (tại K1=8)."""
    sub = [r for r in exp_c if int(r["K1"]) == 8]
    lambdas = sorted({float(r["lam"]) for r in sub})
    c2_list = [1, 2, 3]
    colors = {1: "#d62728", 2: "#1f77b4", 3: "#2ca02c"}

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    for c2 in c2_list:
        rows = sorted([r for r in sub if int(r["c2"]) == c2], key=lambda x: float(x["lam"]))
        xs = [float(r["lam"]) for r in rows]
        t_m = [float(r["T_mean"]) for r in rows]
        t_hw = [float(r["T_hw"]) for r in rows]
        p95_m = [float(r["P95_T_mean"]) for r in rows]
        p95_hw = [float(r["P95_T_hw"]) for r in rows]

        axes[0].errorbar(xs, t_m, yerr=t_hw, marker="o", capsize=4, linewidth=2,
                         color=colors[c2], label=f"c2 = {c2} cửa Payment")
        axes[1].errorbar(xs, p95_m, yerr=p95_hw, marker="s", capsize=4, linewidth=2,
                         color=colors[c2], label=f"c2 = {c2} cửa Payment")

    axes[0].axhline(8.0, color="black", linestyle="--", linewidth=1.4, label="Ngưỡng SLA (T = 8 phút)")
    axes[0].set_title("Thời gian hoàn thành trung bình T theo tải (K1 = 8)", fontweight="bold")
    axes[0].set_xlabel("Tốc độ xe đến λ (xe/phút)")
    axes[0].set_ylabel("Thời gian trung bình T (phút)")
    axes[0].set_xticks(lambdas)
    axes[0].grid(True, linestyle="--", alpha=0.5)
    axes[0].legend()

    axes[1].set_title("Phân vị 95% thời gian hoàn thành P95(T) theo tải (K1 = 8)", fontweight="bold")
    axes[1].set_xlabel("Tốc độ xe đến λ (xe/phút)")
    axes[1].set_ylabel("Phân vị P95(T) (phút)")
    axes[1].set_xticks(lambdas)
    axes[1].grid(True, linestyle="--", alpha=0.5)
    axes[1].legend()

    plt.suptitle("T và P95(T) theo λ và c2", fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(out_dir / "fig1_e2e_time_by_lambda_c2.png", dpi=180)
    plt.savefig(out_dir / "fig1_e2e_time_by_lambda_c2.pdf")
    plt.close(fig)


def plot_fig2_blocking_prob(exp_c: List[Dict[str, str]], out_dir: Path) -> None:
    """Biểu đồ 2: Xác suất từ chối P_b (%) theo sức chứa Order K1 tại từng mức workload lam (c2=2)."""
    sub = [r for r in exp_c if int(r["c2"]) == 2]
    k1_vals = sorted({int(r["K1"]) for r in sub})
    lam_labels = [(0.2, "Light (λ=0.2)"), (0.4, "Normal (λ=0.4)"), (0.6, "Peak (λ=0.6)"), (0.7, "Heavy (λ=0.7)")]
    colors = ["#2ca02c", "#1f77b4", "#ff7f0e", "#d62728"]

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    for (lam, label), col in zip(lam_labels, colors):
        rows = sorted([r for r in sub if abs(float(r["lam"]) - lam) < 1e-9], key=lambda x: int(x["K1"]))
        xs = [int(r["K1"]) for r in rows]
        ys = [float(r["P_b_mean"]) * 100.0 for r in rows]
        yerr = [float(r["P_b_hw"]) * 100.0 for r in rows]
        ax.errorbar(xs, ys, yerr=yerr, marker="o", capsize=4, linewidth=2, color=col, label=label)

    ax.axhline(5.0, color="black", linestyle="--", linewidth=1.4, label="Ngưỡng SLA (P_b = 5%)")
    ax.set_title("Xác suất từ chối P_b theo K1", fontweight="bold")
    ax.set_xlabel("Sức chứa tối đa trạm Order K1 (xe)")
    ax.set_ylabel("Xác suất từ chối P_b (%)")
    ax.set_xticks(k1_vals)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "fig2_blocking_prob_by_K1.png", dpi=180)
    plt.savefig(out_dir / "fig2_blocking_prob_by_K1.pdf")
    plt.close(fig)


def plot_fig3_utilization(exp_c: List[Dict[str, str]], out_dir: Path) -> None:
    """Biểu đồ 3: Độ sử dụng tài nguyên U_i của 4 trạm theo lam (so sánh c2=1 Baseline và c2=2)."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
    stations = [
        ("U1", "Order (U1)", "#1f77b4", "o"),
        ("U2", "Payment (U2)", "#d62728", "s"),
        ("U3", "Kitchen (U3)", "#ff7f0e", "^"),
        ("U4", "Pickup (U4)", "#2ca02c", "d"),
    ]

    for ax, c2, title in [
        (axes[0], 1, "Cấu hình cơ sở (c2 = 1, K1 = 8) — Nút cổ chai tại Payment"),
        (axes[1], 2, "Cấu hình nâng cấp (c2 = 2, K1 = 8) — Giải tỏa nút cổ chai"),
    ]:
        rows = sorted([r for r in exp_c if int(r["c2"]) == c2 and int(r["K1"]) == 8], key=lambda x: float(x["lam"]))
        xs = [float(r["lam"]) for r in rows]
        for key, label, col, mk in stations:
            ys = [float(r[f"{key}_mean"]) * 100.0 for r in rows]
            yerr = [float(r[f"{key}_hw"]) * 100.0 for r in rows]
            ax.errorbar(xs, ys, yerr=yerr, marker=mk, capsize=4, linewidth=2, color=col, label=label)
        ax.set_title(title, fontweight="bold")
        ax.set_xlabel("Tốc độ xe đến λ (xe/phút)")
        ax.set_xticks(xs)
        ax.set_ylim(0, 100)
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend()

    axes[0].set_ylabel("Độ sử dụng tài nguyên Utilization (%)")
    plt.suptitle("Độ sử dụng U_i theo λ", fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(out_dir / "fig3_utilization_bottleneck.png", dpi=180)
    plt.savefig(out_dir / "fig3_utilization_bottleneck.pdf")
    plt.close(fig)


def plot_fig4_exp_a(exp_a_path: Path, out_dir: Path) -> None:
    """Biểu đồ 4: Đối chiếu Lý thuyết giải tích và Mô phỏng cho 6 mô hình đơn (Exp A)."""
    rows = _read_csv(exp_a_path)
    models_order = [
        ("M/M/1", "W", "Thời gian đáp ứng W (phút)"),
        ("M/M/1/4", "P_b", "Xác suất từ chối P_b"),
        ("M/M/inf", "L", "Số xe trung bình L (xe)"),
        ("M/M/3/3 (Erlang B)", "P_b", "Xác suất từ chối Erlang B (P_b)"),
        ("M/M/2 (Erlang C)", "P_w", "Xác suất phải chờ Erlang C (P_w)"),
        ("M/M/2/5", "W", "Thời gian đáp ứng W (phút)"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(15, 8.8))
    axes = axes.flatten()
    for idx, (m_name, metric, ylabel) in enumerate(models_order):
        ax = axes[idx]
        sub = sorted(
            [r for r in rows if r["model"] == m_name and r["metric"] == metric],
            key=lambda x: float(x["rho_or_a"]),
        )
        x = np.arange(len(sub))
        w = 0.35
        th = [float(r["theory"]) for r in sub]
        sm = [float(r["sim_mean"]) for r in sub]
        hw = [float(r["ci95_half_width"]) for r in sub]

        ax.bar(x - w / 2, th, w, label="Lý thuyết (Giải tích)", color="#2b5c8f")
        ax.bar(x + w / 2, sm, w, yerr=hw, capsize=4, label="Mô phỏng (Mean ± CI95)", color="#e07a5f")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{r['code']}\n(λ={float(r['lambda']):.1f})" for r in sub], fontsize=9)
        ax.set_title(f"{m_name} — Chỉ số {metric}", fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.legend(fontsize=8)

    plt.suptitle("Lý thuyết và mô phỏng — Exp A", fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(out_dir / "fig4_exp_a_validation.png", dpi=180)
    plt.savefig(out_dir / "fig4_exp_a_validation.pdf")
    plt.close(fig)


def plot_fig5_exp_d(exp_d: List[Dict[str, str]], out_dir: Path) -> None:
    """Biểu đồ 5: Biểu đồ cột so sánh T, P_b và U1 giữa Không chặn và Chặn theo lam (Exp D)."""
    lambdas = [0.4, 0.6, 0.7]
    nb_map = {float(r["lam"]): r for r in exp_d if "ExpD_NB" in r["exp_tags"]}
    blk_map = {float(r["lam"]): r for r in exp_d if "ExpD_BLK" in r["exp_tags"]}

    specs = [
        ("T", 1.0, "Thời gian hoàn thành T (phút)", "Thời gian end-to-end T"),
        ("P_b", 100.0, "Xác suất từ chối P_b (%)", "Xác suất từ chối tại Order (P_b)"),
        ("U1", 100.0, "Độ sử dụng Order U1 (%)", "Độ sử dụng trạm Order (U1)"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.0))
    x = np.arange(len(lambdas))
    w = 0.35

    for ax, (key, scale, ylabel, title) in zip(axes, specs):
        nb_m = [float(nb_map[l][f"{key}_mean"]) * scale for l in lambdas]
        nb_hw = [float(nb_map[l][f"{key}_hw"]) * scale for l in lambdas]
        blk_m = [float(blk_map[l][f"{key}_mean"]) * scale for l in lambdas]
        blk_hw = [float(blk_map[l][f"{key}_hw"]) * scale for l in lambdas]

        ax.bar(x - w / 2, nb_m, w, yerr=nb_hw, capsize=4, label="Không chặn (Non-blocking)", color="#2a9d8f")
        ax.bar(x + w / 2, blk_m, w, yerr=blk_hw, capsize=4, label="Có chặn (Blocking)", color="#e76f51")
        ax.set_xticks(x)
        ax.set_xticklabels([f"λ = {l:.1f}" for l in lambdas])
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.legend(fontsize=8.5)

    plt.suptitle("Không chặn và có chặn — Exp D", fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.93])
    plt.savefig(out_dir / "fig5_exp_d_blocking_vs_nonblocking.png", dpi=180)
    plt.savefig(out_dir / "fig5_exp_d_blocking_vs_nonblocking.pdf")
    plt.close(fig)


def main() -> None:
    out_dir = Path("reports")
    exp_c = _read_csv(out_dir / "exp_c_summary.csv")
    exp_d = _read_csv(out_dir / "exp_d_summary.csv")

    plot_fig1_e2e_time(exp_c, out_dir)
    plot_fig2_blocking_prob(exp_c, out_dir)
    plot_fig3_utilization(exp_c, out_dir)
    if (out_dir / "exp_a_validation.csv").exists():
        plot_fig4_exp_a(out_dir / "exp_a_validation.csv", out_dir)
    plot_fig5_exp_d(exp_d, out_dir)

    print("[Plot] Đã xuất thành công trọn bộ 5 biểu đồ PNG vào thư mục reports/:")
    for p in sorted(out_dir.glob("fig*.png")):
        print(f"  - {p}")


if __name__ == "__main__":
    main()
