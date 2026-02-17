from __future__ import annotations

import sys

import pytest

from dux.scan import default_scanner
from dux.scan._base import ThreadedScannerBase


class TestDefaultScanner:
    def test_darwin_returns_native_scanner(self) -> None:
        if sys.platform != "darwin":
            pytest.skip("macOS only")
        scanner = default_scanner()
        assert isinstance(scanner, ThreadedScannerBase)
        from dux.scan.native_scanner import NativeScanner

        assert isinstance(scanner, NativeScanner)
