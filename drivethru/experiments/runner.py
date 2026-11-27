import csv
import hashlib
import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from drivethru.config.experiment_config import NetworkExpConfig
from drivethru.config.simulation_config import DriveThruParams
from drivethru.experiments.run_single import run_drivethru_network
from drivethru.metrics.stats_utils import compute_ci95, evaluate_sla_status

MODEL_CODE_VERSION = "v2.1"  # Tăng hằng số này khi thay đổi logic mô hình để tự vô hiệu hóa checkpoint cũ

RELATIVE_PRECISION_METRICS: Tuple[str, ...] = (
    "T",
    "U1", "U2", "U3", "U4",
    "L1", "L2", "L3", "L4", "L_system",
    "W1", "W2", "W3", "W4",
)

RAW_FIELDNAMES = [
    "config_id", "config_hash", "exp_tags", "scenario_name", "seed", "dispatcher",
    "blocking_order", "lam", "c2", "K1", "mean_s3", "t_warmup", "t_end",
    "T", "P95_T", "P_T_gt_8", "P_b", "X", "W_f", "P_f", "L_f", "L_system",
    "U1", "U2", "U3", "U4",
    "W1", "W2", "W3", "W4",
    "Wq1", "Wq2", "Wq3", "Wq4",
    "L1", "L2", "L3", "L4",
    "X1", "X2", "X3", "X4",
    "total_generated", "total_completed", "total_dropped",
    "n_unfinished_total", "n_unfinished_join",
    "flow_balance_ok",
    "little_err_s1", "little_err_s2", "little_err_s3", "little_err_s4", "little_err_sys",
    "events_processed", "wall_time",
]


