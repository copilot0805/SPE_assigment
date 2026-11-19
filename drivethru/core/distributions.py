import random
from typing import Dict


class MultiStreamRNG:
    """
    Quản lý 5 dòng số ngẫu nhiên độc lập từ một seed gốc phục vụ Common Random Numbers (CRN):
    - 1 dòng cho khoảng thời gian giữa 2 xe đến (rng_arrival)
    - 4 dòng riêng biệt cho thời gian phục vụ tại 4 trạm (rng_service[1..4])
    """

    def __init__(self, base_seed: int = 1, station_indices=(1, 2, 3, 4), deterministic: bool = False):
        self.base_seed = base_seed
        self.deterministic = deterministic
        self.rng_arrival = random.Random(base_seed * 1000 + 1)
        self.rng_service: Dict[int, random.Random] = {
            idx: random.Random(base_seed * 1000 + 10 * idx)
            for idx in station_indices
        }

    def sample_interarrival(self, lam: float) -> float:
        if lam <= 0:
            return float("inf")
        if self.deterministic:
            return 1.0 / lam
        return self.rng_arrival.expovariate(lam)

    def sample_service(self, station_idx: int, mean_service_time: float) -> float:
        if mean_service_time <= 0:
            return 0.0
        if self.deterministic:
            return mean_service_time
        rng = self.rng_service.get(station_idx)
        if rng is None:
            rng = random.Random(self.base_seed * 1000 + 10 * station_idx)
            self.rng_service[station_idx] = rng
        return rng.expovariate(1.0 / mean_service_time)
