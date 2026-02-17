from __future__ import annotations

from enum import Enum, IntFlag
from typing import Any


class NodeKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"


class InsightCategory(str, Enum):
    TEMP = "temp"
    CACHE = "cache"
    BUILD_ARTIFACT = "build_artifact"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class ApplyTo(IntFlag):
    FILE = 1
    DIR = 2
    BOTH = FILE | DIR

    @classmethod
    def from_str(cls, value: Any) -> ApplyTo:
        return _APPLY_TO_FROM_STR.get(str(value), cls.BOTH)

    def to_str(self) -> str:
        return _APPLY_TO_TO_STR.get(self, "both")


_APPLY_TO_FROM_STR: dict[str, ApplyTo] = {
    "file": ApplyTo.FILE,
    "dir": ApplyTo.DIR,
    "both": ApplyTo.BOTH,
}

_APPLY_TO_TO_STR: dict[ApplyTo, str] = {v: k for k, v in _APPLY_TO_FROM_STR.items()}
