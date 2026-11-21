import csv
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np

REPORTS_DIR = Path("reports")
SUMMARY_CSV = REPORTS_DIR / "exp_m5_benchmark.csv"
FIG6_PATH = REPORTS_DIR / "fig6_m5_walltime_throughput.png"
FIG7_PATH = REPORTS_DIR / "fig7_m5_memory_and_overhead.png"

ENGINE_META = {
    "sequential": {"label": "Single-thread (Sequential)", "color": "#1f77b4", "marker": "o"},
    "coroutine": {"label": "Virtual Multi-thread (Coroutine + BkSysFuture)", "color": "#ff7f0e", "marker": "s"},
    "multithread": {"label": "OS Multi-thread (6 Threads + Coordinator)", "color": "#d62728", "marker": "^"},
}
ENGINE_ORDER = ("sequential", "coroutine", "multithread")


def _load_summary() -> Dict[str, List[Dict[str, float]]]:
    if not SUMMARY_CSV.exists():
        raise FileNotFoundError(f"Chưa có file {SUMMARY_CSV}. Hãy chạy run_m5_benchmark.py trước.")
    grouped: Dict[str, List[Dict[str, float]]] = {e: [] for e in ENGINE_ORDER}
    with SUMMARY_CSV.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            eng = row["engine_name"]
            if eng in grouped:
                grouped[eng].append({k: float(v) for k, v in row.items() if k != "engine_name"})
    for eng in grouped:
        grouped[eng].sort(key=lambda r: r["t_end"])
    return grouped


