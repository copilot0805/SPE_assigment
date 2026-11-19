import math
from dataclasses import dataclass
from typing import List, Tuple
from drivethru.config.simulation_config import DriveThruParams


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


@dataclass(frozen=True)
class NetworkExpConfig:
    """Cấu hình cho 1 kịch bản mạng Drive-thru 4 trạm thuộc Exp B, C, D."""
    config_id: str
    exp_tags: Tuple[str, ...]      # Ví dụ: ("ExpC", "ExpB") hoặc ("ExpC", "ExpD_NB")
    scenario_name: str             # Light, Normal, Peak, Heavy
    params: DriveThruParams
    base_replications: int = 30
    max_replications: int = 60     # Tự động mở rộng seed nếu CI95% > 5% (Mục 2.5 Design V2)


def get_exp_a_configs() -> List[ExpAConfig]:
    """Trả về danh sách 18 cấu hình chuẩn của Thí nghiệm A (6 mô hình đơn x 3 mức tải)."""
    mu = 1.0
    configs: List[ExpAConfig] = []

    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        t_end = 60000.0 if abs(rho - 0.9) < 1e-9 else 20000.0
        configs.append(ExpAConfig(f"A1-{idx}", "M/M/1", 1, math.inf, rho, rho * mu, mu, 2000.0, t_end))

    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A2-{idx}", "M/M/1/4", 1, 4, rho, rho * mu, mu, 2000.0, 20000.0))

    for idx, a in enumerate((1.0, 2.0, 4.0), start=1):
        configs.append(ExpAConfig(f"A3-{idx}", "M/M/inf", math.inf, math.inf, a, a * mu, mu, 2000.0, 20000.0))

    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A4-{idx}", "M/M/3/3 (Erlang B)", 3, 3, rho, 3 * rho * mu, mu, 2000.0, 20000.0))

    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A5-{idx}", "M/M/2 (Erlang C)", 2, math.inf, rho, 2 * rho * mu, mu, 2000.0, 20000.0))

    for idx, rho in enumerate((0.5, 0.8, 0.9), start=1):
        configs.append(ExpAConfig(f"A6-{idx}", "M/M/2/5", 2, 5, rho, 2 * rho * mu, mu, 2000.0, 20000.0))

    return configs


def get_exp_bcd_configs() -> List[NetworkExpConfig]:
    """
    Trả về đúng 53 cấu hình duy nhất cho toàn bộ Exp B, Exp C, Exp D (Bảng 10 & 12 Design V2):
    - 48 cấu hình giai thừa đầy đủ Exp C: lam in {0.2, 0.4, 0.6, 0.7} x c2 in {1, 2, 3} x K1 in {3, 4, 6, 8}
      (trong đó c2=1, K1=8 dùng chung cho Exp B Baseline; c2=2, K1=8 với lam in {0.4, 0.6, 0.7} dùng chung cho Exp D Non-blocking)
    - 2 cấu hình đối chiếu Fork-Join của Exp B (K1=30, lam=0.6, c2=1): cơ sở (1/mu3=1.5) và thu gọn (1/mu3=0.01)
    - 3 cấu hình biến thể Chặn (blocking_order=True) của Exp D (c2=2, K1=8, lam in {0.4, 0.6, 0.7})
    """
    workloads = [
        ("Light", 0.2),
        ("Normal", 0.4),
        ("Peak", 0.6),
        ("Heavy", 0.7),
    ]
    c2_levels = [1, 2, 3]
    k1_levels = [3, 4, 6, 8]

    configs: List[NetworkExpConfig] = []

    # 1. 48 cấu hình Exp C (đồng thời gắn tag dùng chung cho Exp B và Exp D Non-blocking)
    for sc_name, lam in workloads:
        for c2 in c2_levels:
            for k1 in k1_levels:
                tags = ["ExpC"]
                if c2 == 1 and k1 == 8:
                    tags.append("ExpB_Base")
                if c2 == 2 and k1 == 8 and lam in (0.4, 0.6, 0.7):
                    tags.append("ExpD_NB")

                cfg_id = f"C_lam{int(round(lam * 10))}_c2_{c2}_K1_{k1}"
                params = DriveThruParams(
                    lam=lam, c1=2, K1=k1, mean_s1=1.5,
                    c2=c2, mean_s2=1.25,
                    c3=2, mean_s3=1.5,
                    c4=2, mean_s4=1.0,
                    t_warmup=2000.0, t_end=10000.0,
                    blocking_order=False,
                )
                configs.append(NetworkExpConfig(cfg_id, tuple(tags), sc_name, params))

    # 2. 2 cấu hình đối chiếu Fork-Join của Exp B (K1=30, lam=0.6, c2=1)
    configs.append(
        NetworkExpConfig(
            config_id="B_FJ_K30_base",
            exp_tags=("ExpB_FJ",),
            scenario_name="Peak_K30",
            params=DriveThruParams(
                lam=0.6, c1=2, K1=30, mean_s1=1.5,
                c2=1, mean_s2=1.25,
                c3=2, mean_s3=1.5,
                c4=2, mean_s4=1.0,
                t_warmup=2000.0, t_end=10000.0,
                blocking_order=False,
            ),
        )
    )
    configs.append(
        NetworkExpConfig(
            config_id="B_FJ_K30_deg",
            exp_tags=("ExpB_FJ",),
            scenario_name="Peak_K30_NoKitchen",
            params=DriveThruParams(
                lam=0.6, c1=2, K1=30, mean_s1=1.5,
                c2=1, mean_s2=1.25,
                c3=2, mean_s3=0.01,
                c4=2, mean_s4=1.0,
                t_warmup=2000.0, t_end=10000.0,
                blocking_order=False,
            ),
        )
    )

    # 3. 3 cấu hình biến thể Chặn (blocking_order=True) của Exp D (c2=2, K1=8, lam in {0.4, 0.6, 0.7})
    for sc_name, lam in [("Normal", 0.4), ("Peak", 0.6), ("Heavy", 0.7)]:
        cfg_id = f"D_BLK_lam{int(round(lam * 10))}_c2_2_K1_8"
        params = DriveThruParams(
            lam=lam, c1=2, K1=8, mean_s1=1.5,
            c2=2, mean_s2=1.25,
            c3=2, mean_s3=1.5,
            c4=2, mean_s4=1.0,
            t_warmup=2000.0, t_end=10000.0,
            blocking_order=True,
        )
        configs.append(NetworkExpConfig(cfg_id, ("ExpD_BLK",), sc_name, params))

    return configs
