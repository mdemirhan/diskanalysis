from __future__ import annotations

import pytest

from dux.cli import app as cli_app


def test_interactive_is_the_default() -> None:
    assert cli_app._launch_interactive(
        interactive=False,
        non_interactive=False,
        focused_summary_requested=False,
    )


def test_non_interactive_flag_selects_summary() -> None:
    assert not cli_app._launch_interactive(
        interactive=False,
        non_interactive=True,
        focused_summary_requested=False,
    )


def test_focused_summary_flags_preserve_non_interactive_compatibility() -> None:
    assert not cli_app._launch_interactive(
        interactive=False,
        non_interactive=False,
        focused_summary_requested=True,
    )
    assert cli_app._launch_interactive(
        interactive=True,
        non_interactive=False,
        focused_summary_requested=True,
    )


def test_conflicting_interactive_modes_are_rejected() -> None:
    with pytest.raises(cli_app.typer.BadParameter):
        cli_app._launch_interactive(
            interactive=True,
            non_interactive=True,
            focused_summary_requested=False,
        )


def test_windows_platform_exits_with_not_implemented(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_app.sys, "platform", "win32")

    with pytest.raises(cli_app.typer.Exit) as exc_info:
        cli_app.run(sample_config=True)

    assert exc_info.value.exit_code == 1
    out = capsys.readouterr().out
    assert "Windows support is not implemented yet." in out
