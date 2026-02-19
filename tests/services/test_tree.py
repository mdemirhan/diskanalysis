from __future__ import annotations

from dux.models.enums import NodeKind
from dux.services.tree import iter_nodes, top_nodes
from tests.factories import make_dir, make_file


class TestIterNodes:
    def test_single_root(self) -> None:
        root = make_dir("/root")
        assert list(iter_nodes(root)) == [root]

    def test_nested_tree(self) -> None:
        f1 = make_file("/root/a.txt", du=10)
        f2 = make_file("/root/sub/b.txt", du=20)
        sub = make_dir("/root/sub", du=20, children=[f2])
        root = make_dir("/root", du=30, children=[f1, sub])
        paths = [n.path for n in iter_nodes(root)]
        assert "/root" in paths
        assert "/root/a.txt" in paths
        assert "/root/sub" in paths
        assert "/root/sub/b.txt" in paths
        assert len(paths) == 4


class TestTopNodes:
    def test_kind_none_returns_all(self) -> None:
        f1 = make_file("/r/a", du=10)
        f2 = make_file("/r/b", du=20)
        sub = make_dir("/r/sub", du=20, children=[f2])
        root = make_dir("/r", du=30, children=[f1, sub])
        result = top_nodes(root, 10, kind=None)
        # root excluded, all others present
        assert len(result) == 3
        assert result[0].path in {"/r/sub", "/r/b"}

    def test_kind_file(self) -> None:
        f1 = make_file("/r/a", du=10)
        f2 = make_file("/r/b", du=20)
        sub = make_dir("/r/sub", du=5)
        root = make_dir("/r", du=35, children=[f1, f2, sub])
        result = top_nodes(root, 10, kind=NodeKind.FILE)
        assert all(n.kind is NodeKind.FILE for n in result)
        assert len(result) == 2
        assert result[0].disk_usage >= result[1].disk_usage

    def test_kind_directory(self) -> None:
        f1 = make_file("/r/a", du=10)
        sub = make_dir("/r/sub", du=5)
        root = make_dir("/r", du=15, children=[f1, sub])
        result = top_nodes(root, 10, kind=NodeKind.DIRECTORY)
        assert len(result) == 1
        assert result[0].path == "/r/sub"

    def test_n_greater_than_count(self) -> None:
        f1 = make_file("/r/a", du=10)
        root = make_dir("/r", du=10, children=[f1])
        result = top_nodes(root, 100, kind=None)
        assert len(result) == 1

    def test_root_excluded(self) -> None:
        root = make_dir("/r", du=100)
        result = top_nodes(root, 10, kind=None)
        assert len(result) == 0
