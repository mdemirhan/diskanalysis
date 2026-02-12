from __future__ import annotations

from pathlib import Path

from result import Err, Ok

from diskanalysis.models.scan import ScanErrorCode, ScanOptions
from diskanalysis.services.scanner import scan_path


def _write_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_scanner_returns_valid_results(tmp_path: Path) -> None:
    _write_file(tmp_path / "big.bin", 128)
    _write_file(tmp_path / "small.bin", 32)
    _write_file(tmp_path / "sub" / "nested.bin", 64)

    result = scan_path(tmp_path, ScanOptions())

    assert isinstance(result, Ok)
    snapshot = result.unwrap()
    assert snapshot.stats.files == 3
    assert snapshot.stats.directories >= 2
    assert snapshot.root.size_bytes == 224


def test_missing_path_returns_error(tmp_path: Path) -> None:
    result = scan_path(tmp_path / "does-not-exist", ScanOptions())

    assert isinstance(result, Err)
    error = result.unwrap_err()
    assert error.code is ScanErrorCode.NOT_FOUND
    assert "does not exist" in error.message.lower()


def test_children_sorted_by_size_descending(tmp_path: Path) -> None:
    _write_file(tmp_path / "a.bin", 10)
    _write_file(tmp_path / "b.bin", 100)
    _write_file(tmp_path / "c.bin", 50)

    result = scan_path(tmp_path, ScanOptions())
    assert isinstance(result, Ok)
    snapshot = result.unwrap()

    names = [child.name for child in snapshot.root.children if not child.is_dir]
    assert names == ["b.bin", "c.bin", "a.bin"]


def test_max_depth_respected(tmp_path: Path) -> None:
    _write_file(tmp_path / "lvl1" / "lvl2" / "f.bin", 20)

    result = scan_path(tmp_path, ScanOptions(max_depth=0))
    assert isinstance(result, Ok)
    snapshot = result.unwrap()

    lvl1 = next(child for child in snapshot.root.children if child.name == "lvl1")
    assert lvl1.children == []


def test_excluded_paths_respected(tmp_path: Path) -> None:
    _write_file(tmp_path / "include" / "ok.bin", 10)
    _write_file(tmp_path / "ignore" / "skip.bin", 50)

    result = scan_path(tmp_path, ScanOptions(exclude_paths=("**/ignore", "**/ignore/**")))
    assert isinstance(result, Ok)
    snapshot = result.unwrap()

    all_paths = {child.path for child in snapshot.root.children}
    assert not any("ignore" in path for path in all_paths)


def test_progress_callback_invoked(tmp_path: Path) -> None:
    _write_file(tmp_path / "f1.bin", 1)
    _write_file(tmp_path / "f2.bin", 1)

    callbacks: list[tuple[str, int, int]] = []

    def progress(path: str, files: int, directories: int) -> None:
        callbacks.append((path, files, directories))

    result = scan_path(tmp_path, ScanOptions(), progress_callback=progress)
    assert isinstance(result, Ok)
    assert callbacks


def test_cancellation_respected(tmp_path: Path) -> None:
    for idx in range(50):
        _write_file(tmp_path / f"f{idx}.bin", 1)

    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 2

    result = scan_path(tmp_path, ScanOptions(), cancel_check=cancel)
    assert isinstance(result, Err)
    error = result.unwrap_err()
    assert error.code is ScanErrorCode.CANCELLED
    assert "cancel" in error.message.lower()
