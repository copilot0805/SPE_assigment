from enum import Enum, IntEnum


class LPID(IntEnum):
    """Định danh cố định của 6 Logical Processes trong hệ thống Drive-thru."""
    CAR_SOURCE = 0
    ORDER = 1
    PAYMENT = 2
    KITCHEN = 3
    PICKUP = 4
    MONITOR = 5


class EventType(str, Enum):
    """Đúng 10 loại sự kiện chuẩn theo Thiết kế V2 (Mục 1.5)."""
    GENERATE = "GENERATE"
    ARRIVAL = "ARRIVAL"
    TRANSFER = "TRANSFER"
    ORDER_PLACED = "ORDER_PLACED"
    FOOD_READY = "FOOD_READY"
    BEGIN_SERVICE = "BEGIN_SERVICE"
    END_SERVICE = "END_SERVICE"
    DROP = "DROP"
    DEPARTURE = "DEPARTURE"
    WARMUP_END = "WARMUP_END"
