import math
from typing import Dict


def erlang_b(n: int, a: float) -> float:
    """Tính xác suất từ chối Erlang B cho mô hình M/M/n/n bằng công thức đệ quy chống tràn số."""
    if a <= 0.0:
        return 0.0
    b = 1.0
    for k in range(1, n + 1):
        b = (a * b) / (k + a * b)
    return b


def erlang_c(c: int, a: float) -> float:
    """Tính xác suất phải chờ Erlang C cho mô hình M/M/c (với a = lambda / mu < c)."""
    rho = a / c
    if rho >= 1.0:
        raise ValueError(f"M/M/c không ổn định khi rho = {rho:.4f} >= 1.0")
    if a <= 0.0:
        return 0.0
    b = erlang_b(c, a)
    return b / (1.0 - rho * (1.0 - b))


def analytical_mm1(lam: float, mu: float) -> Dict[str, float]:
    """Mô hình 1: M/M/1 (c = 1, K = inf)."""
    rho = lam / mu
    if rho >= 1.0:
        raise ValueError(f"M/M/1 không ổn định khi rho = {rho:.4f} >= 1.0")
    u_val = rho
    p_w = rho
    l_q = (rho ** 2) / (1.0 - rho)
    l_sys = rho / (1.0 - rho)
    w_q = l_q / lam
    w_sys = 1.0 / (mu - lam)
    return {
        "U": u_val,
        "avg_busy": u_val,
        "L_q": l_q,
        "L": l_sys,
        "W_q": w_q,
        "W": w_sys,
        "X": lam,
        "P_b": 0.0,
        "P_w": p_w,
    }


def analytical_mm1k(lam: float, mu: float, K: int) -> Dict[str, float]:
    """Mô hình 2: M/M/1/K (c = 1, K hữu hạn)."""
    rho = lam / mu
    if abs(rho - 1.0) < 1e-12:
        probs = [1.0 / (K + 1) for _ in range(K + 1)]
    else:
        p0 = (1.0 - rho) / (1.0 - (rho ** (K + 1)))
        probs = [p0 * (rho ** k) for k in range(K + 1)]

    p0 = probs[0]
    p_b = probs[K]
    x_tput = lam * (1.0 - p_b)
    u_val = 1.0 - p0
    l_sys = sum(k * probs[k] for k in range(K + 1))
    l_q = l_sys - u_val
    w_sys = l_sys / x_tput if x_tput > 0 else 0.0
    w_q = l_q / x_tput if x_tput > 0 else 0.0
    # Xác suất phải chờ (W_q > 0) đối với các xe được nhận vào trạm
    p_w = sum(probs[1:K]) / (1.0 - p_b) if (1.0 - p_b) > 0 else 0.0

    return {
        "U": u_val,
        "avg_busy": u_val,
        "L_q": l_q,
        "L": l_sys,
        "W_q": w_q,
        "W": w_sys,
        "X": x_tput,
        "P_b": p_b,
        "P_w": p_w,
    }


def analytical_mminf(lam: float, mu: float) -> Dict[str, float]:
    """Mô hình 3: M/M/inf (c = inf, K = inf). Báo cáo U = avg_busy = a = lambda / mu."""
    a = lam / mu
    w_sys = 1.0 / mu
    return {
        "U": a,
        "avg_busy": a,
        "L_q": 0.0,
        "L": a,
        "W_q": 0.0,
        "W": w_sys,
        "X": lam,
        "P_b": 0.0,
        "P_w": 0.0,
    }


def analytical_mmnn(lam: float, mu: float, n: int) -> Dict[str, float]:
    """Mô hình 4: M/M/n/n - Erlang B (c = n, K = n, không có chỗ chờ)."""
    a = lam / mu
    p_b = erlang_b(n, a)
    x_tput = lam * (1.0 - p_b)
    avg_busy = x_tput / mu
    u_val = avg_busy / n
    l_sys = avg_busy
    w_sys = 1.0 / mu
    return {
        "U": u_val,
        "avg_busy": avg_busy,
        "L_q": 0.0,
        "L": l_sys,
        "W_q": 0.0,
        "W": w_sys,
        "X": x_tput,
        "P_b": p_b,
        "P_w": 0.0,
    }


