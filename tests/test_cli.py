from syzygy.cli import main


def test_dev_deck_lists_78_cards(capsys):
    exit_code = main(["dev", "deck"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "the_fool" in out
    assert "78 cards total." in out


def test_doctor_exits_zero(capsys):
    exit_code = main(["doctor"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "deck    OK" in out


def test_help_flag_prints_usage(capsys):
    import pytest

    # `syzygy` with no arguments launches the TUI (DESIGN.md section 20),
    # so usage is reached through --help rather than through no arguments.
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert "tui" in out


def test_unknown_subcommand_group_prints_help(capsys):
    exit_code = main(["dev"])
    assert exit_code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_version_flag(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
