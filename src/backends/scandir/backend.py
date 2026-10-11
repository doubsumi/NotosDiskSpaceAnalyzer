"""Adapter exposing the existing DirectoryScanner as a backend."""

from __future__ import annotations

from typing import Any, Iterator

from src.core.scan_contracts import (
    BackendCapabilities,
    EntrySink,
    OutputOrder,
    ScanDiagnostics,
    ScanRequest,
)
from src.core.scanner import DirectoryScanner


class ScandirSession:
    backend_id = "scandir"
    output_order = OutputOrder.DFS_PREORDER

    def __init__(self, request: ScanRequest, filesystem: Any, scanner_factory=DirectoryScanner):
        self.request = request
        self.scanner = scanner_factory(filesystem)

    def iter_entries(self) -> Iterator:
        yield from self.scanner.scan(self.request.root_path, self.request.context())

    def run(self, sink: EntrySink) -> ScanDiagnostics:
        batch = []
        for entry in self.iter_entries():
            batch.append(entry)
            if len(batch) >= self.request.execution.batch_size:
                sink.consume_batch(batch)
                batch = []
        if batch:
            sink.consume_batch(batch)
        stats = self.scanner.statistics
        return ScanDiagnostics(
            status=self.scanner.status,
            error_count=stats.errors if stats else 0,
            skipped_count=stats.skipped if stats else 0,
            error_breakdown=dict(self.scanner.error_breakdown),
            error_paths=list(self.scanner.error_paths),
            backend_id=self.backend_id,
            output_order=self.output_order,
        )

    def cancel(self) -> None:
        self.request.cancel_token.cancel()


class ScandirBackend:
    backend_id = "scandir"

    def __init__(self, filesystem: Any = None, scanner_factory=DirectoryScanner):
        self.filesystem = filesystem
        self.scanner_factory = scanner_factory

    def probe(self, request: ScanRequest) -> BackendCapabilities:
        return BackendCapabilities(
            backend_id=self.backend_id,
            supported=True,
            output_order=OutputOrder.DFS_PREORDER,
            supports_arbitrary_directory=True,
            supports_hidden_entries=True,
            supports_symlink_policy=True,
            reliable_file_identity=bool(
                getattr(self.filesystem, "probe_hard_links", False)
            ),
            supports_logical_size=True,
            supports_cancellation=True,
        )

    def create_session(self, request: ScanRequest) -> ScandirSession:
        capabilities = self.probe(request)
        if not capabilities.supported:
            raise RuntimeError(capabilities.reason or "scandir backend unavailable")
        return ScandirSession(
            request, self.filesystem, scanner_factory=self.scanner_factory
        )
