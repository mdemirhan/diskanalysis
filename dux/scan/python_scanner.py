from __future__ import annotations

from collections.abc import Sequence
from typing import override

from dux.scan._base import ThreadedScannerBase
from dux.services.fs import DEFAULT_FS, FileSystem


class PythonScanner(ThreadedScannerBase):
    def __init__(self, workers: int = 8, fs: FileSystem = DEFAULT_FS) -> None:
        super().__init__(workers=workers, fs=fs)

    @override
    def _scan_dir(self, path: str) -> tuple[Sequence[tuple[str, str, bool, int, int]], int]:
        entries: list[tuple[str, str, bool, int, int]] = []
        errors = 0
        for entry in self._fs.scandir(path):
            st = entry.stat
            if st is None:
                errors += 1
                continue
            entries.append(
                (
                    entry.path,
                    entry.name,
                    st.is_dir,
                    0 if st.is_dir else st.size,
                    0 if st.is_dir else st.disk_usage,
                )
            )
        return entries, errors
