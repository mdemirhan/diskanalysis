from dux.services.formatting import format_bytes


def test_format_bytes_outputs() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(1) == "1 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024) == "1.0 MB"
