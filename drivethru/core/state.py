from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional
from bkitevsim.core import BkSysLogicalProcessState


@dataclass
class CarRecord:
    """Bản ghi xe truyền qua payload của mọi Event theo Mục 1.5 và 1.6."""
    car_id: int
    t_arrive: float
    service_times: Dict[int, float] = field(default_factory=dict)
    t_enter: Dict[int, float] = field(default_factory=dict)
    t_start: Dict[int, float] = field(default_factory=dict)
    t_end: Dict[int, float] = field(default_factory=dict)
    t_payment_done: Optional[float] = None
    t_food_ready: Optional[float] = None
    food_wait_time: float = 0.0

    def copy_for_branch(self) -> "CarRecord":
        """Tạo bản sao độc lập khi tách nhánh song song (Order -> Kitchen)."""
        return CarRecord(
            car_id=self.car_id,
            t_arrive=self.t_arrive,
            service_times=dict(self.service_times),
            t_enter=dict(self.t_enter),
            t_start=dict(self.t_start),
            t_end=dict(self.t_end),
            t_payment_done=self.t_payment_done,
            t_food_ready=self.t_food_ready,
            food_wait_time=self.food_wait_time,
        )


@dataclass
class StationState(BkSysLogicalProcessState):
    queue: Deque[CarRecord] = field(default_factory=deque)
    busy: int = 0
    # Từ điển giữ xe đang đứng chờ FOOD_READY tại Order khi blocking_order=True (Exp D)
    waiting_food_cars: Dict[int, CarRecord] = field(default_factory=dict)

    # Bộ đếm toàn trình [0, t_end] phục vụ kiểm tra cân bằng dòng (Công thức 48)
    total_arrived: int = 0
    total_served: int = 0
    total_dropped: int = 0

    # Bộ đếm và tích phân trong cửa sổ quan sát [t_warmup, t_end]
    arrived: int = 0
    served: int = 0
    dropped: int = 0
    waited_count: int = 0
    last_t: float = 0.0
    area_busy: float = 0.0
    area_queue: float = 0.0
    area_system: float = 0.0
    sum_w: float = 0.0
    sum_wq: float = 0.0


@dataclass
class JoinEntry:
    car: Optional[CarRecord] = None
    xe_den: bool = False
    do_xong: bool = False
    t_p: float = 0.0
    t_f: float = 0.0


@dataclass
class PickupState(StationState):
    join_table: Dict[int, JoinEntry] = field(default_factory=dict)
    waiting_food_count: int = 0
    last_join_t: float = 0.0
    area_food_wait: float = 0.0
    food_wait_samples: List[float] = field(default_factory=list)
    food_waited_count: int = 0


@dataclass
class MonitorState(BkSysLogicalProcessState):
    total_completed: int = 0
    total_dropped: int = 0
    window_completed: int = 0
    window_dropped: int = 0
    t_samples: List[float] = field(default_factory=list)
    wf_samples: List[float] = field(default_factory=list)
