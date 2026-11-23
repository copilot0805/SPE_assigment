import gc
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

FIDELITY_METRICS: Tuple[str, ...] = (
    "T", "P_b", "U1", "U2", "U3", "U4", "W_f", "X", "P95_T", "L_system",
)


def get_process_rss_mb() -> float:
    """
    Đo bộ nhớ thực tế hệ điều hành (OS Resident Set Size / Working Set, đơn vị MB),
    bao gồm cả stack của OS threads (mà tracemalloc bỏ sót). Không cần cài psutil.
    """
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        hproc = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(hproc, ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024.0 * 1024.0)
        return 0.0

    # Linux (/proc/self/status -> VmRSS) hoặc macOS fallback
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    import resource
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / (1024.0 * 1024.0) if sys.platform == "darwin" else ru / 1024.0


@dataclass
class EngineRunResult:
    """Chuẩn kết quả thống nhất cho cả 3 kiến trúc Engine ở M5 (mô phỏng + phần cứng)."""

    engine_name: str
    seed: int
    dispatcher: str
    blocking_order: bool
    lam: float
    c2: int
    K1: int
    t_warmup: float
    t_end: float

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

    events_processed: int
    wall_time: float
    cpu_time: float
    cpu_wall_ratio: float
    events_per_sec: float
    peak_mem_mb: float
    rss_mb: float = 0.0
    delta_rss_mb: float = 0.0
    avg_active_lps_per_epoch: float = 1.0
    pct_single_lp_epochs: float = 100.0
    causality_violations: int = 0
    deadlocked: bool = False
    car_trace: Optional[List[Tuple[str, int, float, float, float]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("car_trace", None)
        return d


def measure_hardware_run(
    run_fn: Callable[[], Any],
    measure_memory: bool = True,
) -> Tuple[Any, Dict[str, float]]:
    """Đo wall_time, cpu_time, Python heap (tracemalloc) và OS RSS (GetProcessMemoryInfo/VmRSS)."""
    gc.collect()
    rss_before = get_process_rss_mb()
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

    rss_after = get_process_rss_mb()
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
        "rss_mb": rss_after,
        "delta_rss_mb": max(0.0, rss_after - rss_before),
    }


def compute_fidelity_error(
    candidate: Dict[str, Any],
    baseline: Dict[str, Any],
    tol: float = 1e-9,
    metrics: Tuple[str, ...] = FIDELITY_METRICS,
) -> Dict[str, Any]:
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


def compare_car_traces(
    cand_trace: Optional[List[Tuple[str, int, float, float, float]]],
    base_trace: Optional[List[Tuple[str, int, float, float, float]]],
    tol: float = 1e-9,
) -> Dict[str, Any]:
    """So khớp quỹ đạo từng xe (status, car_id, t_arrive, t_done, food_wait_time) giữa 2 engine."""
    if cand_trace is None or base_trace is None:
        return {"passed": False, "reason": "missing_trace", "cars_checked": 0, "max_car_err": float("inf")}
    c_sorted = sorted(cand_trace, key=lambda x: x[1])
    b_sorted = sorted(base_trace, key=lambda x: x[1])
    if len(c_sorted) != len(b_sorted):
        return {
            "passed": False,
            "reason": f"count_mismatch:{len(c_sorted)}!={len(b_sorted)}",
            "cars_checked": min(len(c_sorted), len(b_sorted)),
            "max_car_err": float("inf"),
        }
    max_err = 0.0
    for c_item, b_item in zip(c_sorted, b_sorted):
        if c_item[0] != b_item[0] or c_item[1] != b_item[1]:
            return {
                "passed": False,
                "reason": f"identity_mismatch:{c_item[:2]}!={b_item[:2]}",
                "cars_checked": len(c_sorted),
                "max_car_err": float("inf"),
            }
        err = max(
            abs(c_item[2] - b_item[2]),
            abs(c_item[3] - b_item[3]),
            abs(c_item[4] - b_item[4]),
        )
        if err > max_err:
            max_err = err
    return {"passed": max_err < tol, "reason": "ok", "cars_checked": len(c_sorted), "max_car_err": max_err}
