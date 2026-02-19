from __future__ import annotations

from typing import override

from dux.models.scan import ScanNode
from dux.scan._base import ThreadedScannerBase


class PythonScanner(ThreadedScannerBase):
    @override
    def _scan_dir(self, parent: ScanNode, path: str) -> tuple[list[ScanNode], int, int, int]:
        dir_children: list[ScanNode] = []
        errors = 0
        files = 0
        dirs = 0
        for entry in self._fs.scandir(path):
            st = entry.stat
            if st is None:
                errors += 1
                continue
            if st.is_dir:
                node = ScanNode.directory(entry.path, entry.name)
                parent.children.append(node)
                dir_children.append(node)
                dirs += 1
            else:
                node = ScanNode.file(entry.path, entry.name, st.size, st.disk_usage)
                parent.children.append(node)
                files += 1
        return dir_children, files, dirs, errors
