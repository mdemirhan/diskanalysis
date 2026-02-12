from __future__ import annotations

from enum import Enum


class NodeKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"


class InsightCategory(str, Enum):
    TEMP = "temp"
    CACHE = "cache"
    LARGE_FILE = "large_file"
    LARGE_DIRECTORY = "large_directory"
    OLD_FILE = "old_file"
    BUILD_ARTIFACT = "build_artifact"
    CUSTOM = "custom"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
