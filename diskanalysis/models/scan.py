from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from diskanalysis.models.enums import NodeKind


ProgressCallback = Callable[[str, int, int], None]
CancelCheck = Callable[[], bool]


@dataclass(slots=True)
class ScanNode:
    path: str
    name: str
    kind: NodeKind
    size_bytes: int
    modified_ts: float
    children: list[ScanNode] = field(default_factory=list)

    @property
    def is_dir(self) -> bool:
        return self.kind is NodeKind.DIRECTORY


@dataclass(slots=True)
class ScanStats:
    files: int = 0
    directories: int = 0
    bytes_total: int = 0
    access_errors: int = 0


@dataclass(slots=True)
class ScanOptions:
    max_depth: int | None = None
    follow_symlinks: bool = False
    exclude_paths: tuple[str, ...] = ()


@dataclass(slots=True)
class ScanSuccess:
    root: ScanNode
    stats: ScanStats


@dataclass(slots=True)
class ScanFailure:
    path: str
    message: str


ScanResult = ScanSuccess | ScanFailure


def normalize_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())
