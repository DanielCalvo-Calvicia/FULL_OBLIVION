from collections.abc import Iterator

import pytest

from domain.console import configure_logger, console_log, get_logger


@pytest.fixture(autouse=True)
def reset_logger_environment() -> Iterator[None]:
    configure_logger("development")
    yield
    configure_logger("development")


def test_development_logger_shows_trace(capsys) -> None:
    configure_logger("development")

    get_logger("test").trace("visible")

    assert "[development] [trace] [test] visible" in capsys.readouterr().out


def test_staging_logger_hides_info_but_shows_warn(capsys) -> None:
    configure_logger("staging")

    logger = get_logger("test")
    logger.info("hidden")
    logger.warn("visible")

    output = capsys.readouterr().out
    assert "hidden" not in output
    assert "[staging] [warn] [test] visible" in output


def test_production_logger_shows_critical_only(capsys) -> None:
    configure_logger("production")

    logger = get_logger("test")
    logger.error("hidden")
    logger.critical("visible")

    output = capsys.readouterr().out
    assert "hidden" not in output
    assert "[production] [critical] [test] visible" in output


def test_forced_console_log_is_visible_in_production(capsys) -> None:
    configure_logger("production")

    console_log("internal-stream", "visible", always=True)

    assert "[production] [info] [internal-stream] visible" in capsys.readouterr().out


def test_console_log_can_surround_message_with_blank_lines(capsys) -> None:
    configure_logger("development")

    console_log("stream", "closed", blank_lines=2)

    output = capsys.readouterr().out
    assert output.startswith("\n\n[")
    assert "[development] [info] [stream] closed" in output
    assert output.endswith("\n\n")
