import math
from dataclasses import dataclass

NUM_LADDER_BUCKETS = 1024


def safe_bucket_width(t_end: float, safety_factor: float = 1.05, margin: float = 100.0) -> float:
    """
    Tính bucket_width theo công thức: ceil(1.05 * (t_end + 100) / 1024).
    Đảm bảo int(timestamp / bucket_width) < 1024 cho mọi sự kiện
    (kể cả khi t_end nhỏ hoặc có sự kiện END_SERVICE vượt qua t_end).
    Với t_end = 10000 -> trả về 11.0; t_end = 20000 -> 21.0; t_end = 60000 -> 62.0.
    """
    if t_end <= 0:
        return 1.0
    raw_width = (safety_factor * (t_end + margin)) / NUM_LADDER_BUCKETS
    return float(max(1, math.ceil(raw_width)))


@dataclass(frozen=True)
class DriveThruParams:
    """Tham số chuẩn của mạng Drive-thru theo Bảng 5, 6, 7 của Thiết kế V2 (đơn vị: phút)."""
    lam: float = 0.6
    c1: int = 2
    K1: int = 4
    mean_s1: float = 1.5     # 1 / mu_1 (Order)
    c2: int = 2
    mean_s2: float = 1.25    # 1 / mu_2 (Payment)
    c3: int = 2
    mean_s3: float = 1.5     # 1 / mu_3 (Kitchen)
    c4: int = 2
    mean_s4: float = 1.0     # 1 / mu_4 (Pickup)
    t_warmup: float = 2000.0
    t_end: float = 10000.0
    blocking_order: bool = False
