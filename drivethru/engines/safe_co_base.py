import bkitevsim.core  # Né Lỗi 5: luôn nạp bkitevsim.core trước mọi module queues

import asyncio
from typing import List, Optional

from bkitevsim.core import (
    BkSysCoLogicalProcess,
    BkSysFuture,
    BkSysLogicalProcessState,
    Event,
)


def check_and_raise_errors(error_sink: List[Exception], context: str = "BkSysCoEventLoop") -> None:
    """Fail-fast sau khi sim.run() kết thúc nếu có bất kỳ Exception nào bị event loop nuốt (Lỗi 4)."""
    if not error_sink:
        return
    first_err = error_sink[0]
    raise RuntimeError(
        f"[{context}] Phát hiện {len(error_sink)} ngoại lệ bị framework nuốt. "
        f"Lỗi đầu tiên: {type(first_err).__name__}: {first_err}"
    ) from first_err


class SafeCoLogicalProcess(BkSysCoLogicalProcess):
    """
    Lớp cơ sở an toàn bọc trên BkSysCoLogicalProcess (không sửa bkitevsim/):
    - Vá Lỗi 2: sử dụng tham số t_end thay cho end_time.
    - Vá Lỗi 3: override wait_for() kiểm tra self._pending_events trước khi tạo BkSysFuture.
    - Vá Lỗi 4: ghi lại mọi Exception trong handle_event() và coroutine_run() vào error_sink.
    - Tránh treo vòng lặp ready_lps của BkSysCoEventLoop bằng wait_until(self.t_end).
    """

    def __init__(
        self,
        lp_id: int,
        initial_state: Optional[BkSysLogicalProcessState] = None,
        t_end: float = 10000.0,
        error_sink: Optional[List[Exception]] = None,
        **kwargs,
    ):
        super().__init__(lp_id=lp_id, initial_state=initial_state, **kwargs)
        self.t_end = t_end
        self._error_sink: List[Exception] = error_sink if error_sink is not None else []

    def create_bksys_future(self) -> BkSysFuture:
        """Tạo BkSysFuture gắn với event loop hiện tại (dùng cho bảng Join của CoPickupLP)."""
        return self._create_future()

    async def wait_for(self, event_type: str, timeout: Optional[float] = None) -> Event:
        """
        Vá Lỗi 3: kiểm tra bộ đệm _pending_events theo thứ tự FIFO trước khi đăng ký waiter.
        """
        for idx, pending_ev in enumerate(self._pending_events):
            if pending_ev.event_type == event_type:
                return self._pending_events.pop(idx)
        return await super().wait_for(event_type, timeout=timeout)

    async def safe_wait_for(self, event_type: str, timeout: Optional[float] = None) -> Event:
        """Alias tường minh của wait_for() đã vá Lỗi 3."""
        return await self.wait_for(event_type, timeout=timeout)

    def handle_event(self, event: Event) -> None:
        """
        Vá Lỗi 4: bắt mọi Exception từ on_event_safe() đưa vào error_sink trước khi re-raise.
        """
        try:
            self.on_event_safe(event)
        except Exception as exc:
            self._error_sink.append(exc)
            raise

    def on_event_safe(self, event: Event) -> None:
        """
        Hook xử lý sự kiện cho lớp con. Mặc định đệm sự kiện vào _pending_events
        để tương thích với mô hình await self.wait_for(...).
        """
        self._pending_events.append(event)

    async def coroutine_run(self) -> None:
        """
        Vá Lỗi 4 cho nhánh coroutine_run(): ghi ngoại lệ vào error_sink (bỏ qua CancelledError khi loop dừng).
        """
        try:
            await self.on_coroutine_run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error_sink.append(exc)
            raise

    async def on_coroutine_run(self) -> None:
        """
        Chu trình mặc định an toàn: chạy initialize() rồi chờ tới t_end (WAITING_TIME)
        để không kẹt nhánh ready_lps của BkSysCoEventLoop._run_async().
        """
        self.initialize()
        if self._event_loop is not None:
            await self.wait_until(self.t_end)
