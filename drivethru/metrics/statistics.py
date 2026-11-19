import math
from typing import Dict, List, Sequence

# Giá trị tới hạn Student-t hai phía ở mức tin cậy 95% (alpha = 0.05)
STUDENT_T_95: Dict[int, float] = {
    1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706,
    6: 2.4469, 7: 2.3646, 8: 2.3060, 9: 2.2622, 10: 2.2281,
    14: 2.1448, 19: 2.0930, 24: 2.0639, 29: 2.04523, 30: 2.0423,
    39: 2.0227, 49: 2.0096, 59: 2.0010, 99: 1.9842, 119: 1.9801,
}


def get_t_critical_95(df: int) -> float:
    """Lấy hệ số t_{0.975, df} cho khoảng tin cậy 95% (với R=30 -> df=29 -> 2.04523)."""
    if df <= 0:
        return 0.0
    if df in STUDENT_T_95:
        return STUDENT_T_95[df]
    # Xấp xỉ Cornhish-Fisher bậc 1 chính xác cao cho df bất kỳ
    z = 1.959964
    return z + (z ** 3 + z) / (4.0 * df) + (5.0 * z ** 5 + 16.0 * z ** 3 + 3.0 * z) / (96.0 * (df ** 2))


def compute_ci95(values: Sequence[float]) -> Dict[str, float]:
    """Tính Mean, Sample Std, Half-width, [CI_low, CI_high] và Relative Half-width (%)."""
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
        "n": n,
        "mean": mean_val,
        "std": std_val,
        "half_width": hw,
        "ci_low": mean_val - hw,
        "ci_high": mean_val + hw,
        "rel_half_width_pct": rel_hw_pct,
    }


def check_littles_law(l_val: float, x_val: float, w_val: float, tol: float = 0.01) -> Dict[str, float]:
    """Kiểm tra Định luật Little L ≈ X * W với ngưỡng sai số tương đối mặc định <= 1%."""
    xw = x_val * w_val
    if l_val <= 1e-12 and xw <= 1e-12:
        rel_err = 0.0
    else:
        rel_err = abs(l_val - xw) / max(1e-12, abs(l_val))
    return {
        "L": l_val,
        "X_W": xw,
        "rel_error": rel_err,
        "passed": float(rel_err <= tol),
    }
