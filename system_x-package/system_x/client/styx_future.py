import asyncio
import dataclasses
import threading
from abc import ABC

from system_x.common.exceptions import FutureAlreadySet, FutureTimedOut


@dataclasses.dataclass
class SysXResponse(object):
    request_id: bytes
    in_timestamp: int = -1
    out_timestamp: int = -1
    response: any = None

    @property
    def system_x_latency_ms(self) -> float:
        return self.out_timestamp - self.in_timestamp


class BaseFuture(ABC):
    _timeout: int
    _condition: threading.Event | asyncio.Event
    _val: SysXResponse

    def __init__(self, request_id: bytes, timeout_sec: int, is_async: bool = False):
        self._val: SysXResponse = SysXResponse(request_id=request_id)
        self._condition: threading.Event | asyncio.Event = asyncio.Event() if is_async else threading.Event()
        self._timeout = timeout_sec

    @property
    def request_id(self):
        return self._val.request_id

    def set_in_timestamp(self, in_timestamp: int) -> None:
        self._val.in_timestamp = in_timestamp

    def done(self) -> bool:
        return self._condition.is_set()

    def set(self, response_val: any, out_timestamp: int):
        if self._condition.is_set():
            raise FutureAlreadySet(f"{self._val.request_id} Trying to set Future to |{response_val}|"
                                   f" Future has already been set to |{self._val.response}|")
        self._val.response = response_val
        self._val.out_timestamp = out_timestamp
        self._condition.set()


class SysXFuture(BaseFuture):
    def __init__(self, request_id: bytes, timeout_sec: int = 30):
        super().__init__(request_id, timeout_sec)

    def get(self) -> SysXResponse | None:
        success = self._condition.wait(timeout=self._timeout)
        if not success:
            raise FutureTimedOut(f"Future for request: {self._val.request_id}"
                                 f" timed out after {self._timeout} seconds.")
        return self._val


class SysXAsyncFuture(BaseFuture):
    def __init__(self, request_id: bytes, timeout_sec: int = 30):
        super().__init__(request_id, timeout_sec, is_async=True)

    async def get(self) -> SysXResponse | None:
        try:
            await asyncio.wait_for(self._condition.wait(), self._timeout)
        except asyncio.TimeoutError:
            raise FutureTimedOut(f"Future for request: {self._val.request_id}"
                                 f" timed out after {self._timeout} seconds.")
        return self._val
