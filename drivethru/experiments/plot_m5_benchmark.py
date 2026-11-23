import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

REPORTS_DIR = Path("reports")
SUMMARY_CSV = REPORTS_DIR / "exp_m5_benchmark.csv"
PROBE_CSV = REPORTS_DIR / "exp_m5_speedup_probe.csv"
FIG6_PATH = REPORTS_DIR / "fig6_m5_walltime_throughput.png"
FIG7_PATH = REPORTS_DIR / "fig7_m5_memory_and_overhead.png"
FIG8_PATH = REPORTS_DIR / "fig8_m5_speedup_conditions.png"

ENGINE_META = {
    "sequential": {"label": "Single-thread (Sequential)", "color": "#1f77b4", "marker": "o"},
    "coroutine": {"label": "Virtual MT (Mô hình lai: Handler + BkSysFuture)", "color": "#ff7f0e", "marker": "s"},
    "multithread": {"label": "OS Multi-thread (6 Threads, Zero-Lookahead)", "color": "#d62728", "marker": "^"},
}
ENGINE_ORDER = ("sequential", "coroutine", "multithread")


def _load_rows(path: Path, str_cols: Tuple[str, ...]) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Chưa có file {path}.")
    rows: List[Dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({k: (v if k in str_cols else float(v)) for k, v in r.items()})
    return rows


def plot_fig6_walltime_throughput(rows: List[Dict[str, Any]]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.4), dpi=300)

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
    ax1.legend(loc="upper left", fontsize=8.1, framealpha=0.95)

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

    ax2.set_title("(b) Event Throughput theo Mức tải λ ($t_{end}=5,000$p, Mean ± CI 95%)", fontsize=10.8, fontweight="bold")
    ax2.set_xlabel("Tốc độ xe đến λ (xe/phút)", fontsize=10)
    ax2.set_ylabel("Thông lượng (×1,000 events/s) — Cao hơn tốt hơn", fontsize=10)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(["Light (0.2)", "Peak (0.6)", "Heavy (0.7)"])
    ax2.set_ylim(0, max_thr * 1.36)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=8.1, framealpha=0.95)

    fig.suptitle(
        "M5: Wall-time và throughput của 3 kiến trúc",
        fontsize=11.8, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG6_PATH, dpi=300, bbox_inches="tight")
    fig.savefig(FIG6_PATH.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ: {FIG6_PATH}")


def plot_fig7_memory_and_overhead(rows: List[Dict[str, Any]]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.4), dpi=300)

    # (a) Chỉ vẽ Python Heap Peak (tracemalloc) theo t_end (không vẽ RSS)
    t_ends = [2000.0, 5000.0, 10000.0]
    x_pos = np.arange(len(t_ends))
    width = 0.26
    max_mem = 0.0

    for idx, eng in enumerate(ENGINE_ORDER):
        meta = ENGINE_META[eng]
        sub = sorted(
            [r for r in rows if r["engine_name"] == eng and abs(r["lam"] - 0.6) < 1e-9],
            key=lambda x: x["t_end"],
        )
        ys = [r["peak_mem_mb_mean"] for r in sub]
        ye = [r["peak_mem_mb_ci95"] for r in sub]
        max_mem = max(max_mem, max(y + e for y, e in zip(ys, ye)))
        bars = ax1.bar(
            x_pos + (idx - 1) * width, ys, width, yerr=ye, capsize=3,
            label=meta["label"], color=meta["color"], alpha=0.88,
        )
        for bar, val, err in zip(bars, ys, ye):
            ax1.text(
                bar.get_x() + bar.get_width() / 2.0, val + err + 0.012,
                f"{val:.2f}", ha="center", va="bottom", fontsize=8.2, fontweight="bold",
            )

    ax1.set_title("(a) Python Heap Peak theo $t_{end}$ (tracemalloc — chưa gồm stack OS thread)", fontsize=10.4, fontweight="bold")
    ax1.set_xlabel("Thời lượng mô phỏng $t_{end}$ (phút)", fontsize=10)
    ax1.set_ylabel("Python Heap Peak (MB) — Thấp hơn tốt hơn", fontsize=9.8)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(["2,000", "5,000", "10,000"])
    ax1.set_ylim(0, max_mem * 1.32)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", fontsize=8.0, framealpha=0.95)

    # (b) Slowdown Ratio + Chú thích giới hạn Zero-Lookahead tại t_end = 10,000
    sub10 = {r["engine_name"]: r for r in rows if r["scenario_id"] == "scale_t10000_lam06"}
    labels = ["Single-thread\n(Sequential)", "Virtual MT\n(Mô hình lai)", "OS Multi-thread\n(6 Threads)"]
    x2 = np.arange(len(labels))
    w2 = 0.34
    slowdowns = [sub10[e]["slowdown_vs_seq"] for e in ENGINE_ORDER]
    cpu_ratios = [sub10[e]["cpu_wall_ratio_mean"] for e in ENGINE_ORDER]
    colors = [ENGINE_META[e]["color"] for e in ENGINE_ORDER]
    mt_pct1 = sub10["multithread"]["pct_single_lp_epochs_mean"]
    mt_act = sub10["multithread"]["avg_active_lps_mean"]

    b1 = ax2.bar(x2 - w2 / 2, slowdowns, w2, label="Slowdown Ratio (vs Single = 1.0x)", color=colors, alpha=0.88)
    b2 = ax2.bar(x2 + w2 / 2, cpu_ratios, w2, label="CPU Time / Wall Time Ratio", color="#555555", alpha=0.72, hatch="//")

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
    ax2.set_title("(b) Phân rã Slowdown & Giới hạn Zero-Lookahead ($t_{end}=10,000$)", fontsize=10.4, fontweight="bold")
    ax2.set_ylabel("Tỷ số (Ratio)", fontsize=9.8)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.set_ylim(0, max(max(slowdowns), max(cpu_ratios)) * 1.28)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=8.2, framealpha=0.95)

    fig.suptitle(
        "M5: Bộ nhớ và overhead",
        fontsize=11.8, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG7_PATH, dpi=300, bbox_inches="tight")
    fig.savefig(FIG7_PATH.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ: {FIG7_PATH}")


def plot_fig8_speedup_conditions(probe_rows: List[Dict[str, Any]]) -> None:
    regimes = [
        ("R1_zero_lookahead_light", "Chế độ 1:\nZero-Lookahead\n(1 LP/nhịp, nhẹ)"),
        ("R2_pos_lookahead_py_gil", "Chế độ 2:\nLookahead dương\n(6 LP/nhịp, Python GIL)"),
        ("R3_pos_lookahead_nogil_c", "Chế độ 3:\nLookahead dương\n(6 LP/nhịp, C No-GIL)"),
    ]
    x = np.arange(len(regimes))
    width = 0.25

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.2), dpi=300)
    max_sp = 0.0
    max_cpu_r = 0.0

    for idx, eng in enumerate(ENGINE_ORDER):
        meta = ENGINE_META[eng]
        sp_vals = []
        cpu_r_vals = []
        for rid, _lbl in regimes:
            rec = next(r for r in probe_rows if r["regime_id"] == rid and r["engine_name"] == eng)
            sp_vals.append(rec["speedup_vs_seq"])
            cpu_r_vals.append(rec["cpu_wall_ratio_mean"])
        max_sp = max(max_sp, max(sp_vals))
        max_cpu_r = max(max_cpu_r, max(cpu_r_vals))

        b1 = ax1.bar(x + (idx - 1) * width, sp_vals, width, label=meta["label"], color=meta["color"], alpha=0.88)
        for bar, val in zip(b1, sp_vals):
            ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.06, f"{val:.2f}x", ha="center", va="bottom", fontsize=8.3, fontweight="bold")

        b2 = ax2.bar(x + (idx - 1) * width, cpu_r_vals, width, label=meta["label"], color=meta["color"], alpha=0.88)
        for bar, val in zip(b2, cpu_r_vals):
            ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.06, f"{val:.2f}", ha="center", va="bottom", fontsize=8.3, fontweight="bold")

    ax1.axhline(1.0, color="black", linestyle="--", linewidth=1.2, label="Mốc hòa vốn (Speedup = 1.0x)")
    ax1.set_title("(a) Speedup so với Single-thread (Cao hơn 1.0x = Nhanh hơn)", fontsize=10.6, fontweight="bold")
    ax1.set_ylabel("Speedup = Wall(Single) / Wall(Engine)", fontsize=9.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([lbl for _, lbl in regimes], fontsize=8.8)
    ax1.set_ylim(0, max_sp * 1.28)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", fontsize=8.0, framealpha=0.95)

    ax2.axhline(1.0, color="gray", linestyle=":", linewidth=1.2)
    ax2.set_title("(b) Tỷ số CPU Time / Wall Time (Đo số nhân CPU thực sự khai thác)", fontsize=10.6, fontweight="bold")
    ax2.set_ylabel("CPU Time / Wall Time (~Số nhân CPU hoạt động)", fontsize=9.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels([lbl for _, lbl in regimes], fontsize=8.8)
    ax2.set_ylim(0, max_cpu_r * 1.28)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=8.0, framealpha=0.95)

    fig.suptitle(
        "M5: Zero-lookahead và GIL",
        fontsize=11.8, fontweight="bold", y=0.99,
    )
    plt.tight_layout()
    fig.savefig(FIG8_PATH, dpi=300, bbox_inches="tight")
    fig.savefig(FIG8_PATH.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Đã xuất biểu đồ: {FIG8_PATH}")


if __name__ == "__main__":
    summary_rows = _load_rows(SUMMARY_CSV, ("scenario_id", "engine_name"))
    plot_fig6_walltime_throughput(summary_rows)
    plot_fig7_memory_and_overhead(summary_rows)
    if PROBE_CSV.exists():
        probe_rows = _load_rows(PROBE_CSV, ("regime_id", "regime_label", "engine_name"))
        plot_fig8_speedup_conditions(probe_rows)
