"""Application-layer orchestration contract tests."""

from src.backends.registry import BackendRegistry
from src.backends.scandir.backend import ScandirBackend
from src.backends.selection import SelectionPolicy
from src.core.filesystem import FileSystem
from src.core.scan_contracts import OutputOrder, ScanRequest
from src.core.scanner import CancellationToken
from src.services.directory_cache import DirectoryCache
from src.services.scan_orchestrator import ScanOrchestrator
from src.core.scan_models import ScanStatus


def test_orchestrator_creates_isolated_scandir_session(tmp_path):
    registry = BackendRegistry()
    registry.register("scandir", lambda fs: ScandirBackend(fs))
    orchestrator = ScanOrchestrator(registry, SelectionPolicy(), FileSystem())

    prepared = orchestrator.prepare(ScanRequest(str(tmp_path), CancellationToken()))

    assert prepared.decision.selected_backend == "scandir"
    assert prepared.session.backend_id == "scandir"
    assert prepared.session.output_order is OutputOrder.DFS_PREORDER


def test_cache_commit_boundary_rejects_incomplete_lifecycle_states():
    for status in (ScanStatus.CANCELLED, ScanStatus.TIMED_OUT, ScanStatus.ERROR):
        assert DirectoryCache.can_commit(status) is False

    assert DirectoryCache.can_commit(ScanStatus.COMPLETED) is True
    assert DirectoryCache.can_commit(ScanStatus.PARTIAL) is True
