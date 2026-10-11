"""Backend selection policy with explicit, explainable decisions."""

from __future__ import annotations

from src.backends.registry import BackendRegistry
from src.core.scan_contracts import BackendDecision, ScanRequest


class SelectionPolicy:
    """Select a registered backend without executing a scan."""

    VERSION = "1"

    def select(self, request: ScanRequest, registry: BackendRegistry, filesystem) -> BackendDecision:
        candidates = registry.ids()
        preference = request.backend_preference.lower()
        if preference != "auto":
            candidates = [backend_id for backend_id in candidates if backend_id == preference]

        rejected = {}
        for backend_id in candidates:
            backend = registry.create(backend_id, filesystem)
            capabilities = backend.probe(request)
            if capabilities.supported:
                return BackendDecision(
                    selected_backend=backend_id,
                    candidates=tuple(registry.ids()),
                    rejected=rejected,
                    reason="explicit preference" if preference != "auto" else "first compatible backend",
                    policy_version=self.VERSION,
                )
            rejected[backend_id] = capabilities.reason or "backend does not support request"

        return BackendDecision(
            selected_backend=None,
            candidates=tuple(registry.ids()),
            rejected=rejected,
            reason="no registered backend can satisfy request",
            policy_version=self.VERSION,
        )