def plot_fig6_walltime_throughput(data: Dict[str, List[Dict[str, float]]]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.4), dpi=300)

    # (a) Wall-clock Time vs t_end
    max_wall = 0.0
    for eng in ENGINE_ORDER:
        meta = ENGINE_META[eng]
        rows = data[eng]
        xs = [r["t_end"] for r in rows]
        ys = [r["wall_time_mean"] for r in rows]
        yerr = [r["wall_time_ci95"] for r in rows]
        max_wall = max(max_wall, max(y + e for y, e in zip(ys, yerr)))
        ax1.errorbar(
            xs, ys, yerr=yerr, label=meta["label"],
            color=meta["color"], marker=meta["marker"], linewidth=2.0, capsize=4,
        )
        last = rows[-1]
        ax1.annotate(
            f"{last['wall_time_mean']:.2f}s ({last['slowdown_vs_seq']:.2f}x)",
            xy=(last["t_end"], last["wall_time_mean"] + last["wall_time_ci95"]),
            xytext=(-78, 8), textcoords="offset points",
            fontsize=8.5, fontweight="bold", color=meta["color"],
        )

    ax1.set_title("(a) Wall-clock Time theo Quy mô Mô phỏng (Mean ± CI 95%)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Thời lượng mô phỏng $t_{end}$ (phút)", fontsize=10)
    ax1.set_ylabel("Wall-clock Time (giây) — Thấp hơn tốt hơn", fontsize=10)
    ax1.set_xticks([2000, 5000, 10000])
    ax1.set_xlim(1500, 10600)
    ax1.set_ylim(0, max_wall * 1.18)
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", fontsize=8.5, framealpha=0.95)

    # (b) Event Throughput (events/sec) — đặt nhãn trên hẳn đầu râu CI95 và nới ylim để legend không che
    t_ends = [2000, 5000, 10000]
    x_pos = np.arange(len(t_ends))
    width = 0.26
    max_thr = 0.0

    for idx, eng in enumerate(ENGINE_ORDER):
        meta = ENGINE_META[eng]
        rows = data[eng]
        ys = [r["events_per_sec_mean"] / 1000.0 for r in rows]
        yerr = [r["events_per_sec_ci95"] / 1000.0 for r in rows]
        max_thr = max(max_thr, max(y + e for y, e in zip(ys, yerr)))
        bars = ax2.bar(
            x_pos + (idx - 1) * width, ys, width, yerr=yerr, capsize=3,
            label=meta["label"], color=meta["color"], alpha=0.88,
        )
        for bar, val, err in zip(bars, ys, yerr):
            ax2.text(
                bar.get_x() + bar.get_width() / 2.0,
                val + err + 1.4,
                f"{val:.1f}k",
                ha="center", va="bottom", fontsize=8.2, fontweight="bold",
            )

    ax2.set_title("(b) Event Throughput (×1,000 events/sec, Mean ± CI 95%)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Thời lượng mô phỏng $t_{end}$ (phút)", fontsize=10)
    ax2.set_ylabel("Thông lượng xử lý (×1,000 events/s) — Cao hơn tốt hơn", fontsize=10)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels([f"{t:,}" for t in t_ends])
    ax2.set_ylim(0, max_thr * 1.32)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", ncol=1, fontsize=8.3, framealpha=0.95)

    fig.suptitle(
        "M5 Benchmark (1-Core, CPython 3.12 GIL): So sánh Hiệu năng 3 Kiến trúc DES (Fidelity Error = 0.0)",
        fontsize=12, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG6_PATH, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất lại biểu đồ: {FIG6_PATH}")


def plot_fig7_memory_and_overhead(data: Dict[str, List[Dict[str, float]]]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.4), dpi=300)

    # (a) Peak Memory Footprint (MB) — đặt nhãn trên hẳn đầu râu CI95
    t_ends = [2000, 5000, 10000]
    x_pos = np.arange(len(t_ends))
    width = 0.26
    max_mem = 0.0

    for idx, eng in enumerate(ENGINE_ORDER):
        meta = ENGINE_META[eng]
        rows = data[eng]
        ys = [r["peak_mem_mb_mean"] for r in rows]
        yerr = [r["peak_mem_mb_ci95"] for r in rows]
        max_mem = max(max_mem, max(y + e for y, e in zip(ys, yerr)))
        bars = ax1.bar(
            x_pos + (idx - 1) * width, ys, width, yerr=yerr, capsize=3,
            label=meta["label"], color=meta["color"], alpha=0.88,
        )
        for bar, val, err in zip(bars, ys, yerr):
            ax1.text(
                bar.get_x() + bar.get_width() / 2.0,
                val + err + 0.012,
                f"{val:.2f}",
                ha="center", va="bottom", fontsize=8.2, fontweight="bold",
            )

    ax1.set_title("(a) Peak Python Heap Memory Footprint (tracemalloc, MB)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Thời lượng mô phỏng $t_{end}$ (phút)", fontsize=10)
    ax1.set_ylabel("Peak Memory (MB) — Thấp hơn tốt hơn", fontsize=10)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels([f"{t:,}" for t in t_ends])
    ax1.set_ylim(0, max_mem * 1.24)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", fontsize=8.3, framealpha=0.95)

    # (b) Slowdown Ratio và Tỷ số CPU/Wall tại t_end = 10,000 phút
    labels = ["Single-thread\n(Sequential)", "Virtual MT\n(Coroutine)", "OS Multi-thread\n(6 Threads)"]
    slowdowns = [data[e][-1]["slowdown_vs_seq"] for e in ENGINE_ORDER]
    cpu_ratios = [data[e][-1]["cpu_wall_ratio_mean"] for e in ENGINE_ORDER]
    colors = [ENGINE_META[e]["color"] for e in ENGINE_ORDER]

    x2 = np.arange(len(labels))
    w2 = 0.35
    b1 = ax2.bar(x2 - w2 / 2, slowdowns, w2, label="Slowdown Ratio (vs Single = 1.0x)", color=colors, alpha=0.88)
    b2 = ax2.bar(x2 + w2 / 2, cpu_ratios, w2, label="CPU Time / Wall Time Ratio", color="#555555", alpha=0.72, hatch="//")

    for bar, val in zip(b1, slowdowns):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.08, f"{val:.2f}x", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
    for bar, val in zip(b2, cpu_ratios):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.08, f"{val:.2f}", ha="center", va="bottom", fontsize=8.5)

    ax2.axhline(1.0, color="gray", linestyle=":", linewidth=1.2)
    ax2.set_title("(b) Phân tích Chi phí Điều phối & GIL tại $t_{end} = 10,000$ phút", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Tỷ số (Ratio)", fontsize=10)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.set_ylim(0, max(max(slowdowns), max(cpu_ratios)) * 1.22)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=8.5, framealpha=0.95)

    fig.suptitle(
        "M5 Benchmark: Dấu chân Bộ nhớ (RAM) và Phân rã Overhead Điều phối trên CPython 3.12 (GIL)",
        fontsize=12, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG7_PATH, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất lại biểu đồ: {FIG7_PATH}")


if __name__ == "__main__":
    summary_data = _load_summary()
    plot_fig6_walltime_throughput(summary_data)
    plot_fig7_memory_and_overhead(summary_data)