def analytical_mmc(lam: float, mu: float, c: int) -> Dict[str, float]:
    """Mô hình 5: M/M/c - Erlang C (c >= 2, K = inf)."""
    a = lam / mu
    rho = a / c
    if rho >= 1.0:
        raise ValueError(f"M/M/c không ổn định khi rho = {rho:.4f} >= 1.0")
    p_w = erlang_c(c, a)
    l_q = p_w * rho / (1.0 - rho)
    w_q = l_q / lam
    w_sys = w_q + (1.0 / mu)
    l_sys = l_q + a
    return {
        "U": rho,
        "avg_busy": a,
        "L_q": l_q,
        "L": l_sys,
        "W_q": w_q,
        "W": w_sys,
        "X": lam,
        "P_b": 0.0,
        "P_w": p_w,
    }


def analytical_mmck(lam: float, mu: float, c: int, K: int) -> Dict[str, float]:
    """Mô hình 6: M/M/c/K tổng quát (c >= 1, K >= c hữu hạn)."""
    if K < c:
        raise ValueError(f"Sức chứa K={K} phải >= số server c={c}")
    a = lam / mu
    rho = a / c

    unnorm = []
    for k in range(K + 1):
        if k < c:
            unnorm.append((a ** k) / math.factorial(k))
        else:
            unnorm.append((a ** c) / math.factorial(c) * (rho ** (k - c)))

    total_sum = sum(unnorm)
    probs = [val / total_sum for val in unnorm]

    p_b = probs[K]
    x_tput = lam * (1.0 - p_b)
    avg_busy = x_tput / mu
    u_val = avg_busy / c
    l_q = sum((k - c) * probs[k] for k in range(c, K + 1))
    l_sys = l_q + avg_busy
    w_q = l_q / x_tput if x_tput > 0 else 0.0
    w_sys = l_sys / x_tput if x_tput > 0 else 0.0
    p_w = sum(probs[c:K]) / (1.0 - p_b) if (1.0 - p_b) > 0 else 0.0

    return {
        "U": u_val,
        "avg_busy": avg_busy,
        "L_q": l_q,
        "L": l_sys,
        "W_q": w_q,
        "W": w_sys,
        "X": x_tput,
        "P_b": p_b,
        "P_w": p_w,
    }


def analytical_single_station(lam: float, mu: float, c: float, K: float) -> Dict[str, float]:
    """Hàm điều phối tự động chọn công thức giải tích theo cặp (c, K)."""
    if math.isinf(c):
        return analytical_mminf(lam, mu)
    c_int = int(c)
    if math.isinf(K):
        if c_int == 1:
            return analytical_mm1(lam, mu)
        return analytical_mmc(lam, mu, c_int)
    K_int = int(K)
    if c_int == 1:
        return analytical_mm1k(lam, mu, K_int)
    if c_int == K_int:
        return analytical_mmnn(lam, mu, c_int)
    return analytical_mmck(lam, mu, c_int, K_int)


def analytical_fork_join_network(
    lam: float,
    c1: int, K1: int, mean_s1: float,
    c2: int, mean_s2: float,
    c3: int, mean_s3: float,
    c4: int, mean_s4: float,
) -> Dict[str, float]:
    """
    Tính xấp xỉ giải tích cho mạng Drive-thru 4 trạm Fork-Join (Công thức 50, 51 của Thiết kế V2):
    T_approx = W_1 + (W_2 + W_3 - (W_2 * W_3) / (W_2 + W_3)) + W_4
    """
    st1 = analytical_single_station(lam, 1.0 / mean_s1, c1, K1)
    lam_eff = st1["X"]
    p_b = st1["P_b"]
    w1 = st1["W"]

    st2 = analytical_single_station(lam_eff, 1.0 / mean_s2, c2, math.inf)
    st3 = analytical_single_station(lam_eff, 1.0 / mean_s3, c3, math.inf)
    st4 = analytical_single_station(lam_eff, 1.0 / mean_s4, c4, math.inf)

    w2, w3, w4 = st2["W"], st3["W"], st4["W"]
    e_max_23 = (w2 + w3 - (w2 * w3) / (w2 + w3)) if (w2 + w3) > 0 else 0.0
    wf_approx = max(0.0, e_max_23 - w2)
    t_approx = w1 + e_max_23 + w4
    t_jackson = w1 + w2 + w4

    return {
        "lambda_eff": lam_eff,
        "P_b": p_b,
        "U1": st1["U"],
        "U2": st2["U"],
        "U3": st3["U"],
        "U4": st4["U"],
        "W1": w1,
        "W2": w2,
        "W3": w3,
        "W4": w4,
        "E_max_R2_R3": e_max_23,
        "W_f_approx": wf_approx,
        "T_approx": t_approx,
        "T_jackson_no_kitchen": t_jackson,
    }
