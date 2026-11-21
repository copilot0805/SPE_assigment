import gc
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Tuple

FIDELITY_METRICS: Tuple[str, ...] = (
    "T",
    "P_b",
    "U1",
    "U2",
    "U3",
    "U4",
    "W_f",
    "X",
    "P95_T",
    "L_system",
)


@dataclass
class EngineRunResult:
    """Chuẩn kết quả thống nhất cho cả 3 kiến trúc Engine ở M5 (mô phỏng + phần cứng)."""

    # Định danh cấu hình & engine
    engine_name: str
    seed: int
    dispatcher: str
    blocking_order: bool
    lam: float
    c2: int
    K1: int
    t_warmup: float
    t_end: float

    # Chỉ số hiệu năng mô hình Drive-thru (khớp run_single.py)
    T: float
    P95_T: float
    P_T_gt_8: float
    P_b: float
    X: float
    W_f: float
    P_f: float
    L_f: float
    L_system: float

    U1: float
    U2: float
    U3: float
    U4: float
    W1: float
    W2: float
    W3: float
    W4: float
    Wq1: float
    Wq2: float
    Wq3: float
    Wq4: float
    L1: float
    L2: float
    L3: float
    L4: float
    X1: float
    X2: float
    X3: float
    X4: float

    # Kiểm chứng bất biến (Verification)
    total_generated: int
    total_completed: int
    total_dropped: int
    n_unfinished_total: int
    n_unfinished_join: int
    flow_balance_ok: bool
    little_err_s1: float
    little_err_s2: float
    little_err_s3: float
    little_err_s4: float
    little_err_sys: float

    # Chỉ số hiệu năng bộ máy mô phỏng (M5 — 10 bước PE)
    events_processed: int
    wall_time: float
    cpu_time: float
    cpu_wall_ratio: float
    events_per_sec: float
    peak_mem_mb: float
    causality_violations: int = 0
    deadlocked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def measure_hardware_run(
    run_fn: Callable[[], Any],
    measure_memory: bool = True,
) -> Tuple[Any, Dict[str, float]]:
    """
    Đo đồng nhất wall_time (perf_counter), cpu_time (process_time) và peak_mem_mb (tracemalloc).
    Gọi gc.collect() trước khi đo để tránh nhiễu bộ nhớ từ lượt chạy trước.
    """
    gc.collect()
    already_tracing = tracemalloc.is_tracing()
    if measure_memory:
        if already_tracing:
            tracemalloc.reset_peak()
        else:
            tracemalloc.start()

    t_wall_0 = time.perf_counter()
    t_cpu_0 = time.process_time()
    result = run_fn()
    t_cpu_1 = time.process_time()
    t_wall_1 = time.perf_counter()

    peak_mem_mb = 0.0
    if measure_memory:
        _, peak_bytes = tracemalloc.get_traced_memory()
        peak_mem_mb = peak_bytes / (1024.0 * 1024.0)
        if not already_tracing:
            tracemalloc.stop()

    wall_time = max(1e-12, t_wall_1 - t_wall_0)
    cpu_time = max(0.0, t_cpu_1 - t_cpu_0)
    return result, {
        "wall_time": wall_time,
        "cpu_time": cpu_time,
        "cpu_wall_ratio": cpu_time / wall_time,
        "peak_mem_mb": peak_mem_mb,
    }


def compute_fidelity_error(
    candidate: Dict[str, Any],
    baseline: Dict[str, Any],
    tol: float = 1e-9,
    metrics: Tuple[str, ...] = FIDELITY_METRICS,
) -> Dict[str, Any]:
    """
    Kiểm chứng độ khớp fidelity giữa một engine bất kỳ và bản chuẩn Sequential cùng seed.
    Yêu cầu: max_abs_err < 1e-9 trên toàn bộ chỉ số cốt lõi.
    """
    per_metric_err: Dict[str, float] = {}
    max_err = 0.0
    worst_metric = ""
    for key in metrics:
        err = abs(float(candidate[key]) - float(baseline[key]))
        per_metric_err[key] = err
        if err > max_err:
            max_err = err
            worst_metric = key

    return {
        "max_abs_err": max_err,
        "worst_metric": worst_metric,
        "passed": max_err < tol,
        "per_metric_err": per_metric_err,
    }
