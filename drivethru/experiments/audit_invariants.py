"""Hậu kiểm trên dữ liệu thô: chỉ đọc CSV trong reports/, không chạy lại mô phỏng.

Chạy từ thư mục gốc của repo, sau khi đã chạy Exp B, C, D (bước 6 trong sổ tay sử dụng):
    python -m drivethru.experiments.audit_invariants

Đầu vào : reports/exp_bcd_raw_runs.csv (từng lượt chạy), reports/exp_c_summary.csv (đối chiếu trạng thái SLA)
Đầu ra  : reports/audit_invariants.csv     (mỗi dòng một kết quả kiểm: nhóm, phạm vi, chỉ số, giá trị, ghi chú)
          reports/audit_seeds30_exp_c.csv  (từng cấu hình Exp C: kết quả trên toàn bộ R seed và trên 30 seed chung)

Bốn nhóm kiểm tra:
  1. flow       : cân bằng dòng xe của từng lượt, tính lại từ các cột tổng
                  (total_generated = total_completed + total_dropped + n_unfinished_total).
  2. lambda_eff : cân bằng thông lượng; độ lệch tương đối lớn nhất của X2, X3, X4 và X (hệ thống) so với X1.
  3. little     : định luật Little L = X * W cho từng trạm (Order, Payment, Kitchen, Pickup) và toàn hệ thống,
                  ở hai mức: trung bình theo cấu hình (L, X, W lấy trung bình trên các seed rồi mới so)
                  và từng lượt đơn lẻ.
  4. seeds30    : tính lại trạng thái SLA của các cấu hình Exp C chỉ trên 30 seed chung (1..30),
                  so với kết quả dùng toàn bộ R seed của từng cấu hình.

Thời gian chạy vài giây. Mã thoát 1 nếu một khẳng định của báo cáo bị vi phạm (cân bằng dòng, lệch thông lượng
trên 1%, Little theo trung bình cấu hình trên 1%, hoặc trạng thái SLA đổi khi chỉ dùng 30 seed chung).
Little theo từng lượt đơn lẻ có thể vượt 1% ở tải nặng (đã nêu trong báo cáo), nên chỉ được đếm chứ không làm lỗi.
"""
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from drivethru.metrics.stats_utils import check_littles_law, compute_ci95, evaluate_sla_status

REPORTS_DIR = Path("reports")
RAW_BCD_CSV = REPORTS_DIR / "exp_bcd_raw_runs.csv"
EXP_C_CSV = REPORTS_DIR / "exp_c_summary.csv"
OUT_AUDIT_CSV = REPORTS_DIR / "audit_invariants.csv"
OUT_SEEDS30_CSV = REPORTS_DIR / "audit_seeds30_exp_c.csv"

TOL_PCT = 1.0          # ngưỡng 1% của thiết kế (Little, cân bằng thông lượng)
COMMON_SEEDS = 30      # seed 1..30 có mặt trong mọi cấu hình Exp C
STATIONS = ((1, "Order"), (2, "Payment"), (3, "Kitchen"), (4, "Pickup"))
U2_ROBUST_MAX = 0.80   # luật chọn cấu hình khuyến nghị: giống build_min_sla_table() trong analyze_step9.py
PB_ROBUST_MAX = 0.015


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy {path}. Hãy chạy Exp B/C/D trước.")
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _little_err_pct(l_val: float, x_val: float, w_val: float) -> float:
    return check_littles_law(l_val, x_val, w_val, tol=TOL_PCT / 100.0)["rel_error"] * 100.0


def _add(rows: List[Dict[str, Any]], check: str, scope: str, metric: str, value: Any, note: str = "") -> None:
    if isinstance(value, float):
        value = round(value, 4)
    rows.append({"check": check, "scope": scope, "metric": metric, "value": value, "note": note})


