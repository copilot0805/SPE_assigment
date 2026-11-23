import csv
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np

REPORTS_DIR = Path("reports")
SUMMARY_CSV = REPORTS_DIR / "exp_m5_benchmark.csv"
FIG6_PATH = REPORTS_DIR / "fig6_m5_walltime_throughput.png"
FIG7_PATH = REPORTS_DIR / "fig7_m5_memory_and_overhead.png"

ENGINE_META = {
    "sequential": {"label": "Single-thread (Sequential)", "color": "#1f77b4", "marker": "o"},
    "coroutine": {"label": "Virtual MT (Coroutine + BkSysFuture)", "color": "#ff7f0e", "marker": "s"},
    "multithread": {"label": "OS Multi-thread (6 Threads, Zero-Lookahead)", "color": "#d62728", "marker": "^"},
}
ENGINE_ORDER = ("sequential", "coroutine", "multithread")


def _load_rows() -> List[Dict[str, Any]]:
    if not SUMMARY_CSV.exists():
        raise FileNotFoundError(f"Chưa có file {SUMMARY_CSV}. Hãy chạy run_m5_benchmark.py trước.")
    rows: List[Dict[str, Any]] = []
    with SUMMARY_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            parsed: Dict[str, Any] = {}
            for k, v in r.items():
                parsed[k] = v if k in ("scenario_id", "engine_name") else float(v)
            rows.append(parsed)
    return rows


