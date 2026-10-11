"""Pure-Python scan orchestration.

This module is deliberately free of Qt and GUI result types.  It owns backend
selection and session creation so GUI adapters only need to submit a request
and consume the resulting application data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backends.registry import BackendRegistry
from src.backends.selection import SelectionPolicy
from src.core.scan_contracts import BackendDecision, ScanRequest, ScanSession


@dataclass(frozen=True)
class PreparedScan:
    """A selected, isolated scan session and the decision that produced it."""

    request: ScanRequest
    decision: BackendDecision
    session: ScanSession


class ScanOrchestrator:
    """Select and create independent scan sessions.

    A session is never switched to another backend after it starts.  Retry or
    fallback callers must ask this orchestrator for a new ``PreparedScan``.
    """

    def __init__(
        self,
        registry: BackendRegistry,
        selection_policy: SelectionPolicy,
        filesystem: Any,
    ) -> None:
        self.registry = registry
        self.selection_policy = selection_policy
        self.filesystem = filesystem

    def prepare(self, request: ScanRequest) -> PreparedScan:
        decision = self.selection_policy.select(
            request, self.registry, self.filesystem
        )
        if decision.selected_backend is None:
            raise RuntimeError(decision.reason)
        backend = self.registry.create(decision.selected_backend, self.filesystem)
        return PreparedScan(
            request=request,
            decision=decision,
            session=backend.create_session(request),
        )

    def run(self, request: ScanRequest, sink) -> tuple[PreparedScan, object]:
        """Run one isolated session and return its decision plus diagnostics."""

        prepared = self.prepare(request)
        return prepared, prepared.session.run(sink)
