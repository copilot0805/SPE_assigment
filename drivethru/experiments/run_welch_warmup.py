import csv
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib.pyplot as plt

from drivethru.config.simulation_config import DriveThruParams
from drivethru.experiments.run_single import run_drivethru_network


def _welch_seed_worker(args: Tuple[DriveThruParams, int, float, int, float]) -> Tuple[List[float], float, float]:
    """Chạy 1 replication với t_warmup=0, gom T theo bin thời gian đến trên miền hợp lệ [0, t_valid_end)."""
    params, seed, bin_width, n_bins, t_valid_end = args
    res = run_drivethru_network(
        params=params,
        seed=seed,
        dispatcher="sequential",
        verify_invariants=True,
        record_trace=True,
    )
    sums = [0.0] * n_bins
    counts = [0] * n_bins
    all_t: List[float] = []
    post_t: List[float] = []
    for t_arr, _t_dep, e2e in res["departure_trace"]:
        idx = int(t_arr // bin_width)
        if 0 <= idx < n_bins:
            sums[idx] += e2e
            counts[idx] += 1
        if t_arr < t_valid_end:
            all_t.append(e2e)
            if t_arr >= 2000.0:
                post_t.append(e2e)

    bins_mean = [sums[i] / counts[i] if counts[i] > 0 else math.nan for i in range(n_bins)]
    mean_all = sum(all_t) / len(all_t) if all_t else 0.0
    mean_post = sum(post_t) / len(post_t) if post_t else 0.0
    return bins_mean, mean_all, mean_post


def welch_moving_average(series: List[float], w: int) -> List[float]:
    m = len(series)
    out: List[float] = []
    for i in range(m):
        half = min(w, i, m - 1 - i)
        vals = [series[j] for j in range(i - half, i + half + 1) if not math.isnan(series[j])]
        out.append(sum(vals) / len(vals) if vals else math.nan)
    return out


def run_welch_study(
    num_replications: int = 60,
    t_end: float = 5000.0,
    bin_width: float = 50.0,
    window_w: int = 5,
    max_workers: int = 4,
) -> None:
    """
    Kiểm chứng độ đủ của t_warmup = 2000 phút bằng phương pháp Welch (R=60 seeds, dải ±5%).
    Loại bỏ 4 bin cắt cụt cuối + w bin co cửa sổ ở mép phải để mức ổn định không bị kéo tụt giả tạo.
    """
    n_bins = int(t_end // bin_width)
    usable_bins = n_bins - 4                 # Bỏ 200 phút cuối do hiệu ứng cắt cụt xe đến sát t_end
    valid_bins = usable_bins - window_w      # Bỏ thêm w bin cuối nơi cửa sổ Welch co lại
    t_valid_end = valid_bins * bin_width

    scenarios = [
        ("Heavy_c2_1_K1_8", "Heavy (λ=0.7, c2=1, ρ2=0.875)", DriveThruParams(lam=0.7, c2=1, K1=8, t_warmup=0.0, t_end=t_end)),
        ("Peak_c2_1_K1_8", "Peak (λ=0.6, c2=1, ρ2=0.750)", DriveThruParams(lam=0.6, c2=1, K1=8, t_warmup=0.0, t_end=t_end)),
    ]

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_rows: List[Dict[str, Any]] = []

    fig, axes = plt.subplots(1, 2, figsize=(13.8, 5.2), dpi=200)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for ax, (sc_id, sc_label, params) in zip(axes, scenarios):
            tasks = [(params, seed, bin_width, n_bins, t_valid_end) for seed in range(1, num_replications + 1)]
            outputs = list(executor.map(_welch_seed_worker, tasks))
            rep_curves = [o[0] for o in outputs]
            mean_no_warmup = sum(o[1] for o in outputs) / len(outputs)
            mean_with_warmup = sum(o[2] for o in outputs) / len(outputs)
            bias_pct = (mean_no_warmup - mean_with_warmup) / mean_with_warmup * 100.0

            cross_mean_full: List[float] = []
            for j in range(usable_bins):
                vals = [c[j] for c in rep_curves if not math.isnan(c[j])]
                cross_mean_full.append(sum(vals) / len(vals) if vals else math.nan)

            welch_full = welch_moving_average(cross_mean_full, w=window_w)

            # Chỉ giữ miền hợp lệ [0, t_valid_end) đã bỏ w bin mép phải
            cross_mean = cross_mean_full[:valid_bins]
            welch_smooth = welch_full[:valid_bins]
            t_axis = [(j + 0.5) * bin_width for j in range(valid_bins)]

            steady_vals = [y for t_val, y in zip(t_axis, welch_smooth) if t_val >= 2000.0 and not math.isnan(y)]
            steady_mean = sum(steady_vals) / len(steady_vals)
            max_dev = max(abs(y - steady_mean) / steady_mean * 100.0 for y in steady_vals)

            print(
                f"[Welch R={num_replications}] {sc_label} (miền hợp lệ [0, {int(t_valid_end)}) phút):\n"
                f"  - T ổn định theo xe [2000, {int(t_valid_end)}) = {mean_with_warmup:.3f} phút | "
                f"Không bỏ warm-up = {mean_no_warmup:.3f} phút (lệch {bias_pct:+.2f}%)\n"
                f"  - Mức bình ổn Welch [2000, {int(t_valid_end)}) = {steady_mean:.3f} phút | "
                f"Dao động nhiễu cực đại (R={num_replications}): {max_dev:.2f}%"
            )

            for t_val, y_raw, y_sm in zip(t_axis, cross_mean, welch_smooth):
                csv_rows.append({
                    "scenario": sc_id,
                    "t_mid": t_val,
                    "cross_rep_mean_T": y_raw,
                    "welch_ma_T": y_sm,
                    "steady_mean_after_2000": steady_mean,
                })

            ax.axhspan(steady_mean * 0.95, steady_mean * 1.05, color="#2ca02c", alpha=0.12, label="Dải bình ổn ±5%")
            ax.plot(t_axis, cross_mean, color="#9ecae1", linewidth=1.1, alpha=0.8, label=f"Trung bình {num_replications} seeds (thô)")
            ax.plot(t_axis, welch_smooth, color="#1f77b4", linewidth=2.2, label=f"Trung bình động Welch (w={window_w})")
            ax.axvline(2000.0, color="#d62728", linestyle="--", linewidth=1.6, label="Mốc chọn t_warmup = 2000 phút")
            ax.axhline(steady_mean, color="#2ca02c", linestyle=":", linewidth=1.4, label=f"Mức ổn định = {steady_mean:.2f} phút")
            ax.set_title(sc_label, fontweight="bold")
            ax.set_xlabel("Thời gian mô phỏng t (phút) — phần dao động sau t=2000 là nhiễu R=60")
            ax.set_ylabel("Thời gian end-to-end trung bình T(t) (phút)")
            ax.grid(True, linestyle="--", alpha=0.45)
            ax.legend(fontsize=8.2, loc="lower right")

    out_csv = reports_dir / "exp_welch_warmup.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    fig.suptitle(
        f"Kiểm chứng độ đủ Warm-up bằng Phương pháp Welch (R={num_replications} seeds, Δt={int(bin_width)}p, w={window_w}, bỏ w bin mép phải)",
        fontweight="bold", fontsize=11.5,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    out_png = reports_dir / "fig0_welch_warmup.png"
    plt.savefig(out_png, dpi=200)
    plt.close(fig)
    print(f"[OK] Đã xuất dữ liệu & biểu đồ Welch: {out_csv}, {out_png}")


if __name__ == "__main__":
    run_welch_study(num_replications=60, t_end=5000.0, bin_width=50.0, window_w=5, max_workers=4)
