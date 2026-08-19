from __future__ import annotations

from typing import override

from result import Err

from dux.config.schema import AppConfig, PatternRule
from dux.models.enums import ApplyTo, InsightCategory, NodeKind
from dux.models.scan import CancelCheck, ProgressCallback, ScanOptions, ScanResult
from dux.scan import Scanner
from dux.scan.python_scanner import PythonScanner
from dux.services.fs import DirEntry
from dux.services.refresh import refresh_subtree
from tests.fs_mock import MemoryFileSystem


class _RecordingScanner:
    def __init__(self, scanner: Scanner) -> None:
        self._scanner = scanner
        self.calls: list[tuple[str, int | None]] = []

    def scan(
        self,
        path: str,
        options: ScanOptions,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ScanResult:
        self.calls.append((path, options.max_depth))
        return self._scanner.scan(path, options, progress_callback, cancel_check)


class _FaultyMemoryFileSystem(MemoryFileSystem):
    def __init__(self) -> None:
        super().__init__()
        self.denied_paths: set[str] = set()

    @override
    def scandir(self, path: str) -> list[DirEntry]:
        return [
            DirEntry(entry.path, entry.name, None) if entry.path in self.denied_paths else entry
            for entry in super().scandir(path)
        ]


def _index(root) -> tuple[dict, dict]:
    nodes = {}
    parents = {}
    stack = [(root, None)]
    while stack:
        node, parent = stack.pop()
        nodes[node.path] = node
        if parent is not None:
            parents[node.path] = parent
        for child in node.children:
            stack.append((child, node.path))
    return nodes, parents


def _initial_state(fs: MemoryFileSystem, options: ScanOptions | None = None):
    scanner = PythonScanner(workers=1, fs=fs)
    scan_options = options or ScanOptions()
    result = scanner.scan("/r", scan_options)
    assert not isinstance(result, Err)
    snapshot = result.unwrap()
    nodes, parents = _index(snapshot.root)
    return scanner, snapshot, nodes, parents


def test_directory_refresh_reuses_scanner_and_updates_all_derived_state() -> None:
    fs = (
        MemoryFileSystem()
        .add_dir("/r")
        .add_dir("/r/sub")
        .add_file("/r/sub/old.txt", size=10)
        .add_file("/r/sibling.txt", size=20)
    )
    scanner, snapshot, nodes, parents = _initial_state(fs)
    old_sibling = nodes["/r/sibling.txt"]
    fs.remove("/r/sub/old.txt").add_file("/r/sub/new.tmp", size=40)
    config = AppConfig(
        patterns=[
            PatternRule(
                name="temp extension",
                pattern="**/*.tmp",
                category=InsightCategory.TEMP,
                apply_to=ApplyTo.FILE,
            )
        ]
    )
    recording = _RecordingScanner(scanner)

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/sub",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=recording,
        scan_options=ScanOptions(),
        config=config,
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert recording.calls == [("/r/sub", None)]
    assert outcome.root.disk_usage == 60
    assert outcome.stats.files == 2
    assert outcome.stats.directories == 2
    assert "/r/sub/old.txt" not in outcome.node_by_path
    assert outcome.node_by_path["/r/sub/new.tmp"].disk_usage == 40
    assert outcome.node_by_path["/r/sibling.txt"] is old_sibling
    assert any(item.path == "/r/sub/new.tmp" for item in outcome.bundle.insights)
    # The pre-refresh tree remains untouched until the caller swaps roots.
    assert "/r/sub/old.txt" in nodes
    assert snapshot.root.disk_usage == 30


def test_file_refresh_probes_parent_through_same_scanner_path() -> None:
    fs = MemoryFileSystem().add_dir("/r").add_file("/r/a.txt", size=10).add_file("/r/b.txt", size=20)
    scanner, snapshot, nodes, parents = _initial_state(fs)
    fs.add_file("/r/a.txt", size=50)
    recording = _RecordingScanner(scanner)

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/a.txt",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=recording,
        scan_options=ScanOptions(),
        config=AppConfig(),
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert recording.calls == [("/r/a.txt", None), ("/r", 0)]
    assert outcome.node_by_path["/r/a.txt"].disk_usage == 50
    assert outcome.root.disk_usage == 70
    assert outcome.stats.files == 2


def test_deleted_file_is_removed_and_ancestor_totals_are_updated() -> None:
    fs = MemoryFileSystem().add_dir("/r").add_file("/r/a.txt", size=10).add_file("/r/b.txt", size=20)
    scanner, snapshot, nodes, parents = _initial_state(fs)
    fs.remove("/r/a.txt")

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/a.txt",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=scanner,
        scan_options=ScanOptions(),
        config=AppConfig(),
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert outcome.removed is True
    assert "/r/a.txt" not in outcome.node_by_path
    assert outcome.root.disk_usage == 20
    assert outcome.stats.files == 1


def test_refresh_handles_file_to_directory_type_change() -> None:
    fs = MemoryFileSystem().add_dir("/r").add_file("/r/item", size=10)
    scanner, snapshot, nodes, parents = _initial_state(fs)
    fs.remove("/r/item").add_dir("/r/item").add_file("/r/item/child", size=25)

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/item",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=scanner,
        scan_options=ScanOptions(),
        config=AppConfig(),
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert outcome.node_by_path["/r/item"].kind is NodeKind.DIRECTORY
    assert "/r/item/child" in outcome.node_by_path
    assert outcome.stats.files == 1
    assert outcome.stats.directories == 2


def test_refresh_handles_directory_to_file_type_change() -> None:
    fs = MemoryFileSystem().add_dir("/r").add_dir("/r/item").add_file("/r/item/child", size=10)
    scanner, snapshot, nodes, parents = _initial_state(fs)
    fs.remove("/r/item").add_file("/r/item", size=25)

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/item",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=scanner,
        scan_options=ScanOptions(),
        config=AppConfig(),
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert outcome.node_by_path["/r/item"].kind is NodeKind.FILE
    assert "/r/item/child" not in outcome.node_by_path
    assert outcome.stats.files == 1
    assert outcome.stats.directories == 1


def test_refresh_respects_remaining_absolute_max_depth() -> None:
    fs = (
        MemoryFileSystem()
        .add_dir("/r")
        .add_dir("/r/sub")
        .add_dir("/r/sub/deep")
        .add_file("/r/sub/deep/hidden.txt", size=10)
    )
    options = ScanOptions(max_depth=1)
    scanner, snapshot, nodes, parents = _initial_state(fs, options)
    recording = _RecordingScanner(scanner)

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/sub",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=recording,
        scan_options=options,
        config=AppConfig(max_depth=1),
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert recording.calls == [("/r/sub", 0)]
    assert "/r/sub/deep" in outcome.node_by_path
    assert "/r/sub/deep/hidden.txt" not in outcome.node_by_path


def test_refresh_applies_accessible_results_and_reports_access_errors() -> None:
    fs = (
        _FaultyMemoryFileSystem()
        .add_dir("/r")
        .add_dir("/r/sub")
        .add_file("/r/sub/good.txt", size=10)
        .add_file("/r/sub/denied.txt", size=20)
    )
    assert isinstance(fs, _FaultyMemoryFileSystem)
    scanner, snapshot, nodes, parents = _initial_state(fs)
    fs.add_file("/r/sub/good.txt", size=30)
    fs.denied_paths.add("/r/sub/denied.txt")

    result = refresh_subtree(
        root=snapshot.root,
        stats=snapshot.stats,
        selected_path="/r/sub",
        selected_depth=1,
        node_by_path=nodes,
        parent_by_path=parents,
        scanner=scanner,
        scan_options=ScanOptions(),
        config=AppConfig(),
    )

    assert not isinstance(result, Err)
    outcome = result.unwrap()
    assert outcome.node_by_path["/r/sub/good.txt"].disk_usage == 30
    assert "/r/sub/denied.txt" not in outcome.node_by_path
    assert outcome.refresh_access_errors == 1
