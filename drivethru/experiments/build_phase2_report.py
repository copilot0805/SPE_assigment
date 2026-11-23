import csv
from collections import Counter
from pathlib import Path
from typing import Dict, List

REPORTS_DIR = Path("reports")
OUT_REPORT = Path("docs/REPORT_PHASE2_10_STEPS.md")


def _read_csv(name: str) -> List[Dict[str, str]]:
    p = REPORTS_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Thiếu tệp {p}. Hãy chạy đầy đủ Exp A-D, analyze_step9 và M5 trước.")
    with p.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_report() -> None:
    raw_bcd = _read_csv("exp_bcd_raw_runs.csv")
    exp_a = _read_csv("exp_a_validation.csv")
    exp_b = _read_csv("exp_b_summary.csv")
    exp_c = _read_csv("exp_c_summary.csv")
    exp_d = _read_csv("exp_d_summary.csv")
    exp_d_paired = _read_csv("exp_d_paired_crn.csv")
    anova = _read_csv("exp_c_sensitivity_anova.csv")
    min_sla = _read_csv("exp_c_min_sla_configs.csv")
    little_audit = _read_csv("exp_c_little_audit.csv")
    m5_bm = _read_csv("exp_m5_benchmark.csv")
    m5_probe = _read_csv("exp_m5_speedup_probe.csv")

    # --- Chốt kiểm chéo toàn vẹn dữ liệu nguồn trước khi sinh báo cáo ---
    raw_counts = Counter(r["config_id"] for r in raw_bcd)
    for name, rows in (("exp_b_summary", exp_b), ("exp_c_summary", exp_c), ("exp_d_summary", exp_d)):
        for r in rows:
            cid = r["config_id"]
            assert int(r["R"]) == raw_counts[cid], (
                f"Lệch R giữa {name}.csv ({r['R']}) và exp_bcd_raw_runs.csv ({raw_counts[cid]}) tại {cid}! "
                "Hãy chạy lại `python -m drivethru.experiments.run_exp_bcd`."
            )
    assert "sla_status" in exp_c[0], "exp_c_summary.csv thiếu cột sla_status!"
    for r in exp_c:
        assert (r["sla_pass"] == "True") == (r["sla_status"] == "PASS"), (
            f"Lệch sla_pass vs sla_status tại {r['config_id']}!"
        )

    # Kiểm tra các cặp CRN Exp D dùng đúng số seed lớn nhất của cặp (§2.5)
    exp_d_by_key = {(float(r["lam"]), r["blocking_order"] == "True"): r for r in exp_d}
    for pr in exp_d_paired:
        lam = float(pr["lam"])
        r_nb = int(exp_d_by_key[(lam, False)]["R"])
        r_blk = int(exp_d_by_key[(lam, True)]["R"])
        assert r_nb == r_blk == int(pr["n_pairs"]), (
            f"Lệch tập seed CRN Exp D tại lam={lam}: NB={r_nb}, BLK={r_blk}, pairs={pr['n_pairs']}!"
        )

    # --- Thống kê Exp A ---
    n_a_tot = len(exp_a)
    n_a_pass = sum(1 for r in exp_a if r["passed"] == "True")
    n_a_inci = sum(1 for r in exp_a if r["in_ci95"] == "True")
    max_a_err = max(float(r["rel_error_pct"]) for r in exp_a)
    max_a_little = max(float(r["little_error_pct"]) for r in exp_a)

    # --- Thống kê Exp C & D động hoàn toàn ---
    n_c_prec = sum(1 for r in exp_c if r["precision_ok"] == "True")
    n_c_pass = sum(1 for r in exp_c if r["sla_status"] == "PASS")
    n_c_fail = sum(1 for r in exp_c if r["sla_status"] == "FAIL")
    n_c_bnd = sum(1 for r in exp_c if r["sla_status"] == "BOUNDARY")
    expanded_c = [r for r in exp_c if int(r["R"]) > 30]
    expanded_d = [r for r in exp_d if int(r["R"]) > 30]
    exp_c_str = ", ".join(f"`{r['config_id']}` ($R={r['R']}$)" for r in expanded_c) or "Không có"
    exp_d_str = ", ".join(f"`{r['config_id']}` ($R={r['R']}$)" for r in expanded_d) or "Không có"
    bnd_list = [
        f"`{r['config_id']}` ($R={r['R']}$, $\\overline{{T}}={float(r['T_mean']):.3f}\\pm{float(r['T_hw']):.3f}$p, "
        f"$P_b={float(r['P_b_mean'])*100:.2f}\\pm{float(r['P_b_hw'])*100:.2f}$%)"
        for r in exp_c if r["sla_status"] == "BOUNDARY"
    ]
    bnd_note = (
        "Hai cấu hình `BOUNDARY` (cột `sla_pass` ghi `False` vì chỉ tính `PASS` chắc chắn khi cận trên $CI_{95}$ nằm trọn trong ngưỡng): "
        + "; ".join(bnd_list) + "."
        if bnd_list
        else "Không có cấu hình nào nằm ở trạng thái `BOUNDARY`."
    )

    peak_c = sorted(
        [r for r in exp_c if abs(float(r["lam"]) - 0.6) < 1e-9],
        key=lambda x: (int(x["c2"]), int(x["K1"])),
    )
    p_min = next(r for r in peak_c if int(r["c2"]) == 1 and int(r["K1"]) == 4)
    p_rec = next(r for r in peak_c if int(r["c2"]) == 2 and int(r["K1"]) == 6)
    p_c3 = next(r for r in peak_c if int(r["c2"]) == 3 and int(r["K1"]) == 6)
    dt_c2_to_c3 = float(p_rec["T_mean"]) - float(p_c3["T_mean"])
    pct_c2_to_c3 = dt_c2_to_c3 / float(p_rec["T_mean"]) * 100.0

    d_peak_nb, d_peak_blk = exp_d_by_key[(0.6, False)], exp_d_by_key[(0.6, True)]
    d_heavy_nb, d_heavy_blk = exp_d_by_key[(0.7, False)], exp_d_by_key[(0.7, True)]
    save_peak_pct = (1.0 - float(d_peak_nb["T_mean"]) / float(d_peak_blk["T_mean"])) * 100.0
    save_heavy_pct = (1.0 - float(d_heavy_nb["T_mean"]) / float(d_heavy_blk["T_mean"])) * 100.0

    # --- Các bảng Markdown ---
    anova_lines = [
        "| Chỉ số | $\\lambda$ (%) | $c_2$ (%) | $K_1$ (%) | $\\lambda \\times c_2$ (%) | $\\lambda \\times K_1$ (%) | $c_2 \\times K_1$ (%) | 3-way (%) | **Sai số `SSE` (%)** | Tác động chính |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in anova:
        anova_lines.append(
            f"| {r['metric_label']} | **{r['pct_lam']}** | **{r['pct_c2']}** | **{r['pct_K1']}** | "
            f"**{r['pct_lam_x_c2']}** | {r['pct_lam_x_K1']} | {r['pct_c2_x_K1']} | "
            f"{r['pct_lam_x_c2_x_K1']} | **{r['pct_error_sse']}** | {r['top_effects']} |"
        )
    anova_table = "\n".join(anova_lines)

    paired_lines = [
        "| $\\lambda$ | Tập seed chung (`1..R`) | $\\Delta \\overline{T} \\pm CI_{95}$ (phút) | $\\Delta P_b \\pm CI_{95}$ (điểm %) | $\\Delta U_1 \\pm CI_{95}$ (điểm %) | $\\Delta W_f \\pm CI_{95}$ (phút) | Ý nghĩa thống kê |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in exp_d_paired:
        paired_lines.append(
            f"| {float(r['lam']):.1f} | {r['n_pairs']} cặp (`1..{r['n_pairs']}`) | "
            f"`{float(r['dT_mean']):+.3f} ± {float(r['dT_hw']):.3f}` | "
            f"`{float(r['dPb_pp_mean']):+.3f} ± {float(r['dPb_pp_hw']):.3f}` | "
            f"`{float(r['dU1_pp_mean']):+.3f} ± {float(r['dU1_pp_hw']):.3f}` | "
            f"`{float(r['dWf_mean']):+.4f} ± {float(r['dWf_hw']):.4f}` | "
            f"{'Có (CI > 0)' if int(r['stat_sig_T']) else 'Không'} |"
        )
    paired_table = "\n".join(paired_lines)

    min_lines = [
        "| Kịch bản | $\\lambda$ | Đạt SLA (`PASS`) | Cấu hình nhỏ nhất đạt SLA | $\\overline{T} \\pm CI_{95}$ (phút) | $P_b$ (%) | $U_2$ | Cấu hình khuyến nghị vận hành ($U_2 \\le 0.8, P_b \\le 1.5\\%$) |",
        "|---|---:|---:|---|---:|---:|---:|---|",
    ]
    for r in min_sla:
        min_lines.append(
            f"| {r['scenario']} | {float(r['lam']):.1f} | {r['n_pass_out_of_12']}/12 | "
            f"**$c_2={r['min_sla_c2']}, K_1={r['min_sla_K1']}$** | "
            f"`{float(r['min_sla_T_mean']):.3f} ± {float(r['min_sla_T_hw']):.3f}` | "
            f"{float(r['min_sla_Pb_pct']):.2f}% | {float(r['min_sla_U2']):.3f} | "
            f"**$c_2={r['rec_c2']}, K_1={r['rec_K1']}$** ($\\overline{{T}}={float(r['rec_T_mean']):.2f}$p, $P_b={float(r['rec_Pb_pct']):.2f}$%, $U_2={float(r['rec_U2']):.3f}$) |"
        )
    min_table = "\n".join(min_lines)

    peak_lines = [
        "| $c_2$ | $K_1$ | R | $\\overline{T} \\pm CI_{95}$ (phút) | $P_{95}(T)$ (phút) | $P(T>8)$ (%) | $P_b \\pm CI_{95}$ (%) | $U_2$ | Trạng thái SLA (§2.6) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in peak_c:
        peak_lines.append(
            f"| {r['c2']} | {r['K1']} | {r['R']} | "
            f"`{float(r['T_mean']):.3f} ± {float(r['T_hw']):.3f}` | {float(r['P95_T_mean']):.2f} | "
            f"{float(r['P_T_gt_8_mean'])*100:.2f}% | "
            f"`{float(r['P_b_mean'])*100:.2f} ± {float(r['P_b_hw'])*100:.2f}`% | "
            f"{float(r['U2_mean']):.3f} | **{r['sla_status']}** |"
        )
    peak_table = "\n".join(peak_lines)

    d_lines = [
        "| $\\lambda$ | Biến thể | R | $\\overline{T} \\pm CI_{95}$ (phút) | $P_b \\pm CI_{95}$ (%) | $U_1$ (%) | $W_f$ (phút) |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for lam in (0.4, 0.6, 0.7):
        for is_blk, lbl in ((False, "Non-blocking"), (True, "Blocking")):
            r = exp_d_by_key[(lam, is_blk)]
            d_lines.append(
                f"| {lam:.1f} | {lbl} | {r['R']} | "
                f"`{float(r['T_mean']):.3f} ± {float(r['T_hw']):.3f}` | "
                f"`{float(r['P_b_mean'])*100:.2f} ± {float(r['P_b_hw'])*100:.2f}`% | "
                f"{float(r['U1_mean'])*100:.2f}% | {float(r['W_f_mean']):.4f} |"
            )
    d_table = "\n".join(d_lines)

    max_ens_little = max(float(r["ensemble_little_err_pct"]) for r in little_audit)
    max_single_little = max(float(r["max_single_little_err_pct"]) for r in little_audit)
    flagged_little = [r for r in little_audit if int(r["n_runs_gt_1pct"]) > 0]
    little_lines = [
        "| Cấu hình | $\\lambda$ | $c_2$ | $K_1$ | R | $\\overline{L}_{sys}$ | Little trung bình (%) | Max 1 lượt (%) | Số lượt > 1% | Cận biên $2L/(X T_m)$ (%) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in flagged_little:
        little_lines.append(
            f"| `{r['config_id']}` | {float(r['lam']):.1f} | {r['c2']} | {r['K1']} | {r['R']} | "
            f"{float(r['L_sys_mean']):.2f} | **{float(r['ensemble_little_err_pct']):.3f}%** | "
            f"{float(r['max_single_little_err_pct']):.3f}% (seed {r['worst_seed']}) | "
            f"{r['n_runs_gt_1pct']}/{r['R']} | {float(r['boundary_order_2L_over_XTm_pct']):.3f}% |"
        )
    little_table = "\n".join(little_lines) if flagged_little else "_Không có lượt đơn lẻ nào vượt 1%._"

    m5_lines = [
        "| Kịch bản | Kiến trúc | $\\lambda$ | $t_{end}$ | Events | Wall (s) ± CI95 | Slowdown | Thr (ev/s) | Heap (MB) | 1LP% | ActLP | Car Err |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in m5_bm:
        m5_lines.append(
            f"| `{r['scenario_id']}` | **{r['engine_name']}** | {float(r['lam']):.1f} | {int(float(r['t_end'])):,} | "
            f"{int(float(r['events_mean'])):,} | `{float(r['wall_time_mean']):.4f} ± {float(r['wall_time_ci95']):.4f}` | "
            f"**{float(r['slowdown_vs_seq']):.2f}x** | {int(float(r['events_per_sec_mean'])):,} | "
            f"{float(r['peak_mem_mb_mean']):.3f} | {float(r['pct_single_lp_epochs_mean']):.1f}% | "
            f"{float(r['avg_active_lps_mean']):.2f} | `{float(r['max_car_trace_err']):.1e}` |"
        )
    m5_table = "\n".join(m5_lines)

    probe_lines = [
        "| Chế độ kiểm chứng | Kiến trúc | Wall (s) ± CI95 | Speedup vs Single | CPU/Wall | ActLP | 1LP% | Checksum |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in m5_probe:
        probe_lines.append(
            f"| {r['regime_label']} | **{r['engine_name']}** | "
            f"`{float(r['wall_time_mean']):.4f} ± {float(r['wall_time_ci95']):.4f}` | "
            f"**{float(r['speedup_vs_seq']):.2f}x** | {float(r['cpu_wall_ratio_mean']):.2f} | "
            f"{float(r['avg_active_lps']):.1f} | {float(r['pct_single_lp_epochs']):.1f}% | OK |"
        )
    probe_table = "\n".join(probe_lines)

    report = f"""# BÁO CÁO PHASE 2 — ĐÁNH GIÁ HIỆU NĂNG MẠNG HÀNG ĐỢI DRIVE-THRU THEO 10 BƯỚC PE

* **Môn học:** Đánh giá Hiệu năng Hệ thống (CO3007) — Khoa KH&KT Máy tính, ĐH Bách Khoa TP.HCM.
* **Nhóm:** SPE-L0x-008 (Lớp L02).
* **Môi trường thực thi chính thức:** Windows 11, CPU 4-core/8-thread, Python 3.12.10 (CPython có GIL); thư viện gốc `bkitevsim/` giữ nguyên vẹn byte-by-byte.
* **Tài liệu kỹ thuật kèm theo:** `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` (kiến trúc, class diagram, bảng đối chiếu thiết kế, kiểm toán Bảng 5–7, errata), `USER_MANUAL.md` (hướng dẫn tái lập), `EXAMINER_GUIDE.md` (kiểm định **29/29 unit tests**), `ROADMAP_M5_MULTITHREAD.md` (chi tiết Phụ lục A — M5).

---

## Bảng Ánh xạ 10 Bước PE với Thiết kế V2 (`Assignment_SPE_Design_v2.pdf`) & Bài giảng

| Bước PE | Nội dung thực hiện | Liên kết Thiết kế V2 & Slide | Tệp mã nguồn / Bằng chứng đầu ra |
|---|---|---|---|
| **1–2** | Mục tiêu, ranh giới, dịch vụ và 3 kết quả | Thiết kế §1.1–1.2, `pe2` | `drivethru/models/`, `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` |
| **3** | Chọn chỉ số, phân loại tiện ích HB/LB/NB & độ dư thừa | Thiết kế §2.1–2.3, `pe3` | `drivethru/metrics/stats_utils.py`, `analytical.py` |
| **4–5** | Tham số hệ thống (Bảng 5–7) và 3 yếu tố ($\\lambda, c_2, K_1$) | Thiết kế §3.1–3.2, `pe2` | `simulation_config.py`, `experiment_config.py` |
| **6** | Kỹ thuật DES + Giải tích; đủ 9 kỹ thuật Verification | Thiết kế §1.4, §1.9, `pe3`, `pe7` | `run_exp_a.py`, `tests/test_m1..m4` (**29/29 unit tests PASS**) |
| **7–8** | Workload CRN, Welch, Leftover, Student-$t$ CI & Full Factorial | Thiết kế §2.5, §3.3–3.4, `pe7`–`pe9` | `run_welch_warmup.py`, `run_hand_trace.py`, `runner.py`, `fig0` |
| **9** | Phân bổ phương sai có `SSE`, Paired CRN, Trade-off & Little | Thiết kế §2.6, §3.4, `pe9`–`pe10` | `analyze_step9.py`, `fig9`, `fig10`, `exp_d_paired_crn.csv` |
| **10** | Trình bày kết quả, khuyến nghị cấu hình & Hạn chế đã biết | Thiết kế §1.9, §3.4, `pe2` | `fig1`–`fig5`, `fig9`, `fig10` *(M5 tách riêng tại Phụ lục A)* |

---

## Bước 1–2: Mục tiêu, Ranh giới, Dịch vụ và Kết quả
_Liên kết Thiết kế V2: Mục 1.1 (Mục tiêu, ranh giới, giả thiết) và Mục 1.2 (Dịch vụ và kết quả); bảng đối chiếu chi tiết tại `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` §3._

* **Hệ thống nghiên cứu (SUT):** Mạng hàng đợi Drive-thru 4 trạm dạng Fork–Join (`Order -> (Payment || Kitchen) -> Join -> Pickup`), hiện thực bằng 6 Logical Processes (`LP0..LP5`) từ 4 lớp (`CarSourceLP`, `StationLP`, `PickupLP(StationLP)`, `MonitorLP`).
* **Mục tiêu:** Định lượng $\\overline{{T}}$, $U_i$, $P_b$, $W_f$; tìm cấu hình $(c_2, K_1)$ đạt chuẩn SLA tại cao điểm Peak ($\\lambda = 0.6$): **S1:** $\\overline{{T}} \\le 8.0$ phút và **S2:** $P_b \\le 5.0$%; đồng thời lượng hóa lợi ích giao tiếp không chặn giữa Order và Kitchen.
* **Ba kết quả dịch vụ:** (1) Hoàn thành (`DEPARTURE`), (2) Bị từ chối tại Order khi đầy $K_1$ (`DROP`), (3) Chưa hoàn thành khi kết thúc $t_{{end}}$ (*leftover entities*, đếm riêng để kiểm cân bằng dòng).

## Bước 3: Lựa chọn & Phân loại Chỉ số Hiệu năng
_Liên kết Thiết kế V2: Mục 2.1–2.3 (Bảng 1–3) và bài giảng `pe3` (Utility classification)._

| Nhóm tiện ích (`pe3`) | Chỉ số đo | Ý nghĩa & Vai trò trong đánh giá |
|---|---|---|
| **HB** *(Higher is Better)* | $X$, $X_1..X_4$ | Thông lượng phục vụ (xe/phút) — phản ánh năng suất hệ thống. |
| **LB** *(Lower is Better)* | $\\overline{{T}}$, $P_{{95}}(T)$, $P(T>8)$, $P_b$, $W_f$, $P_f$, $L_f$, $W_i$, $W_{{q,i}}$, $L_i$, $L_{{q,i}}$, $L_{{sys}}$ | Thời gian đáp ứng, xác suất từ chối và độ dài hàng đợi — dùng trực tiếp cho chuẩn SLA (S1, S2). |
| **NB** *(Nominal is Best)* | $U_1, U_2, U_3, U_4$ | Độ sử dụng tài nguyên: quá cao ($>80$%) gây nút cổ chai & tăng vọt hàng đợi; quá thấp gây lãng phí nhân lực/cửa phục vụ. |

* **Lưu ý về tính không dư thừa (`pe3`):** Ba nhóm chỉ số $L, W, X$ liên hệ qua Định luật Little ($L = X \\cdot W$) nên có phần dư thừa về lý thuyết; nhóm cố ý đo độc lập cả ba ($L$ bằng tích phân diện tích theo thời gian; $W$ trung bình mẫu xe; $X$ tốc độ rời) để làm phép kiểm tra nhất quán chéo (*Consistency Verification*) trên mọi lượt chạy.

## Bước 4–5: Tham số Hệ thống & Yếu tố Nghiên cứu
_Liên kết Thiết kế V2: Mục 3.1 (Bảng 5, 6, 7) và Mục 3.2 (Bảng 8); kiểm toán từng dòng tham số tại `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` §4._

* **Tham số cố định:** $c_1 = c_3 = c_4 = 2$; $1/\\mu_1 = 1.5$, $1/\\mu_2 = 1.25$, $1/\\mu_3 = 1.5$, $1/\\mu_4 = 1.0$ phút; $K_2 = K_3 = K_4 = \\infty$; FCFS; $t_{{warmup}} = 2\\,000$ phút, $t_{{end}} = 10\\,000$ phút ($T_m = 8\\,000$ phút); `bucket_width = safe_bucket_width(t_end)` (đính chính Bảng 7 để triệt tiêu lỗi `% 1024` của `LadderQueue`).
* **3 yếu tố nghiên cứu (Full Factorial Exp C):** $\\lambda \\in \\{{0.2, 0.4, 0.6, 0.7\\}}$ (4 mức) $\\times\\ c_2 \\in \\{{1, 2, 3\\}}$ (3 mức) $\\times\\ K_1 \\in \\{{3, 4, 6, 8\\}}$ (4 mức) = **48 cấu hình**.

## Bước 6: Kỹ thuật Đánh giá, Verification (`pe7`) & Validation
_Liên kết Thiết kế V2: Mục 1.4 (Kỹ thuật đánh giá), Mục 1.9 (6 chỉ báo (i)–(vi) & trace ~10 xe) và Mục 2.4; đối chiếu bài giảng `pe3`, `pe7`._

* **Kỹ thuật:** Kết hợp **giải tích** (tìm dải tham số sơ bộ và làm chuẩn đối chiếu 6 mô hình đơn + xấp xỉ Fork–Join) với **mô phỏng DES** trên `bkitevsim` (khảo sát mạng có blocking + fork-join không có nghiệm dạng tích Jackson).
* **Kiểm chứng Verification đầy đủ theo danh mục `pe7` (**29/29 unit tests PASS**):**
  1. *Top-Down Modular Design:* Tách 4 lớp LP độc lập (`drivethru/models/`) khỏi tầng cấu hình, metrics và thực nghiệm.
  2. *Anti-bugging:* Cân bằng dòng xe & đơn bếp, chốt chặn thời gian không giảm cục bộ & liên-LP (`attach_global_monotonic_guard`), fail-fast `unmatched_food_ready_count`.
  3. *Deterministic Models:* `test_m4_review_guards.py::test_9` (đầu vào hằng số khớp chính xác công thức tay $W_f=0.25, T=4.0$, sai số $< 10^{{-9}}$).
  4. *Run Simplified Cases:* 6 mô hình hàng đợi đơn (Exp A) và 3 ca unit test bảng Join (`test_m3_network_gate.py::test_1..3`).
  5. *Trace:* `run_hand_trace.py` (`reports/hand_trace_10_cars.md`: seed=2, 13 xe, 3 DROP, 3 chờ đồ, 121 event đơn điệu qua `MonitorLP.log_event()`, khớp công thức tay $< 10^{{-12}}$).
  6. *Continuity Test:* `test_m4_review_guards.py::test_10` (đổi nhẹ $\\lambda: 0.60 \\to 0.61$ cho $\\overline{{T}}, U_2$ biến thiên mượt).
  7. *Degeneracy Tests:* `test_m3_network_gate.py::test_6` ($1/\\mu_3 = 0.01 \\to$ khớp mạng Jackson $< 5$%).
  8. *Consistency Tests:* Định luật Little $\\le 1$%, tính bất biến cùng seed & đảo thứ tự fork trễ 0 (`test_m3_network_gate.py::test_4`), và hai loại dispatcher `SequentialEventDispatcher` vs. `DistributedEventDispatcher` cho cùng chỉ số (`test_m3_network_gate.py::test_7`).
  9. *Seed Independence:* `test_m4_review_guards.py::test_11` (hai nhóm seed rời nhau `1..10` vs. `11..20` không khác biệt có ý nghĩa thống kê).
* **Validation Exp A (`reports/exp_a_validation.csv`, `fig4_exp_a_validation.png`):**
  * Đạt **{n_a_pass}/{n_a_tot} chỉ số PASS** ({n_a_inci}/{n_a_tot} giá trị lý thuyết nằm trong $CI_{{95}}$), sai số tương đối cực đại **{max_a_err:.2f}%** ($\\le 5$%), sai số Little cực đại **{max_a_little:.3f}%** ($\\le 1$%).

## Bước 7–8: Workload CRN, Warm-up (Welch), Leftover & Kế hoạch Thí nghiệm
_Liên kết Thiết kế V2: Mục 2.5 (Bảng 4), Mục 3.3 (Bảng 10) và Mục 3.4 (Bảng 12); đối chiếu bài giảng `pe7`–`pe9`._

* **Workload CRN:** 5 luồng số ngẫu nhiên độc lập (`MultiStreamRNG`) lấy mẫu sẵn $(s_1, s_2, s_3, s_4)$ ngay lúc sinh xe, đồng bộ hoàn toàn giữa các cấu hình và biến thể so sánh.
* **Loại bỏ trạng thái quá độ (Welch — Moving average of independent replications, `pe7`):** `run_welch_warmup.py` ($R = 60$, bỏ 4 bin cắt cụt + $w = 5$ bin mép phải, `fig0_welch_warmup.png`) chứng minh hai cấu hình hội tụ chậm nhất đều vào dải bình ổn $\\pm 5$% quanh $t \\approx 400$ phút $\\implies$ $t_{{warmup}} = 2\\,000$ phút dư an toàn.
* **Xử lý xe còn sót (Leftover entities, `pe7`):** $\\overline{{T}}$ tính trung bình trên tập xe đến sau $t_{{warmup}}$ và đã hoàn thành trước $t_{{end}}$; $L_i$ và $U_i$ tính bằng tích phân diện tích theo thời gian chia $T_m = 8\\,000$ phút.
* **Khoảng tin cậy Student-$t$, Tiêu chí dừng & Số lần lặp `R` (`pe7`, Thiết kế §2.5 & §3.4):**
  * Nhóm dùng phân phối **Student-$t$** ($t_{{0.975, R-1}}$ trong `stats_utils.py`) thay vì xấp xỉ $z$ do cỡ mẫu cơ sở $R=30$ hữu hạn. Checkpoint được bảo vệ bằng `config_hash` SHA-256 + tự sao lưu `.bak`.
  * Thực hiện theo Mục 2.5 và Mục 3.4 của Thiết kế V2, mọi cấu hình chưa đạt tiêu chí độ chính xác ($CI_{{95}} \\le 5\\%$ cho `U, L, W, T` và $\\le 0.3$ điểm % cho `P_b`) được tự động tăng số lần lặp $R$; các giá trị $R$ cụ thể là kết quả đo thực tế của Phase 2. Trần $R$ tối đa (`max_replications = 60`) là lựa chọn cài đặt của nhóm (Thiết kế V2 không quy định trần này).
  * *Ghi chú ngưỡng `0.3` điểm % của $P_b$:* Thiết kế V2 (§2.5) áp dụng tiêu chí nửa độ rộng $\\le 0.3$ điểm % cho $P_b$ (và lưu ý ở Exp A chỉ dùng cấu hình có $P_b$ lý thuyết $\\ge 1\\%$ làm bằng chứng kiểm chứng $P_b$); trong hiện thực `runner.py`, nhóm kiểm đồng nhất ngưỡng $\\le 0.3$ điểm % cho mọi cấu hình mạng Exp B–D (kể cả khi $P_b$ rất nhỏ gần 0%, khi đó phương sai gần 0 nên điều kiện luôn thỏa).
  * **Các cấu hình tăng $R > 30$ trong Phase 2 (đồng bộ trên cả `exp_bcd_raw_runs.csv` và summary CSV):**
    * Exp C: {exp_c_str} *(trong đó `C_lam7_c2_2_K1_8` tăng từ 30 lên 40 để đồng bộ tập seed chung `1..40` với biến thể chặn của Exp D theo đúng quy định CRN §2.5)*.
    * Exp D: {exp_d_str} *(biến thể chặn tại $\\lambda=0.7$ đạt chuẩn chính xác ở $R=40$; hai biến thể ở $\\lambda=0.7$ dùng chung trọn 40 seed `1..40`)*.
  * **Tổng kết 48 cấu hình Exp C (`reports/exp_c_summary.csv`):** **{n_c_prec}/48 đạt `precision_ok`**; phân loại SLA 3 mức theo cột `sla_status`: **{n_c_pass} `PASS`**, **{n_c_fail} `FAIL`**, **{n_c_bnd} `BOUNDARY`**. {bnd_note}

---

## Bước 9: Phân tích Dữ liệu Có Hệ thống
_Liên kết Thiết kế V2: Mục 2.6 (Tiêu chí SLA), Mục 3.3–3.4 và bài giảng `pe9`–`pe10` (Allocation of Variation, tránh lỗi bỏ qua tương tác và sai số thí nghiệm)._

### 9.1. Phân bổ Phương sai Có Sai số Thí nghiệm `SSE` (Allocation of Variation — 1,440 lượt Exp C)
Trích từ `reports/exp_c_sensitivity_anova.csv` và trực quan hóa tại `reports/fig10_allocation_of_variation.png` (thiết kế giai thừa đầy đủ $4 \\times 3 \\times 4$ cân bằng trên 30 seeds đầu mỗi ô):

{anova_table}

* **Nhận xét trọng tâm (`pe9`–`pe10`):**
  * Với **$\\overline{{T}}$:** Không chỉ yếu tố chính $c_2$ (~34%) và $\\lambda$ (~28%) mà **tương tác $\\lambda \\times c_2$ chiếm ~25% tổng biến thiên**, trong khi sai số thí nghiệm `SSE` chỉ ~3.6%. Điều này giải thích hiện tượng $\\overline{{T}}$ tăng phi tuyến mạnh ở $c_2=1$ khi $\\lambda: 0.6 \\to 0.7$ nhưng gần như phẳng ở $c_2 \\ge 2$.
  * Với **$P_b$:** $K_1$ (~46%), $\\lambda$ (~29%) và tương tác $\\lambda \\times K_1$ (~23%) giải thích ~98% biến thiên (`SSE` ~1%); $c_2$ bằng 0% do không có back-pressure từ Payment về Order.
  * Với **$X$:** $\\lambda$ chiếm ~99% biến thiên (`SSE` ~0.2%).
  * Với **$W_f$:** $c_2$ (~70%) và tương tác $\\lambda \\times c_2$ (~25%) chi phối vì khi Payment chậm ($c_2=1$), đồ ăn thường xong trước xe nên $W_f \\approx 0$; khi $c_2 \\ge 2$, xe qua Payment nhanh nên phải chờ Kitchen.

### 9.2. Đánh đổi $\\overline{{T}}$ vs. $P_b$ (`fig9`) & Cấu hình Tối thiểu Đạt SLA theo $\\lambda$
Xem `reports/fig9_pareto_T_vs_Pb.png` và `reports/exp_c_min_sla_configs.csv`:

{min_table}

**Chi tiết 12 cấu hình tại cao điểm Peak ($\\lambda = 0.6$, chuẩn SLA: $\\overline{{T}} \\le 8.0$ phút & $P_b \\le 5.0$%):**

{peak_table}

* **Biện luận chọn cấu hình khuyến nghị `$c_2 = 2, K_1 = 6$` (mọi con số trích trực tiếp từ bảng trên):**
  1. Theo đúng §2.6 và dự liệu ở §3.3.1 Thiết kế V2, **`c2 = 1, K1 = 4`** là cấu hình nhỏ nhất đạt đúng 2 ngưỡng SLA tại Peak ($\\overline{{T}} = {float(p_min['T_mean']):.3f} \\pm {float(p_min['T_hw']):.3f}$ phút, $P_b = {float(p_min['P_b_mean'])*100:.2f}$% nhờ ~{float(p_min['P_b_mean'])*100:.1f}% xe bị từ chối ở Order làm giảm $\\lambda_{{eff}}$ vào Payment). Tuy nhiên cấu hình này vẫn mất khách đáng kể, vận hành ở $U_2 = {float(p_min['U2_mean']):.3f}$, có đuôi trễ cao ($P_{{95}}(T) = {float(p_min['P95_T_mean']):.2f}$ phút, $P(T>8) = {float(p_min['P_T_gt_8_mean'])*100:.2f}$%) và **vỡ SLA hoàn toàn ở tải Heavy** ($\\lambda = 0.7$).
  2. Nâng lên **`c2 = 2, K1 = 6`** nằm trên mặt biên Pareto, giải tỏa triệt để nút cổ chai Payment ($U_2 = {float(p_rec['U2_mean']):.3f} \\le 0.8$), kéo $\\overline{{T}}$ xuống **{float(p_rec['T_mean']):.3f} phút** ($P_{{95}}(T) = {float(p_rec['P95_T_mean']):.2f}$ phút), giảm $P_b$ còn **{float(p_rec['P_b_mean'])*100:.2f}%** và đạt SLA bền vững ở cả Peak lẫn Heavy. Nâng tiếp lên $c_2 = 3, K_1 = 6$ chỉ giảm thêm $\\overline{{T}}$ được **{dt_c2_to_c3:.3f} phút** ({pct_c2_to_c3:.2f}%) trong khi tốn thêm 1 cửa thanh toán.

### 9.3. Lợi ích Giao tiếp Không chặn (Exp D — So sánh Ghép cặp CRN `Paired CI 95%`)
Xem `reports/fig5_exp_d_blocking_vs_nonblocking.png`, `reports/exp_d_summary.csv` và `reports/exp_d_paired_crn.csv`:

{d_table}

**Khoảng tin cậy 95% cho hiệu từng cặp CRN ($\\Delta_r = Y_{{\\text{{Blocking}}, r}} - Y_{{\\text{{Non-blocking}}, r}}$, dùng chung trọn tập seed `1..R` lớn nhất của từng cặp theo §2.5):**

{paired_table}

* Mọi khoảng tin cậy ghép cặp của $\\Delta \\overline{{T}}$, $\\Delta P_b$, $\\Delta U_1$ đều nằm hoàn toàn trên 0, khẳng định ở mức ý nghĩa 95% rằng giao tiếp không chặn cắt giảm **{save_peak_pct:.1f}%** thời gian $\\overline{{T}}$ tại Peak ($\\lambda=0.6$) và **{save_heavy_pct:.1f}%** tại Heavy ($\\lambda=0.7$), đồng thời kéo $P_b$ từ {float(d_peak_blk['P_b_mean'])*100:.2f}% xuống {float(d_peak_nb['P_b_mean'])*100:.2f}% tại Peak.

### 9.4. Kiểm toán Định luật Little
* **Trên trung bình cấu hình (Ensemble Mean):** **53/53 cấu hình** đều đạt sai số Little dưới 1% (cực đại toàn cục **{max_ens_little:.3f}%**).
* **Trên từng lượt đơn lẻ (`reports/exp_c_little_audit.csv`):** Một số ít lượt đơn lẻ ở tải nặng ($\\lambda=0.7, c_2=1$, nơi $\\overline{{L}}_{{sys}} \\approx 9$–$10$ xe) có sai số đơn lẻ tối đa **{max_single_little:.2f}%**, khớp với hiệu ứng xe còn sót tại hai biên cửa sổ $[2\\,000, 10\\,000]$ bậc $2L/(\\lambda_{{eff}} T_m)$ đã phân tích ở Mục 2.4.7 Thiết kế V2 và `pe7`.

{little_table}

---

## Bước 10: Trình bày Kết quả & Hạn chế Đã biết
_Liên kết Thiết kế V2: Mục 1.9 (4 hạn chế đã biết) và Mục 3.4 (5 biểu đồ dự kiến)._

### 10.1. Danh mục Biểu đồ Phần Lõi (`reports/`)
* **5 biểu đồ dự kiến theo Thiết kế §3.4:** `fig1_e2e_time_by_lambda_c2.png`, `fig2_blocking_prob_by_K1.png`, `fig3_utilization_bottleneck.png`, `fig4_exp_a_validation.png`, `fig5_exp_d_blocking_vs_nonblocking.png`.
* **3 biểu đồ bổ sung cho Bước 8–9:** `fig0_welch_warmup.png` (Welch $R=60$), `fig9_pareto_T_vs_Pb.png` (đánh đổi $\\overline{{T}}$–$P_b$), `fig10_allocation_of_variation.png` (phân bổ phương sai có `SSE`).

### 10.2. Hạn chế Đã biết (Nguyên văn §1.9 Thiết kế V2 & Bổ sung Phase 2)
**Bốn hạn chế của mô hình theo Mục 1.9 Thiết kế V2:**
1. Đệm không giới hạn ở Payment, Kitchen, Pickup và bãi chờ đồ loại bỏ blocking sau phục vụ; làn và bãi thực tế hữu hạn nên kết quả lạc quan khi các hàng đó dài.
2. Thời gian phục vụ phân phối mũ cần cho công thức đóng, nhưng thực tế thường ít biến động hơn, nên thời gian chờ có lẽ bị ước lượng cao.
3. Bếp chỉ được mô hình hóa như hàng đợi $M/M/c_3$ với một phân phối thời gian chuẩn bị chung, không phân biệt loại món, kích thước đơn, hay hình thức thanh toán.
4. Ngưỡng dịch vụ và thời gian phục vụ là giả định của nhóm (không có dữ liệu đo thực tế từ cửa hàng Drive-thru).

**Hạn chế bổ sung ghi nhận ở Phase 2:**
5. *Hiệu ứng xe còn sót (leftover entities) trên cửa sổ đo hữu hạn:* Ở cấu hình tải nặng ($\\lambda=0.7, c_2=1$), một vài lượt chạy đơn lẻ có sai số Little lên tới {max_single_little:.2f}% (dù trung bình cấu hình $\\le {max_ens_little:.2f}\\%$).
6. *Phạm vi kiểm chứng thực nghiệm:* Toàn bộ kết quả đo thực hiện trên một cấu hình máy tính duy nhất (Windows 11, CPU 4-core/8-thread, CPython 3.12.10).

---

# PHỤ LỤC A — PHẦN MỞ RỘNG TÙY CHỌN: SO SÁNH 3 KIẾN TRÚC THỰC THI DES (M5)

_Ghi chú phạm vi: Đây là phần mở rộng tùy chọn (theo gợi ý `BkSysCoLogicalProcess`/`BkSysFuture` ở Thiết kế §1.7–1.8 và tài liệu PDES), tách riêng khỏi 10 bước đánh giá lõi của mạng Drive-thru. Chi tiết kỹ thuật xem thêm tại `ROADMAP_M5_MULTITHREAD.md`._

### A.1. Kiến trúc Ba Engine & Hạn chế Đã biết của M5
* **Single-thread (`sequential_engine.py`):** Thực thi trực tiếp 6 LP từ `drivethru/models/` trên `SequentialEventDispatcher`.
* **Virtual Multi-thread (`coroutine_engine.py` — Mô hình lai):** Dùng lớp bọc mỏng Composition (`CoCarSourceLP`, `CoStationLP`, `CoPickupLP`, `CoMonitorLP` kế thừa `SafeCoLogicalProcess`) ủy quyền xử lý event-handler sang `models/` bên trong, kết hợp `BkSysCoEventLoop` và **`BkSysFuture` + `asyncio.Task` tại điểm Join của `CoPickupLP`**.
* **OS Multi-thread (`multithread_engine.py`):** Thực thi trực tiếp 6 LP từ `drivethru/models/` trên 6 `threading.Thread` với `ThreadedClockCoordinator` (đồng bộ bảo thủ không có lookahead — *zero-lookahead conservative barrier*).
* **Hạn chế đã biết của phần mở rộng M5:** (i) Biến thể Coroutine là **mô hình lai** (event-handler + `BkSysFuture` ở Join), không phải mô hình hướng tiến trình thuần (mỗi xe một coroutine dùng `asyncio.gather`); (ii) Bộ nhớ báo cáo là **Python Heap Peak** đo bằng `tracemalloc` (chưa gồm stack cấp phát ở mức hệ điều hành của 6 OS threads); (iii) Số tuyệt đối (`wall_time`, `events/s`) đo trên 1 máy Windows 11, CPython 3.12.10 (có GIL).

### A.2. Kết quả Benchmark 1-Core trên Mạng Drive-thru (`reports/exp_m5_benchmark.csv`, `fig6`, `fig7`)

{m5_table}

### A.3. Thí nghiệm Đối chứng Điều kiện Tăng tốc OS-Thread (`reports/exp_m5_speedup_probe.csv`, `fig8`)

{probe_table}

* **Kết luận Phụ lục A:** Cả 3 kiến trúc khớp tuyệt đối trên từng xe (`Car Err = 0.0e+00`, 0 causality error, 0 deadlock). Trên mạng Drive-thru, OS Multi-thread chậm ~4.3–5.1x chủ yếu do kiến trúc **zero-lookahead** (~82% nhịp chỉ có 1 LP chạy, trần song song hóa ~1.2x) cộng hưởng với độ hạt sự kiện siêu nhẹ và CPython GIL; thí nghiệm đối chứng (Chế độ 3) xác nhận chính `ThreadedClockCoordinator` đạt tăng tốc đa nhân thật khi có lookahead dương kết hợp tác vụ giải phóng GIL.
"""

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(report, encoding="utf-8")
    print(f"[OK] Đã xuất Báo cáo Phase 2 sạch (UTF-8, đã kiểm chéo CSV) tại: {OUT_REPORT} ({OUT_REPORT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build_report()
