import math
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ExpAConfig:
    """Cấu hình cho 1 kịch bản kiểm chứng mô hình đơn trong Thí nghiệm A."""
    code: str
    model_name: str
    c: float
    K: float
    rho_or_a: float
    lam: float
    mu: float = 1.0
    t_warmup: float = 2000.0
    t_end: float = 20000.0
    num_replications: int = 30


def get_exp_a_configs() -> List[ExpAConfig]:
    """Trả về danh sách 18 cấu hình chuẩn của Thí nghiệm A (6 mô hình đơn x 3 mức tải)."""
    mu = 1.0
    configs: List[ExpAConfig] = []

    # 1. M/M/1 (c=1, K=inf), riêng rho=0.9 chạy t_end=60000 theo Mục 2.5 Design V2
    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        t_end = 60000.0 if abs(rho - 0.9) < 1e-9 else 20000.0
        configs.append(ExpAConfig(f"A1-{idx}", "M/M/1", 1, math.inf, rho, rho * mu, mu, 2000.0, t_end))

    # 2. M/M/1/K (c=1, K=4) -> P_b lý thuyết >= 6.25% ở mọi mức tải
    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A2-{idx}", "M/M/1/4", 1, 4, rho, rho * mu, mu, 2000.0, 20000.0))

    # 3. M/M/inf (c=inf, K=inf), a in {1.0, 2.0, 4.0}
    for idx, a in enumerate((1.0, 2.0, 4.0), start=1):
        configs.append(ExpAConfig(f"A3-{idx}", "M/M/inf", math.inf, math.inf, a, a * mu, mu, 2000.0, 20000.0))

    # 4. M/M/n/n - Erlang B (c=3, K=3), rho = lambda / (3*mu) in {0.5, 0.8, 0.9}
    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A4-{idx}", "M/M/3/3 (Erlang B)", 3, 3, rho, 3 * rho * mu, mu, 2000.0, 20000.0))

    # 5. M/M/c - Erlang C (c=2, K=inf), rho = lambda / (2*mu) in {0.5, 0.8, 0.9}
    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A5-{idx}", "M/M/2 (Erlang C)", 2, math.inf, rho, 2 * rho * mu, mu, 2000.0, 20000.0))

    # 6. M/M/c/K (c=2, K=5), rho = lambda / (2*mu) in {0.5, 0.8, 0.9}
    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A6-{idx}", "M/M/2/5", 2, 5, rho, 2 * rho * mu, mu, 2000.0, 20000.0))

    return configs
