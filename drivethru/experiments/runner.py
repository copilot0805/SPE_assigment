import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from drivethru.config.experiment_config import NetworkExpConfig
from drivethru.experiments.run_single import run_drivethru_network
from drivethru.metrics.statistics import compute_ci95

RAW_FIELDNAMES = [
    "config_id", "exp_tags", "scenario_name", "seed", "dispatcher",
    "blocking_order", "lam", "c2", "K1", "mean_s3",
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


def _network_seed_worker(args: Tuple[NetworkExpConfig, int]) -> Dict[str, Any]:
    """
    Top-level worker function cho ProcessPoolExecutor trên Windows.
    Bên trong mỗi worker chạy 1 lượt mô phỏng Sequential đơn luồng độc lập.
    """
    cfg, seed = args
    res = run_drivethru_network(
        params=cfg.params,
        seed=seed,
        dispatcher="sequential",
        verify_invariants=True,
    )
    row = {
        "config_id": cfg.config_id,
        "exp_tags": ";".join(cfg.exp_tags),
        "scenario_name": cfg.scenario_name,
        "mean_s3": cfg.params.mean_s3,
    }
    row.update(res)
    return row


def load_checkpoint(raw_csv_path: Path) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Đọc các lượt chạy đã lưu từ file checkpoint CSV để hỗ trợ Resume."""
    loaded: Dict[str, Dict[int, Dict[str, Any]]] = {}
    if not raw_csv_path.exists():
        return loaded

    float_cols = {
        "lam", "mean_s3", "T", "P95_T", "P_T_gt_8", "P_b", "X", "W_f", "P_f", "L_f", "L_system",
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

    with raw_csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            parsed: Dict[str, Any] = {}
            for k, v in r.items():
                if k in float_cols:
                    parsed[k] = float(v)
                elif k in int_cols:
                    parsed[k] = int(v)
                elif k in bool_cols:
                    parsed[k] = (str(v).strip().lower() == "true")
                else:
                    parsed[k] = v
            cid = parsed["config_id"]
            sid = parsed["seed"]
            loaded.setdefault(cid, {})[sid] = parsed
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


def check_precision_criteria(rep_rows: List[Dict[str, Any]]) -> Tuple[bool, float, float]:
    """
    Kiểm tra tiêu chí độ chính xác Mục 2.5 Design V2:
    - Nửa độ rộng CI95% của T <= 5% giá trị trung bình
    - Nửa độ rộng CI95% của P_b <= 0.003 (0.3 điểm phần trăm)
    """
    ci_t = compute_ci95([r["T"] for r in rep_rows])
    ci_pb = compute_ci95([r["P_b"] for r in rep_rows])
    t_rel_hw_pct = ci_t["rel_half_width_pct"]
    pb_hw_abs = ci_pb["half_width"]
    ok = (t_rel_hw_pct <= 5.0) and (pb_hw_abs <= 0.003)
    return ok, t_rel_hw_pct, pb_hw_abs


def run_batch_with_checkpoint(
    configs: List[NetworkExpConfig],
    raw_csv_path: Path,
    max_workers: int = 4,
    auto_expand_ci: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Thực thi danh sách cấu hình trên max_workers nhân CPU, tự động lưu checkpoint
    sau mỗi cấu hình và mở rộng số seed nếu cấu hình phương sai lớn chưa đạt CI95% <= 5%.
    """
    checkpoint = load_checkpoint(raw_csv_path)
    total_cfgs = len(configs)
    t_all = time.perf_counter()

    already_done_runs = sum(len(v) for v in checkpoint.values())
    print(f"[Runner] Tổng cấu hình: {total_cfgs} | Checkpoint đã có: {already_done_runs} lượt | Workers: {max_workers}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for idx, cfg in enumerate(configs, start=1):
            done_map = checkpoint.setdefault(cfg.config_id, {})
            t_cfg = time.perf_counter()

            # Chạy đủ base_replications (mặc định 30 seeds)
            target_r = cfg.base_replications
            while True:
                missing_seeds = [s for s in range(1, target_r + 1) if s not in done_map]
                if missing_seeds:
                    futures = [executor.submit(_network_seed_worker, (cfg, s)) for s in missing_seeds]
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
                prec_ok, t_hw_pct, pb_hw_abs = check_precision_criteria(rep_list)

                if prec_ok or (not auto_expand_ci) or (target_r >= cfg.max_replications):
                    break
                # Tự động tăng thêm 10 seeds cho cấu hình có phương sai cao (tối đa max_replications)
                target_r = min(cfg.max_replications, target_r + 10)

            rep_list = [done_map[s] for s in sorted(done_map.keys())]
            ci_t = compute_ci95([r["T"] for r in rep_list])
            ci_pb = compute_ci95([r["P_b"] for r in rep_list])
            max_little = max(r["little_err_sys"] for r in rep_list) * 100.0
            dt = time.perf_counter() - t_cfg

            print(" " * 115, end="\r")
            print(
                f"  [OK {idx:02d}/{total_cfgs:02d}] {cfg.config_id:<22} | R={len(rep_list):02d} | "
                f"T={ci_t['mean']:6.3f}±{ci_t['half_width']:.3f} ({ci_t['rel_half_width_pct']:4.2f}%) | "
                f"Pb={ci_pb['mean']*100:5.2f}±{ci_pb['half_width']*100:.2f}% | "
                f"Little<={max_little:.2f}% | {dt:5.1f}s",
                flush=True,
            )

    total_dt = time.perf_counter() - t_all
    total_runs = sum(len(v) for v in checkpoint.values())
    print(f"[Runner] Hoàn tất toàn bộ {total_cfgs} cấu hình ({total_runs} lượt chạy) trong {total_dt:.1f}s.\n")

    return {
        cfg.config_id: [checkpoint[cfg.config_id][s] for s in sorted(checkpoint[cfg.config_id].keys())]
        for cfg in configs
    }
