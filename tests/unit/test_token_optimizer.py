"""Unit tests for token optimizer module."""

import os

import pytest

from harness_agent.core.token_optimizer import strip_ansi, strip_emojis, truncate_output


def test_strip_ansi_basic():
    """TC-01: Strip ANSI escape codes from styled terminal output."""
    raw = "\x1b[31mError\x1b[0m"
    assert strip_ansi(raw) == "Error"


def test_strip_ansi_complex():
    """Strip 256-color, cursor movements, and VT100 escape sequences."""
    raw = "\x1b[38;5;82mGreen\x1b[0m text with \x1b[2Jclear screen \x1b[1;34mBold Blue\x1b[0m"
    assert strip_ansi(raw) == "Green text with clear screen Bold Blue"


def test_strip_emojis():
    """Strip various Unicode emoji icons, pictographs, dingbats, and symbols."""
    raw = "Status: OK! Rocket, Lightbulb, Warning, Cross, Check"
    emojis = " \U0001F680 \U0001F4A1 \U000026A0 \U0000274C \U00002705"
    assert strip_emojis(raw + emojis) == raw + "     "


def test_truncate_output_empty():
    """Edge Case 1: Empty or whitespace string."""
    assert truncate_output("") == ""
    assert truncate_output(None) == ""


def test_truncate_output_under_threshold():
    """TC-02: Pass through under threshold (50 lines under default 60)."""
    lines = [f"line {i}" for i in range(50)]
    text = "\n".join(lines)
    res = truncate_output(text, max_lines=60)
    assert res == text
    assert "[..." not in res


def test_truncate_output_exact_threshold():
    """Edge Case 2: Output exactly equal to threshold (60 lines)."""
    lines = [f"line {i}" for i in range(60)]
    text = "\n".join(lines)
    res = truncate_output(text, max_lines=60)
    assert res == text
    assert "[..." not in res


def test_truncate_output_over_threshold():
    """TC-03: Truncate output when exceeding max_lines."""
    lines = [f"line {i}" for i in range(100)]
    text = "\n".join(lines)
    res = truncate_output(text, max_lines=60, head_lines=20, tail_lines=40)

    assert "[... 40 lines omitted to conserve tokens. Full output: not saved ...]" in res
    res_lines = res.splitlines()
    assert res_lines[0] == "line 0"
    assert res_lines[19] == "line 19"
    assert res_lines[-40] == "line 60"
    assert res_lines[-1] == "line 99"


def test_truncate_output_crlf_and_lf():
    """Edge Case 3: Mixed CRLF and LF lines."""
    mixed_text = "line 0\r\nline 1\nline 2\r\nline 3"
    assert (
        truncate_output(mixed_text, max_lines=10, head_lines=2, tail_lines=2)
        == "line 0\nline 1\nline 2\nline 3"
    )


def test_truncate_output_invalid_threshold():
    """Edge Case 4: Invalid threshold arguments where head + tail > max_lines."""
    with pytest.raises(ValueError):
        truncate_output("some text\nsecond line", max_lines=10, head_lines=6, tail_lines=5)

    with pytest.raises(ValueError):
        truncate_output("some text", max_lines=-1)


def test_truncate_output_spillover(tmp_path):
    """TC-04: Spillover file saving when exceeding threshold."""
    lines = [f"line {i}" for i in range(100)]
    text = "\n".join(lines)
    spillover_file = str(tmp_path / "spillover" / "full_output.log")

    res = truncate_output(
        text,
        max_lines=60,
        head_lines=20,
        tail_lines=40,
        spillover_path=spillover_file,
    )

    assert f"Full output: {spillover_file}" in res
    assert os.path.exists(spillover_file)
    with open(spillover_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == text