def plot_fig6_walltime_throughput(rows: List[Dict[str, Any]]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.4), dpi=300)

    # (a) Wall-clock Time theo t_end (tại Peak lam = 0.6)
    max_w = 0.0
    for eng in ENGINE_ORDER:
        meta = ENGINE_META[eng]
        sub = sorted(
            [r for r in rows if r["engine_name"] == eng and abs(r["lam"] - 0.6) < 1e-9],
            key=lambda x: x["t_end"],
        )
        xs = [r["t_end"] for r in sub]
        ys = [r["wall_time_mean"] for r in sub]
        ye = [r["wall_time_ci95"] for r in sub]
        max_w = max(max_w, max(y + e for y, e in zip(ys, ye)))
        ax1.errorbar(
            xs, ys, yerr=ye, label=meta["label"],
            color=meta["color"], marker=meta["marker"], linewidth=2.0, capsize=4,
        )
        last = sub[-1]
        ax1.annotate(
            f"{last['wall_time_mean']:.2f}s ({last['slowdown_vs_seq']:.2f}x)",
            xy=(last["t_end"], last["wall_time_mean"] + last["wall_time_ci95"]),
            xytext=(-78, 8), textcoords="offset points",
            fontsize=8.3, fontweight="bold", color=meta["color"],
        )

    ax1.set_title("(a) Wall-clock Time theo Quy mô $t_{end}$ (Peak λ=0.6, Mean ± CI 95%)", fontsize=10.8, fontweight="bold")
    ax1.set_xlabel("Thời lượng mô phỏng $t_{end}$ (phút)", fontsize=10)
    ax1.set_ylabel("Wall-clock Time (giây) — Thấp hơn tốt hơn", fontsize=10)
    ax1.set_xticks([2000, 5000, 10000])
    ax1.set_xlim(1500, 10600)
    ax1.set_ylim(0, max_w * 1.18)
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", fontsize=8.3, framealpha=0.95)

    # (b) Event Throughput theo mức tải thực λ ∈ {0.2, 0.6, 0.7} (tại t_end = 5,000)
    lams = [0.2, 0.6, 0.7]
    x_pos = np.arange(len(lams))
    width = 0.26
    max_thr = 0.0

    for idx, eng in enumerate(ENGINE_ORDER):
        meta = ENGINE_META[eng]
        sub = sorted(
            [r for r in rows if r["engine_name"] == eng and abs(r["t_end"] - 5000.0) < 1e-9],
            key=lambda x: x["lam"],
        )
        ys = [r["events_per_sec_mean"] / 1000.0 for r in sub]
        ye = [r["events_per_sec_ci95"] / 1000.0 for r in sub]
        max_thr = max(max_thr, max(y + e for y, e in zip(ys, ye)))
        bars = ax2.bar(
            x_pos + (idx - 1) * width, ys, width, yerr=ye, capsize=3,
            label=meta["label"], color=meta["color"], alpha=0.88,
        )
        for bar, val, err in zip(bars, ys, ye):
            ax2.text(
                bar.get_x() + bar.get_width() / 2.0, val + err + 1.4,
                f"{val:.1f}k", ha="center", va="bottom", fontsize=8.2, fontweight="bold",
            )

    ax2.set_title("(b) Event Throughput theo Mức tải λ (t_end = 5,000p, Mean ± CI 95%)", fontsize=10.8, fontweight="bold")
    ax2.set_xlabel("Tốc độ xe đến λ (xe/phút)", fontsize=10)
    ax2.set_ylabel("Thông lượng (×1,000 events/s) — Cao hơn tốt hơn", fontsize=10)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(["Light (0.2)", "Peak (0.6)", "Heavy (0.7)"])
    ax2.set_ylim(0, max_thr * 1.34)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=8.3, framealpha=0.95)

    fig.suptitle(
        "M5 Benchmark (1-Core, CPython 3.12): So sánh 3 Kiến trúc DES (Car-by-Car Fidelity Error = 0.0)",
        fontsize=12, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG6_PATH, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ: {FIG6_PATH}")


def plot_fig7_memory_and_overhead(rows: List[Dict[str, Any]]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.4), dpi=300)

    # (a) So sánh Python Heap (tracemalloc) vs OS RSS tại t_end = 10,000 (Peak)
    sub10 = {r["engine_name"]: r for r in rows if r["scenario_id"] == "scale_t10000_lam06"}
    labels = ["Single-thread\n(Sequential)", "Virtual MT\n(Coroutine)", "OS Multi-thread\n(6 Threads)"]
    x = np.arange(len(labels))
    w = 0.34

    heaps = [sub10[e]["peak_mem_mb_mean"] for e in ENGINE_ORDER]
    rss_vals = [sub10[e]["rss_mb_mean"] for e in ENGINE_ORDER]
    colors = [ENGINE_META[e]["color"] for e in ENGINE_ORDER]

    ax1_r = ax1.twinx()
    b_heap = ax1.bar(x - w / 2, heaps, w, label="Python Heap Peak (tracemalloc, trái)", color=colors, alpha=0.88)
    b_rss = ax1_r.bar(x + w / 2, rss_vals, w, label="OS RSS / Working Set (gồm stack thread, phải)", color="#444444", alpha=0.65, hatch="//")

    for bar, val in zip(b_heap, heaps):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.015, f"{val:.2f}", ha="center", va="bottom", fontsize=8.3, fontweight="bold")
    for bar, val in zip(b_rss, rss_vals):
        ax1_r.text(bar.get_x() + bar.get_width() / 2, val + 0.6, f"{val:.1f}", ha="center", va="bottom", fontsize=8.3)

    ax1.set_title("(a) Bộ nhớ tại $t_{end}=10,000$: Python Heap vs. OS RSS (MB)", fontsize=10.8, fontweight="bold")
    ax1.set_ylabel("Python Heap Peak — tracemalloc (MB)", fontsize=9.8)
    ax1_r.set_ylabel("OS Process RSS / Working Set (MB)", fontsize=9.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylim(0, max(heaps) * 1.32)
    ax1_r.set_ylim(0, max(rss_vals) * 1.32)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.35)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax1_r.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8.0, framealpha=0.95)

    # (b) Slowdown Ratio + Chú thích nguyên nhân Zero-Lookahead (% epoch chỉ có 1 LP chạy)
    slowdowns = [sub10[e]["slowdown_vs_seq"] for e in ENGINE_ORDER]
    cpu_ratios = [sub10[e]["cpu_wall_ratio_mean"] for e in ENGINE_ORDER]
    mt_pct1 = sub10["multithread"]["pct_single_lp_epochs_mean"]
    mt_act = sub10["multithread"]["avg_active_lps_mean"]

    b1 = ax2.bar(x - w / 2, slowdowns, w, label="Slowdown Ratio (vs Single = 1.0x)", color=colors, alpha=0.88)
    b2 = ax2.bar(x + w / 2, cpu_ratios, w, label="CPU Time / Wall Time Ratio", color="#555555", alpha=0.72, hatch="//")

    for bar, val in zip(b1, slowdowns):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.08, f"{val:.2f}x", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
    for bar, val in zip(b2, cpu_ratios):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.08, f"{val:.2f}", ha="center", va="bottom", fontsize=8.5)

    ax2.axhline(1.0, color="gray", linestyle=":", linewidth=1.2)
    ax2.text(
        0.98, 0.96,
        f"OS-Thread (Zero-Lookahead):\n• {mt_pct1:.1f}% nhịp chỉ có 1 LP chạy\n• TB {mt_act:.2f} LP/nhịp (trần ~{mt_act:.2f}x)",
        transform=ax2.transAxes, ha="right", va="top", fontsize=8.3,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#fff5f5", edgecolor="#d62728", alpha=0.92),
    )
    ax2.set_title("(b) Phân rã Slowdown & Giới hạn Zero-Lookahead ($t_{end}=10,000$)", fontsize=10.8, fontweight="bold")
    ax2.set_ylabel("Tỷ số (Ratio)", fontsize=9.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.set_ylim(0, max(max(slowdowns), max(cpu_ratios)) * 1.28)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=8.2, framealpha=0.95)

    fig.suptitle(
        "M5 Benchmark: Dấu chân Bộ nhớ (Heap & OS RSS) và Phân tích Nguyên nhân Overhead",
        fontsize=12, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG7_PATH, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ: {FIG7_PATH}")


if __name__ == "__main__":
    all_rows = _load_rows()
    plot_fig6_walltime_throughput(all_rows)
    plot_fig7_memory_and_overhead(all_rows)
