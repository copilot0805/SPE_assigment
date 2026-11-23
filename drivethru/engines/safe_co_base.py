import bkitevsim.core  # Né Lỗi 5: luôn nạp bkitevsim.core trước mọi module queues

import asyncio
import math
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
    """Lớp cơ sở an toàn bọc trên BkSysCoLogicalProcess (vá Lỗi 2, 3, 4, 5 + chốt monotonic)."""

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
        self._last_handled_time: float = -math.inf

    def create_bksys_future(self) -> BkSysFuture:
        return self._create_future()

    async def wait_for(self, event_type: str, timeout: Optional[float] = None) -> Event:
        for idx, pending_ev in enumerate(self._pending_events):
            if pending_ev.event_type == event_type:
                return self._pending_events.pop(idx)
        return await super().wait_for(event_type, timeout=timeout)

    async def safe_wait_for(self, event_type: str, timeout: Optional[float] = None) -> Event:
        return await self.wait_for(event_type, timeout=timeout)

    def handle_event(self, event: Event) -> None:
        try:
            t = event.timestamp
            if t < self._last_handled_time - 1e-12:
                raise RuntimeError(
                    f"Vi phạm thời gian không giảm tại CoLP {self.lp_id}: "
                    f"t={t:.6f} < last_t={self._last_handled_time:.6f} ({event.event_type})"
                )
            self._last_handled_time = t
            self.on_event_safe(event)
        except Exception as exc:
            self._error_sink.append(exc)
            raise

    def on_event_safe(self, event: Event) -> None:
        self._pending_events.append(event)

    async def coroutine_run(self) -> None:
        try:
            await self.on_coroutine_run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error_sink.append(exc)
            raise

    async def on_coroutine_run(self) -> None:
        self.initialize()
        if self._event_loop is not None:
            await self.wait_until(self.t_end)
