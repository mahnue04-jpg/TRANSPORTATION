"""In-memory Stay360 state. Resets back to synthetic fixtures."""

from __future__ import annotations

import copy
import threading
from typing import Callable, TypeVar

from .fixtures import build_state

T = TypeVar("T")


class Stay360Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants = build_state()

    def reset(self) -> None:
        with self._lock:
            self._tenants = build_state()

    def tenant_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._tenants)

    def read(self, reader: Callable[[dict], T]) -> T:
        with self._lock:
            snapshot = copy.deepcopy(self._tenants)
        return reader(snapshot)

    def write(self, writer: Callable[[dict], T]) -> T:
        with self._lock:
            return writer(self._tenants)


STORE = Stay360Store()


def reset_stay360_store() -> None:
    STORE.reset()