def check_flow_balance(raw: List[Dict[str, str]], rows: List[Dict[str, Any]]) -> bool:
    n_identity = sum(
        1 for r in raw
        if int(r["total_generated"]) == int(r["total_completed"]) + int(r["total_dropped"]) + int(r["n_unfinished_total"])
    )
    n_flag = sum(1 for r in raw if r["flow_balance_ok"] == "True")
    _add(rows, "flow", "all_runs", "n_runs", len(raw))
    _add(rows, "flow", "all_runs", "n_identity_ok", n_identity,
         "total_generated = total_completed + total_dropped + n_unfinished_total (recomputed from the total columns)")
    _add(rows, "flow", "all_runs", "n_flag_ok", n_flag,
         "flow_balance_ok column of the raw CSV (also covers the kitchen order identity)")
    return n_identity == len(raw) and n_flag == len(raw)


def check_lambda_eff(raw: List[Dict[str, str]], rows: List[Dict[str, Any]]) -> bool:
    worst: Dict[str, Tuple[float, str]] = {}
    n_over = 0
    for r in raw:
        x1 = max(float(r["X1"]), 1e-12)
        diffs = {
            "X2": abs(float(r["X2"]) - x1) / x1 * 100.0,
            "X3": abs(float(r["X3"]) - x1) / x1 * 100.0,
            "X4": abs(float(r["X4"]) - x1) / x1 * 100.0,
            "X": abs(float(r["X"]) - x1) / x1 * 100.0,
        }
        if max(diffs.values()) > TOL_PCT:
            n_over += 1
        for name, d in diffs.items():
            if name not in worst or d > worst[name][0]:
                worst[name] = (d, f"{r['config_id']} seed {r['seed']}")
    for name in ("X2", "X3", "X4", "X"):
        _add(rows, "lambda_eff", "all_runs", f"max_rel_diff_{name}_vs_X1_pct", worst[name][0], worst[name][1])
    overall = max(worst.values(), key=lambda t: t[0])
    _add(rows, "lambda_eff", "all_runs", "max_rel_diff_pct", overall[0], overall[1])
    _add(rows, "lambda_eff", "all_runs", "n_runs_over_1pct", n_over)
    return n_over == 0


def check_little(raw: List[Dict[str, str]], rows: List[Dict[str, Any]]) -> bool:
    # (a) Trung bình theo cấu hình: L, X, W lấy trung bình trên các seed của cấu hình rồi mới so
    by_cfg: Dict[str, List[Dict[str, str]]] = {}
    for r in raw:
        by_cfg.setdefault(r["config_id"], []).append(r)
    series = [(f"s{i}", f"L{i}", f"X{i}", f"W{i}") for i, _ in STATIONS] + [("sys", "L_system", "X", "T")]
    names = {f"s{i}": nm for i, nm in STATIONS}
    names["sys"] = "system"
    n_cfg_over = 0
    for key, lc, xc, wc in series:
        errs = [
            (_little_err_pct(_mean([float(r[lc]) for r in reps]), _mean([float(r[xc]) for r in reps]),
                             _mean([float(r[wc]) for r in reps])), cid)
            for cid, reps in by_cfg.items()
        ]
        worst_err, worst_cid = max(errs)
        n_cfg_over += sum(1 for e, _ in errs if e > TOL_PCT)
        _add(rows, "little", "config_mean", f"max_err_{key}_pct", worst_err, f"{names[key]}; {worst_cid}")
    _add(rows, "little", "config_mean", "n_config_station_over_1pct", n_cfg_over,
         f"(config, station or system) pairs over 1% among {len(by_cfg)} configs")

    # (b) Từng lượt đơn lẻ: tính lại từ L, X, W của từng dòng rồi đối chiếu với cột little_err_* đã lưu
    max_diff_stored = 0.0
    n_any_over = 0
    for key, lc, xc, wc in series:
        n_over = 0
        worst_err, worst_where = -1.0, ""
        for r in raw:
            e = _little_err_pct(float(r[lc]), float(r[xc]), float(r[wc]))
            max_diff_stored = max(max_diff_stored, abs(e - float(r[f"little_err_{key}"]) * 100.0))
            if e > TOL_PCT:
                n_over += 1
            if e > worst_err:
                worst_err, worst_where = e, f"{r['config_id']} seed {r['seed']}"
        _add(rows, "little", "single_run", f"max_err_{key}_pct", worst_err, f"{names[key]}; {worst_where}")
        _add(rows, "little", "single_run", f"n_runs_over_1pct_{key}", n_over, names[key])
    for r in raw:
        if any(
            _little_err_pct(float(r[lc]), float(r[xc]), float(r[wc])) > TOL_PCT for _, lc, xc, wc in series
        ):
            n_any_over += 1
    _add(rows, "little", "single_run", "n_runs_any_over_1pct", n_any_over,
         "runs where at least one station or the system exceeds 1%")
    _add(rows, "little", "single_run", "share_runs_all_within_1pct_pct", (len(raw) - n_any_over) / len(raw) * 100.0)
    _add(rows, "little", "single_run", "max_abs_diff_vs_csv_columns_pct", max_diff_stored,
         "recomputed value minus the stored little_err_* column (expected 0)")
    return n_cfg_over == 0


