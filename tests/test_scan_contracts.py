"""Contract and backend-selection tests from the platform architecture."""

from src.backends.registry import BackendRegistry
from src.backends.scandir.backend import ScandirBackend
from src.backends.selection import SelectionPolicy
from src.core.filesystem import FileSystem
from src.core.scan_contracts import OutputOrder, ScanRequest, ScanOptions
from src.core.scanner import CancellationToken


def test_scandir_backend_reports_explicit_capabilities(tmp_path):
    request = ScanRequest(str(tmp_path), CancellationToken())
    backend = ScandirBackend(FileSystem(probe_hard_links=True))

    capabilities = backend.probe(request)

    assert capabilities.supported is True
    assert capabilities.output_order is OutputOrder.DFS_PREORDER
    assert capabilities.supports_arbitrary_directory is True
    assert capabilities.supports_symlink_policy is True
    assert capabilities.reliable_file_identity is True


def test_selection_policy_returns_auditable_decision(tmp_path):
    registry = BackendRegistry()
    registry.register("scandir", lambda fs: ScandirBackend(fs))
    request = ScanRequest(
        str(tmp_path), CancellationToken(), backend_preference="scandir"
    )

    decision = SelectionPolicy().select(request, registry, FileSystem())

    assert decision.selected_backend == "scandir"
    assert decision.candidates == ("scandir",)
    assert decision.reason == "explicit preference"
    assert decision.policy_version


def test_scandir_session_streams_entries_and_diagnostics(tmp_path):
    (tmp_path / "one.txt").write_bytes(b"one")
    request = ScanRequest(
        str(tmp_path), CancellationToken(), options=ScanOptions(include_hidden=True)
    )
    session = ScandirBackend(FileSystem()).create_session(request)
    received = []

    diagnostics = session.run(type("Sink", (), {
        "consume_batch": lambda self, batch: received.extend(batch),
    })())

    assert [entry.name for entry in received] == ["one.txt"]
    assert diagnostics.backend_id == "scandir"
    assert diagnostics.output_order is OutputOrder.DFS_PREORDER
    assert diagnostics.error_count == 0
