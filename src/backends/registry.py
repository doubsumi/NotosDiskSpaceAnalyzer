"""Explicit static registry for scan backends.

Registration is intentionally boring: the application composition root owns
which backends are available, and selection never imports a concrete backend.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from src.core.scan_contracts import ScannerBackend


class BackendRegistry:
    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[Any], ScannerBackend]] = {}

    def register(self, backend_id: str, factory: Callable[[Any], ScannerBackend]) -> None:
        if not backend_id or backend_id in self._factories:
            raise ValueError(f"backend already registered: {backend_id!r}")
        self._factories[backend_id] = factory

    def ids(self) -> List[str]:
        return list(self._factories)

    def create(self, backend_id: str, filesystem: Any) -> ScannerBackend:
        try:
            return self._factories[backend_id](filesystem)
        except KeyError as exc:
            raise KeyError(f"unknown scan backend: {backend_id}") from exc