def _stats_of(reps: List[Dict[str, str]]) -> Dict[str, Any]:
    ci_t = compute_ci95([float(r["T"]) for r in reps])
    ci_pb = compute_ci95([float(r["P_b"]) for r in reps])
    return {
        "R": len(reps), "T": ci_t["mean"], "T_hw": ci_t["half_width"],
        "Pb": ci_pb["mean"], "Pb_hw": ci_pb["half_width"],
        "U2": _mean([float(r["U2"]) for r in reps]),
        "sla": evaluate_sla_status(ci_t, ci_pb),
    }


def _pick_configs(stats_by_cfg: Dict[str, Dict[str, Any]], lam: float) -> Tuple[str, str]:
    """Cấu hình nhỏ nhất đạt SLA và cấu hình khuyến nghị của một mức tải (cùng luật với analyze_step9.py)."""
    passed = [(s["c2"], s["K1"], s) for s in stats_by_cfg.values() if s["lam"] == lam and s["sla"] == "PASS"]
    passed.sort(key=lambda t: (t[0], t[1]))
    if not passed:
        return "none", "none"
    robust = [t for t in passed if t[2]["U2"] <= U2_ROBUST_MAX and t[2]["Pb"] <= PB_ROBUST_MAX]
    rec = robust[0] if robust else passed[-1]
    return f"c2={passed[0][0]},K1={passed[0][1]}", f"c2={rec[0]},K1={rec[1]}"


