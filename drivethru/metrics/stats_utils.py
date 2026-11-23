import math
from typing import Dict, Sequence

STUDENT_T_95: Dict[int, float] = {
    1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706,
    6: 2.4469, 7: 2.3646, 8: 2.3060, 9: 2.2622, 10: 2.2281,
    14: 2.1448, 19: 2.0930, 24: 2.0639, 29: 2.04523, 30: 2.0423,
    39: 2.0227, 49: 2.0096, 59: 2.0010, 99: 1.9842, 119: 1.9801,
}


def get_t_critical_95(df: int) -> float:
    if df <= 0:
        return 0.0
    if df in STUDENT_T_95:
        return STUDENT_T_95[df]
    z = 1.959964
    return z + (z ** 3 + z) / (4.0 * df) + (5.0 * z ** 5 + 16.0 * z ** 3 + 3.0 * z) / (96.0 * (df ** 2))


def compute_ci95(values: Sequence[float]) -> Dict[str, float]:
    n = len(values)
    if n == 0:
        return {
            "n": 0, "mean": 0.0, "std": 0.0,
            "half_width": 0.0, "ci_low": 0.0, "ci_high": 0.0, "rel_half_width_pct": 0.0,
        }
    mean_val = sum(values) / n
    if n == 1:
        return {
            "n": 1, "mean": mean_val, "std": 0.0,
            "half_width": 0.0, "ci_low": mean_val, "ci_high": mean_val, "rel_half_width_pct": 0.0,
        }
    var_val = sum((x - mean_val) ** 2 for x in values) / (n - 1)
    std_val = math.sqrt(var_val)
    t_crit = get_t_critical_95(n - 1)
    hw = t_crit * std_val / math.sqrt(n)
    rel_hw_pct = (hw / abs(mean_val) * 100.0) if abs(mean_val) > 1e-12 else 0.0
    return {
        "n": n, "mean": mean_val, "std": std_val,
        "half_width": hw, "ci_low": mean_val - hw, "ci_high": mean_val + hw,
        "rel_half_width_pct": rel_hw_pct,
    }


def check_littles_law(l_val: float, x_val: float, w_val: float, tol: float = 0.01) -> Dict[str, float]:
    xw = x_val * w_val
    rel_err = 0.0 if (l_val <= 1e-12 and xw <= 1e-12) else abs(l_val - xw) / max(1e-12, abs(l_val))
    return {"L": l_val, "X_W": xw, "rel_error": rel_err, "passed": float(rel_err <= tol)}


def evaluate_sla_status(
    ci_t: Dict[str, float],
    ci_pb: Dict[str, float],
    t_limit: float = 8.0,
    pb_limit: float = 0.05,
    eps: float = 1e-12,
) -> str:
    """
    Đánh giá trạng thái SLA 3 mức theo §2.6 Thiết kế V2:
    - 'FAIL'     : Ít nhất 1 chỉ số có cận dưới CI 95% vượt ngưỡng (chắc chắn không đạt).
    - 'PASS'     : Cả hai chỉ số có cận trên CI 95% <= ngưỡng (chắc chắn đạt).
    - 'BOUNDARY' : Chưa chắc chắn FAIL, nhưng CI 95% của T hoặc P_b chứa ngưỡng -> cần chạy thêm.
    """
    if (ci_t["ci_low"] > t_limit + eps) or (ci_pb["ci_low"] > pb_limit + eps):
        return "FAIL"
    if (ci_t["ci_high"] <= t_limit + eps) and (ci_pb["ci_high"] <= pb_limit + eps):
        return "PASS"
    return "BOUNDARY"
