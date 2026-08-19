from __future__ import annotations

from dataclasses import dataclass

from result import Err, Ok, Result

from dux.config.schema import AppConfig
from dux.models.enums import NodeKind
from dux.models.insight import InsightBundle
from dux.models.scan import ProgressCallback, ScanError, ScanErrorCode, ScanNode, ScanOptions, ScanStats
from dux.scan import Scanner
from dux.services.insights import generate_insights
from dux.services.tree import iter_nodes


@dataclass(slots=True, frozen=True)
class RefreshOutcome:
    root: ScanNode
    stats: ScanStats
    bundle: InsightBundle
    node_by_path: dict[str, ScanNode]
    parent_by_path: dict[str, str]
    selected_path: str
    removed: bool
    refresh_access_errors: int


RefreshResult = Result[RefreshOutcome, ScanError]


@dataclass(slots=True, frozen=True)
class _LocalScan:
    node: ScanNode | None
    stats: ScanStats


def _scan_selected_path(
    scanner: Scanner,
    path: str,
    parent_path: str | None,
    options: ScanOptions,
    progress_callback: ProgressCallback | None,
) -> Result[_LocalScan, ScanError]:
    """Scan *path* through the same scanner used for the initial scan.

    Scanner roots are directories. For a selected file, scan its parent at
    depth zero and extract the matching child. This keeps native refreshes on
    the optimized readdir/getattrlistbulk path rather than adding a separate
    stat implementation.
    """
    direct = scanner.scan(path, options, progress_callback=progress_callback)
    if not isinstance(direct, Err):
        snapshot = direct.unwrap()
        return Ok(_LocalScan(node=snapshot.root, stats=snapshot.stats))

    direct_error = direct.unwrap_err()
    if direct_error.code not in {ScanErrorCode.NOT_FOUND, ScanErrorCode.NOT_DIRECTORY} or parent_path is None:
        return Err(direct_error)

    parent_result = scanner.scan(
        parent_path,
        ScanOptions(max_depth=0),
        progress_callback=progress_callback,
    )
    if isinstance(parent_result, Err):
        return Err(parent_result.unwrap_err())

    parent_snapshot = parent_result.unwrap()
    selected = next((child for child in parent_snapshot.root.children if child.path == path), None)
    if selected is None:
        # An access error while reading the parent makes absence ambiguous. In
        # that case keep the old UI data instead of incorrectly deleting it.
        if parent_snapshot.stats.access_errors:
            return Err(direct_error)
        return Ok(_LocalScan(node=None, stats=ScanStats()))

    if selected.kind is NodeKind.DIRECTORY:
        # The selected file may have been replaced by a directory between the
        # direct scan and parent probe. Rescan it recursively with the requested
        # depth so the replacement subtree is complete.
        changed_type = scanner.scan(path, options, progress_callback=progress_callback)
        if isinstance(changed_type, Err):
            return Err(changed_type.unwrap_err())
        snapshot = changed_type.unwrap()
        return Ok(_LocalScan(node=snapshot.root, stats=snapshot.stats))

    return Ok(_LocalScan(node=selected, stats=ScanStats(files=1)))


def _subtree_counts(root: ScanNode) -> tuple[int, int]:
    files = 0
    directories = 0
    for node in iter_nodes(root):
        if node.kind is NodeKind.DIRECTORY:
            directories += 1
        else:
            files += 1
    return files, directories


def _replace_subtree(
    root: ScanNode,
    selected_path: str,
    replacement: ScanNode | None,
    node_by_path: dict[str, ScanNode],
    parent_by_path: dict[str, str],
) -> ScanNode | None:
    """Return a copy-on-write root with one subtree replaced or removed."""
    if selected_path == root.path:
        return replacement

    child_path = selected_path
    new_child = replacement
    parent_path = parent_by_path.get(child_path)
    while parent_path is not None:
        old_parent = node_by_path[parent_path]
        children: list[ScanNode] = []
        for child in old_parent.children:
            if child.path == child_path:
                if new_child is not None:
                    children.append(new_child)
            else:
                children.append(child)

        new_parent = ScanNode.directory(old_parent.path, old_parent.name)
        new_parent.children = children
        new_parent.size_bytes = sum(child.size_bytes for child in children)
        new_parent.disk_usage = sum(child.disk_usage for child in children)
        children.sort(key=lambda child: child.disk_usage, reverse=True)

        child_path = parent_path
        new_child = new_parent
        parent_path = parent_by_path.get(parent_path)

    return new_child


def _index_tree(root: ScanNode) -> tuple[dict[str, ScanNode], dict[str, str]]:
    node_by_path: dict[str, ScanNode] = {}
    parent_by_path: dict[str, str] = {}
    stack: list[tuple[ScanNode, str | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        node_by_path[node.path] = node
        if parent is not None:
            parent_by_path[node.path] = parent
        for child in node.children:
            stack.append((child, node.path))
    return node_by_path, parent_by_path


def refresh_subtree(
    *,
    root: ScanNode,
    stats: ScanStats,
    selected_path: str,
    selected_depth: int,
    node_by_path: dict[str, ScanNode],
    parent_by_path: dict[str, str],
    scanner: Scanner,
    scan_options: ScanOptions,
    config: AppConfig,
    progress_callback: ProgressCallback | None = None,
) -> RefreshResult:
    """Rescan and atomically prepare all state derived from one subtree."""
    old_node = node_by_path.get(selected_path)
    if old_node is None:
        return Err(
            ScanError(
                code=ScanErrorCode.NOT_FOUND,
                path=selected_path,
                message="Selected item is no longer in the scan tree",
            )
        )

    remaining_depth = None if scan_options.max_depth is None else max(0, scan_options.max_depth - selected_depth)
    local_result = _scan_selected_path(
        scanner,
        selected_path,
        parent_by_path.get(selected_path),
        ScanOptions(max_depth=remaining_depth),
        progress_callback,
    )
    if isinstance(local_result, Err):
        return Err(local_result.unwrap_err())
    local = local_result.unwrap()

    new_root = _replace_subtree(root, selected_path, local.node, node_by_path, parent_by_path)
    if new_root is None:
        return Err(
            ScanError(
                code=ScanErrorCode.NOT_FOUND,
                path=selected_path,
                message="The scan root no longer exists",
            )
        )

    old_files, old_directories = _subtree_counts(old_node)
    new_files = local.stats.files
    new_directories = local.stats.directories
    new_stats = ScanStats(
        files=max(0, stats.files - old_files + new_files),
        directories=max(0, stats.directories - old_directories + new_directories),
        # Initial snapshots do not retain per-subtree error locations. Keep
        # their aggregate and add newly observed refresh errors. A full-root
        # refresh can replace the count exactly.
        access_errors=(
            local.stats.access_errors if selected_path == root.path else stats.access_errors + local.stats.access_errors
        ),
    )
    new_bundle = generate_insights(new_root, config)
    new_node_by_path, new_parent_by_path = _index_tree(new_root)
    return Ok(
        RefreshOutcome(
            root=new_root,
            stats=new_stats,
            bundle=new_bundle,
            node_by_path=new_node_by_path,
            parent_by_path=new_parent_by_path,
            selected_path=selected_path,
            removed=local.node is None,
            refresh_access_errors=local.stats.access_errors,
        )
    )