def check_common_seeds(raw: List[Dict[str, str]], exp_c: List[Dict[str, str]], rows: List[Dict[str, Any]]) -> bool:
    by_cfg: Dict[str, List[Dict[str, str]]] = {}
    for r in raw:
        if r["config_id"].startswith("C_"):
            by_cfg.setdefault(r["config_id"], []).append(r)
    summary_status = {r["config_id"]: r["sla_status"] for r in exp_c}

    stats_all: Dict[str, Dict[str, Any]] = {}
    stats_30: Dict[str, Dict[str, Any]] = {}
    for cid, reps in by_cfg.items():
        reps = sorted(reps, key=lambda r: int(r["seed"]))
        if [int(r["seed"]) for r in reps[:COMMON_SEEDS]] != list(range(1, COMMON_SEEDS + 1)):
            raise ValueError(f"Cấu hình {cid} không có đủ seed 1..{COMMON_SEEDS} liên tục")
        meta = {"lam": float(reps[0]["lam"]), "c2": int(reps[0]["c2"]), "K1": int(reps[0]["K1"])}
        stats_all[cid] = {**meta, **_stats_of(reps)}
        stats_30[cid] = {**meta, **_stats_of(reps[:COMMON_SEEDS])}

    detail: List[Dict[str, Any]] = []
    for cid in sorted(by_cfg, key=lambda c: (stats_all[c]["lam"], stats_all[c]["c2"], stats_all[c]["K1"])):
        a, b = stats_all[cid], stats_30[cid]
        detail.append({
            "config_id": cid, "lam": a["lam"], "c2": a["c2"], "K1": a["K1"], "R": a["R"],
            "T_all": round(a["T"], 4), "T_hw_all": round(a["T_hw"], 4),
            "Pb_all_pct": round(a["Pb"] * 100.0, 4), "Pb_hw_all_pct": round(a["Pb_hw"] * 100.0, 4), "sla_all": a["sla"],
            "T_30": round(b["T"], 4), "T_hw_30": round(b["T_hw"], 4),
            "Pb_30_pct": round(b["Pb"] * 100.0, 4), "Pb_hw_30_pct": round(b["Pb_hw"] * 100.0, 4), "sla_30": b["sla"],
            "same_status": a["sla"] == b["sla"],
        })
    with OUT_SEEDS30_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        writer.writeheader()
        writer.writerows(detail)

    n = len(detail)
    n_same = sum(1 for d in detail if d["same_status"])
    n_match_summary = sum(1 for cid in by_cfg if summary_status.get(cid) == stats_all[cid]["sla"])
    worst_dt = max(detail, key=lambda d: abs(d["T_all"] - d["T_30"]))
    worst_dpb = max(detail, key=lambda d: abs(d["Pb_all_pct"] - d["Pb_30_pct"]))
    _add(rows, "seeds30", "exp_c", "n_configs", n)
    _add(rows, "seeds30", "exp_c", "n_configs_R_gt_30", sum(1 for d in detail if d["R"] > COMMON_SEEDS),
         "configs with R > 30 (R is chosen independently per config)")
    _add(rows, "seeds30", "exp_c", "n_status_match_exp_c_summary", n_match_summary,
         "SLA status recomputed from the raw runs (all R seeds) vs the sla_status column of exp_c_summary.csv")
    _add(rows, "seeds30", "exp_c", "n_same_status_all_vs_30", n_same,
         "same SLA status with all R seeds and with the first 30 seeds only")
    for tag, stats in (("all", stats_all), ("30", stats_30)):
        for st in ("PASS", "FAIL", "BOUNDARY"):
            _add(rows, "seeds30", "exp_c", f"n_{st}_{tag}", sum(1 for s in stats.values() if s["sla"] == st),
                 "all R seeds" if tag == "all" else "common seeds 1..30")
    _add(rows, "seeds30", "exp_c", "max_abs_diff_T_min", abs(worst_dt["T_all"] - worst_dt["T_30"]),
         f"{worst_dt['config_id']}: T_all={worst_dt['T_all']}, T_30={worst_dt['T_30']}")
    _add(rows, "seeds30", "exp_c", "max_abs_diff_Pb_pct", abs(worst_dpb["Pb_all_pct"] - worst_dpb["Pb_30_pct"]),
         f"{worst_dpb['config_id']}: Pb_all={worst_dpb['Pb_all_pct']}%, Pb_30={worst_dpb['Pb_30_pct']}%")

    same_pick = True
    for lam in sorted({s["lam"] for s in stats_all.values()}):
        min_a, rec_a = _pick_configs(stats_all, lam)
        min_b, rec_b = _pick_configs(stats_30, lam)
        same_pick = same_pick and (min_a == min_b) and (rec_a == rec_b)
        _add(rows, "seeds30", f"lam={lam}", "min_sla_config_all_vs_30", f"{min_a} | {min_b}",
             "smallest config meeting the SLA: all R seeds | common 30 seeds")
        _add(rows, "seeds30", f"lam={lam}", "recommended_config_all_vs_30", f"{rec_a} | {rec_b}",
             "recommended config: all R seeds | common 30 seeds")
    _add(rows, "seeds30", "exp_c", "same_min_and_recommended_configs", int(same_pick),
         "1 if every load level picks the same configs")
    return n_same == n and n_match_summary == n and same_pick


