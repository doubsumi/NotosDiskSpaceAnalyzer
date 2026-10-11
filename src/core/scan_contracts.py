"""Stable contracts shared by scan backends and the application pipeline.

The contracts deliberately describe capabilities and lifecycle without knowing
about Qt, a concrete filesystem API, or a particular aggregator.  The current
``scandir`` implementation can therefore remain the optimized baseline while
future backends (for example an NTFS prototype) are introduced independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol

from src.core.scan_models import CancelToken, ScanContext, ScanEntry, ScanStatus


class OutputOrder(Enum):
    """Ordering guarantee of a backend's normalized facts."""

    DFS_PREORDER = "dfs_preorder"
    UNORDERED = "unordered"
    BACKEND_DEFINED = "backend_defined"


@dataclass(frozen=True)
class ScanOptions:
    """Options that affect scan semantics rather than execution mechanics."""

    include_hidden: bool = True
    follow_symlinks: bool = False
    deduplicate_files: bool = True


@dataclass(frozen=True)
class ExecutionPolicy:
    """Execution hints.  They must not change the meaning of a result."""

    enable_parallel_enum: bool = False
    batch_size: int = 256


@dataclass(frozen=True)
class ScanRequest:
    """A complete request passed to backend probing and session creation."""

    root_path: str
    cancel_token: CancelToken
    options: ScanOptions = field(default_factory=ScanOptions)
    execution: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    backend_preference: str = "auto"

    def context(self) -> ScanContext:
        """Build the legacy context used by the current scanner backend."""

        return ScanContext(
            root_path=self.root_path,
            cancel_token=self.cancel_token,
            include_hidden=self.options.include_hidden,
            follow_symlinks=self.options.follow_symlinks,
            enable_parallel_enum=self.execution.enable_parallel_enum,
        )


@dataclass(frozen=True)
class BackendCapabilities:
    """Capabilities for a concrete request, not merely theoretical features."""

    backend_id: str
    supported: bool
    reason: Optional[str] = None
    output_order: OutputOrder = OutputOrder.BACKEND_DEFINED
    supports_arbitrary_directory: bool = False
    supports_hidden_entries: bool = False
    supports_symlink_policy: bool = False
    reliable_file_identity: bool = False
    supports_logical_size: bool = True
    supports_allocated_size: bool = False
    supports_cancellation: bool = True
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackendDecision:
    """Auditable result of backend selection."""

    selected_backend: Optional[str]
    candidates: tuple[str, ...]
    rejected: Dict[str, str] = field(default_factory=dict)
    reason: str = ""
    policy_version: str = "1"


@dataclass
class ScanDiagnostics:
    """Backend-neutral diagnostics returned by a scan session."""

    status: ScanStatus
    error_count: int = 0
    skipped_count: int = 0
    error_breakdown: Dict[str, int] = field(default_factory=dict)
    error_paths: List[str] = field(default_factory=list)
    backend_id: str = ""
    output_order: OutputOrder = OutputOrder.BACKEND_DEFINED


class EntrySink(Protocol):
    def consume_batch(self, batch: Iterable[ScanEntry]) -> None: ...


class ScanSession(Protocol):
    backend_id: str
    output_order: OutputOrder

    def run(self, sink: EntrySink) -> ScanDiagnostics: ...

    def cancel(self) -> None: ...


class ScannerBackend(Protocol):
    backend_id: str

    def probe(self, request: ScanRequest) -> BackendCapabilities: ...

    def create_session(self, request: ScanRequest) -> ScanSession: ...


BackendFactory = Callable[[Any], ScannerBackend]