def compute_config_fingerprint(params: DriveThruParams, code_version: str = MODEL_CODE_VERSION) -> str:
    """Băm SHA-256 (12 ký tự hex) từ phiên bản mã MODEL_CODE_VERSION và toàn bộ DriveThruParams."""
    payload = json.dumps(
        {"code_version": code_version, "params": asdict(params)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _network_seed_worker(args: Tuple[NetworkExpConfig, int, str]) -> Dict[str, Any]:
    """
    Top-level worker function cho ProcessPoolExecutor trên Windows.
    Bên trong mỗi worker chạy 1 lượt mô phỏng Sequential đơn luồng độc lập.
    """
    cfg, seed, cfg_hash = args
    res = run_drivethru_network(
        params=cfg.params,
        seed=seed,
        dispatcher="sequential",
        verify_invariants=True,
    )
    row = {
        "config_id": cfg.config_id,
        "config_hash": cfg_hash,
        "exp_tags": ";".join(cfg.exp_tags),
        "scenario_name": cfg.scenario_name,
        "mean_s3": cfg.params.mean_s3,
        "t_warmup": cfg.params.t_warmup,
        "t_end": cfg.params.t_end,
    }
    row.update(res)
    return row


def load_checkpoint(
    raw_csv_path: Path,
    expected_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    Đọc các lượt chạy đã lưu từ file checkpoint CSV kèm kiểm chứng dấu vân tay config_hash.
    Nếu file cũ thiếu cột config_hash hoặc sai hash do tham số đã đổi -> cảnh báo, bỏ qua
    dòng cũ và làm sạch file CSV để tuyệt đối không trộn dữ liệu cũ với tham số mới.
    """
    loaded: Dict[str, Dict[int, Dict[str, Any]]] = {}
    if not raw_csv_path.exists():
        return loaded

    float_cols = {
        "lam", "mean_s3", "t_warmup", "t_end",
        "T", "P95_T", "P_T_gt_8", "P_b", "X", "W_f", "P_f", "L_f", "L_system",
        "U1", "U2", "U3", "U4", "W1", "W2", "W3", "W4",
        "Wq1", "Wq2", "Wq3", "Wq4", "L1", "L2", "L3", "L4",
        "X1", "X2", "X3", "X4",
        "little_err_s1", "little_err_s2", "little_err_s3", "little_err_s4", "little_err_sys",
        "wall_time",
    }
    int_cols = {
        "seed", "c2", "K1", "total_generated", "total_completed", "total_dropped",
        "n_unfinished_total", "n_unfinished_join", "events_processed",
    }
    bool_cols = {"blocking_order", "flow_balance_ok"}

    valid_rows: List[Dict[str, Any]] = []
    stale_count = 0
    missing_hash_col = False

    with raw_csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if "config_hash" not in fieldnames:
            missing_hash_col = True
            stale_count = sum(1 for _ in reader)
        else:
            for r in reader:
                cid = r["config_id"]
                row_hash = r.get("config_hash", "")
                if expected_hashes is not None and cid in expected_hashes:
                    if row_hash != expected_hashes[cid]:
                        stale_count += 1
                        continue
                parsed: Dict[str, Any] = {}
                for k, v in r.items():
                    if k in float_cols:
                        parsed[k] = float(v)
                    elif k in int_cols:
                        parsed[k] = int(float(v))
                    elif k in bool_cols:
                        parsed[k] = str(v).strip().lower() in ("true", "1", "yes")
                    else:
                        parsed[k] = v
                loaded.setdefault(cid, {})[parsed["seed"]] = parsed
                valid_rows.append(parsed)

    if missing_hash_col or stale_count > 0:
        reason = (
            "file checkpoint cũ chưa có cột config_hash"
            if missing_hash_col
            else f"{stale_count} dòng cũ có config_hash lệch tham số hiện tại"
        )
        bak_path = raw_csv_path.with_name(raw_csv_path.name + ".bak")
        shutil.copy2(raw_csv_path, bak_path)
        print(f"[WARN][Checkpoint] Bỏ qua dữ liệu cũ ({reason}). Đã sao lưu bản cũ tại: {bak_path} -> tự động chạy lại!")
        with raw_csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RAW_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            if valid_rows:
                writer.writerows(valid_rows)

    return loaded


def append_checkpoint_rows(raw_csv_path: Path, rows: List[Dict[str, Any]]) -> None:
    """Ghi nối tiếp các lượt chạy mới hoàn thành vào file checkpoint CSV."""
    if not rows:
        return
    raw_csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = raw_csv_path.exists() and raw_csv_path.stat().st_size > 0
    with raw_csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def check_precision_details(
    rep_rows: List[Dict[str, Any]],
    rel_tol_pct: float = 5.0,
    pb_abs_tol: float = 0.003,
) -> Dict[str, Any]:
    """
    Kiểm tra đầy đủ tiêu chí độ chính xác theo Bảng 4 Mục 2.5 Thiết kế V2:
    - T, U1..U4, L1..L4, L_system, W1..W4: nửa độ rộng CI 95% <= 5% giá trị trung bình (bỏ qua nếu mean ~ 0).
    - P_b: nửa độ rộng CI 95% <= 0.003 (0.3 điểm phần trăm).
    - Đồng thời đánh giá trạng thái SLA 3 mức (PASS / FAIL / BOUNDARY) theo Mục 2.6.
    """
    failed_metrics: List[str] = []
    worst_rel_metric = "T"
    worst_rel_hw_pct = 0.0
    t_rel_hw_pct = 0.0

    for m in RELATIVE_PRECISION_METRICS:
        if m not in rep_rows[0]:
            continue
        ci = compute_ci95([float(r[m]) for r in rep_rows])
        rel_pct = 0.0 if abs(ci["mean"]) <= 1e-12 else ci["rel_half_width_pct"]
        if m == "T":
            t_rel_hw_pct = rel_pct
        if rel_pct > worst_rel_hw_pct:
            worst_rel_hw_pct = rel_pct
            worst_rel_metric = m
        if rel_pct > rel_tol_pct:
            failed_metrics.append(f"{m}({rel_pct:.2f}%)")

    ci_t = compute_ci95([float(r["T"]) for r in rep_rows])
    ci_pb = compute_ci95([float(r["P_b"]) for r in rep_rows])
    pb_hw_abs = ci_pb["half_width"]
    if pb_hw_abs > pb_abs_tol:
        failed_metrics.append(f"P_b({pb_hw_abs*100:.3f}pp)")

    sla_status = evaluate_sla_status(ci_t, ci_pb, t_limit=8.0, pb_limit=0.05)

    return {
        "precision_ok": len(failed_metrics) == 0,
        "t_rel_hw_pct": t_rel_hw_pct,
        "pb_hw_abs": pb_hw_abs,
        "worst_rel_metric": worst_rel_metric,
        "worst_rel_hw_pct": worst_rel_hw_pct,
        "failed_metrics": failed_metrics,
        "sla_status": sla_status,
    }


def check_precision_criteria(rep_rows: List[Dict[str, Any]]) -> Tuple[bool, float, float]:
    """Giữ chữ ký tương thích ngược (ok, t_rel_hw_pct, pb_hw_abs), bên trong kiểm đủ U, L, W, T và P_b."""
    det = check_precision_details(rep_rows)
    return det["precision_ok"], det["t_rel_hw_pct"], det["pb_hw_abs"]


def run_batch_with_checkpoint(
    configs: List[NetworkExpConfig],
    raw_csv_path: Path,
    max_workers: int = 4,
    auto_expand_ci: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Thực thi danh sách cấu hình trên max_workers nhân CPU, tự động lưu checkpoint có config_hash
    và mở rộng số seed nếu chưa đạt CI 95% (U, L, W, T, P_b) hoặc cấu hình Peak đang ở BOUNDARY.
    """
    expected_hashes = {cfg.config_id: compute_config_fingerprint(cfg.params) for cfg in configs}
    checkpoint = load_checkpoint(raw_csv_path, expected_hashes=expected_hashes)
    total_cfgs = len(configs)
    t_all = time.perf_counter()

    already_done_runs = sum(len(v) for v in checkpoint.values())
    print(f"[Runner] Tổng cấu hình: {total_cfgs} | Checkpoint hợp lệ: {already_done_runs} lượt | Workers: {max_workers}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for idx, cfg in enumerate(configs, start=1):
            cfg_hash = expected_hashes[cfg.config_id]
            done_map = checkpoint.setdefault(cfg.config_id, {})
            t_cfg = time.perf_counter()

            target_r = cfg.base_replications
            while True:
                missing_seeds = [s for s in range(1, target_r + 1) if s not in done_map]
                if missing_seeds:
                    futures = [executor.submit(_network_seed_worker, (cfg, s, cfg_hash)) for s in missing_seeds]
                    newly_done: List[Dict[str, Any]] = []
                    finished = len(done_map)
                    for fut in as_completed(futures):
                        row = fut.result()
                        done_map[row["seed"]] = row
                        newly_done.append(row)
                        finished += 1
                        print(
                            f"  -> [{idx:02d}/{total_cfgs:02d}] {cfg.config_id:<22} "
                            f"(lam={cfg.params.lam:.1f}, c2={cfg.params.c2}, K1={cfg.params.K1}, blk={int(cfg.params.blocking_order)}): "
                            f"{finished:02d}/{target_r} seeds...",
                            end="\r",
                            flush=True,
                        )
                    newly_done.sort(key=lambda r: r["seed"])
                    append_checkpoint_rows(raw_csv_path, newly_done)

                rep_list = [done_map[s] for s in sorted(done_map.keys())]
                det = check_precision_details(rep_list)
                is_peak_boundary = (
                    abs(cfg.params.lam - 0.6) < 1e-9
                    and "ExpC" in cfg.exp_tags
                    and det["sla_status"] == "BOUNDARY"
                )
                need_more = auto_expand_ci and (not det["precision_ok"] or is_peak_boundary)

                if (not need_more) or (target_r >= cfg.max_replications):
                    break
                target_r = min(cfg.max_replications, target_r + 10)

            rep_list = [done_map[s] for s in sorted(done_map.keys())]
            det = check_precision_details(rep_list)
            ci_t = compute_ci95([r["T"] for r in rep_list])
            ci_pb = compute_ci95([r["P_b"] for r in rep_list])
            max_little = max(r["little_err_sys"] for r in rep_list) * 100.0
            dt = time.perf_counter() - t_cfg

            print(" " * 118, end="\r")
            print(
                f"  [OK {idx:02d}/{total_cfgs:02d}] {cfg.config_id:<22} | R={len(rep_list):02d} | "
                f"T={ci_t['mean']:6.3f}+/-{ci_t['half_width']:.3f} | "
                f"maxHW={det['worst_rel_hw_pct']:4.2f}%({det['worst_rel_metric']}) | "
                f"Pb={ci_pb['mean']*100:5.2f}+/-{ci_pb['half_width']*100:.2f}% | "
                f"SLA={det['sla_status']:<8} | Little<={max_little:.2f}% | {dt:5.1f}s",
                flush=True,
            )

    total_dt = time.perf_counter() - t_all
    total_runs = sum(len(v) for v in checkpoint.values())
    print(f"[Runner] Hoàn tất toàn bộ {total_cfgs} cấu hình ({total_runs} lượt chạy) trong {total_dt:.1f}s.\n")

    return {
        cfg.config_id: [checkpoint[cfg.config_id][s] for s in sorted(checkpoint[cfg.config_id].keys())]
        for cfg in configs
    }