def main() -> int:
    raw = _read_csv(RAW_BCD_CSV)
    exp_c = _read_csv(EXP_C_CSV)
    rows: List[Dict[str, Any]] = []
    ok_flow = check_flow_balance(raw, rows)
    ok_lambda = check_lambda_eff(raw, rows)
    ok_little = check_little(raw, rows)
    ok_seeds = check_common_seeds(raw, exp_c, rows)

    with OUT_AUDIT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["check", "scope", "metric", "value", "note"])
        writer.writeheader()
        writer.writerows(rows)

    val = {(r["check"], r["scope"], r["metric"]): r["value"] for r in rows}
    print("=" * 100)
    print(f"HẬU KIỂM TRÊN DỮ LIỆU THÔ: {len(raw)} lượt chạy, {len({r['config_id'] for r in raw})} cấu hình (Exp B, C, D)")
    print("=" * 100)
    print(f"[{'OK' if ok_flow else 'CẢNH BÁO'}] Cân bằng dòng: {val[('flow', 'all_runs', 'n_identity_ok')]}/{len(raw)} lượt thỏa "
          f"generated = completed + dropped + unfinished")
    print(f"[{'OK' if ok_lambda else 'CẢNH BÁO'}] Thông lượng X2, X3, X4, X so với X1: lệch lớn nhất "
          f"{val[('lambda_eff', 'all_runs', 'max_rel_diff_pct')]}% (ngưỡng 1%), "
          f"{val[('lambda_eff', 'all_runs', 'n_runs_over_1pct')]} lượt vượt")
    cfg = {k: val[("little", "config_mean", f"max_err_{k}_pct")] for k in ("s1", "s2", "s3", "s4", "sys")}
    print(f"[{'OK' if ok_little else 'CẢNH BÁO'}] Little theo trung bình cấu hình, lớn nhất (%): toàn hệ thống {cfg['sys']}; "
          f"Order {cfg['s1']}, Payment {cfg['s2']}, Kitchen {cfg['s3']}, Pickup {cfg['s4']} (ngưỡng 1%)")
    single = {k: val[("little", "single_run", f"max_err_{k}_pct")] for k in ("s1", "s2", "s3", "s4", "sys")}
    print(f"[--] Little theo từng lượt đơn lẻ: {val[('little', 'single_run', 'n_runs_any_over_1pct')]}/{len(raw)} lượt vượt 1%; "
          f"lớn nhất (%): toàn hệ thống {single['sys']}; Order {single['s1']}, Payment {single['s2']}, "
          f"Kitchen {single['s3']}, Pickup {single['s4']}")
    n = val[("seeds30", "exp_c", "n_configs")]
    print(f"[{'OK' if ok_seeds else 'CẢNH BÁO'}] Exp C trên 30 seed chung: {val[('seeds30', 'exp_c', 'n_same_status_all_vs_30')]}/{n} cấu hình "
          f"cùng trạng thái SLA (PASS {val[('seeds30', 'exp_c', 'n_PASS_30')]}, FAIL {val[('seeds30', 'exp_c', 'n_FAIL_30')]}, "
          f"BOUNDARY {val[('seeds30', 'exp_c', 'n_BOUNDARY_30')]}); "
          f"cấu hình nhỏ nhất và khuyến nghị {'giống nhau' if val[('seeds30', 'exp_c', 'same_min_and_recommended_configs')] else 'KHÁC nhau'} "
          f"ở mọi mức tải")
    print(f"[OK] Đã xuất: {OUT_AUDIT_CSV} và {OUT_SEEDS30_CSV}\n")
    return 0 if (ok_flow and ok_lambda and ok_little and ok_seeds) else 1


if __name__ == "__main__":
    sys.exit(main())
