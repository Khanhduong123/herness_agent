"""Unit tests for ModelPricing and TokenLogger in harness_agent.core.token_logger."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from harness_agent.core.models import RunResult
from harness_agent.core.token_logger import ModelPricing, TokenLogger, get_active_model


def test_model_pricing_rates():
    """Verify ModelPricing rate resolution for exact and partial match."""
    flash_rates = ModelPricing.get_model_rates("gemini-1.5-flash")
    assert flash_rates["input"] == 0.075
    assert flash_rates["output"] == 0.30
    assert flash_rates["cached"] == 0.01875

    # Partial match
    partial_rates = ModelPricing.get_model_rates("models/gemini-1.5-pro-latest")
    assert partial_rates["input"] == 3.50

    # Default fallback
    default_rates = ModelPricing.get_model_rates("unknown-future-model")
    assert default_rates["input"] == 1.00


def test_model_pricing_calculate_cost():
    """Verify cost calculation with cached discount."""
    # 1M prompt (including 500k cached) and 1M completion on gemini-1.5-flash
    # Non-cached prompt: 500k = $0.0375
    # Cached prompt: 500k = $0.009375
    # Completion: 1M = $0.30
    # Total = 0.346875
    cost = ModelPricing.calculate_cost(
        model="gemini-1.5-flash",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        cached_tokens=500_000,
    )
    assert pytest.approx(cost, rel=1e-5) == 0.346875


def test_model_pricing_calculate_savings():
    """TC-01: Verify user savings formula calculation with cached and truncated tokens.

    total_savings_usd = [cached_tokens * (standard_input_rate - cached_input_rate) / 1_000_000]
                      + [truncated_output_tokens * output_rate / 1_000_000]

    On gemini-1.5-flash:
    standard_input_rate = 0.075, cached_input_rate = 0.01875, output_rate = 0.30
    cached=100_000 -> 100_000 * (0.075 - 0.01875) / 1_000_000
                   = 100_000 * 0.05625 / 1_000_000 = 0.005625
    truncated=5_000 -> 5_000 * 0.30 / 1_000_000 = 0.0015
    total = 0.007125
    """
    savings = ModelPricing.calculate_savings(
        model="gemini-1.5-flash",
        cached_tokens=100_000,
        truncated_output_tokens=5_000,
    )
    assert pytest.approx(savings, rel=1e-5) == 0.007125

    # Zero truncated tokens
    savings_no_trunc = ModelPricing.calculate_savings(
        model="gemini-1.5-flash",
        cached_tokens=100_000,
        truncated_output_tokens=0,
    )
    assert pytest.approx(savings_no_trunc, rel=1e-5) == 0.005625

    # Fallback default model
    default_savings = ModelPricing.calculate_savings(
        model="unknown-model",
        cached_tokens=1_000_000,
        truncated_output_tokens=1_000_000,
    )
    # Default rates: input=1.00, cached=0.25, output=3.00
    # cache: 1.00 - 0.25 = 0.75
    # output: 3.00
    # total = 3.75
    assert pytest.approx(default_savings, rel=1e-5) == 3.75


def test_token_logger_log_task_summary(tmp_path: Path):
    """TC-02: Verify log_task_summary writes complete row with cost and savings."""
    csv_file = tmp_path / "task_summary.csv"
    TokenLogger.log_task_summary(
        task_id="subtask_08",
        plan_id="plan_token_opt",
        role="coder",
        model="gemini-1.5-flash",
        prompt_tokens=50_000,
        completion_tokens=2_000,
        cached_tokens=10_000,
        truncated_output_tokens=1_000,
        duration_seconds=12.5,
        status="COMPLETED",
        csv_path=csv_file,
    )

    assert csv_file.exists()
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert row["plan_id"] == "plan_token_opt"
        assert row["task_id"] == "subtask_08"
        assert row["role"] == "coder"
        assert row["model"] == "gemini-1.5-flash"
        assert row["prompt_tokens"] == "50000"
        assert row["completion_tokens"] == "2000"
        assert row["cached_tokens"] == "10000"
        assert row["total_tokens"] == "52000"
        assert row["truncated_output_tokens"] == "1000"
        assert float(row["estimated_cost_usd"]) > 0.0
        assert float(row["total_savings_usd"]) > 0.0
        assert row["duration_seconds"] == "12.50"
        assert row["status"] == "COMPLETED"


def test_token_logger_initialization_and_header(tmp_path: Path):
    """TC-01: Verify new log.csv creation with header and 1 data row."""
    csv_file = tmp_path / "runs" / "log.csv"
    res = RunResult(
        task_id="task_tc01",
        success=True,
        exit_code=0,
        duration_seconds=1.5,
        prompt_tokens=1000,
        completion_tokens=200,
        cached_tokens=400,
    )

    logged_path = TokenLogger.log_run(
        result=res,
        role="coder",
        model="gemini-1.5-flash",
        csv_path=csv_file,
    )

    assert logged_path == csv_file
    assert csv_file.exists()

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 2  # Header + 1 row
        header = reader[0]
        assert "plan_id" in header
        assert "task_id" in header
        assert "prompt_tokens" in header
        assert "estimated_cost_usd" in header
        assert "total_savings_usd" in header
        row = reader[1]
        assert row[1] == "default_plan"
        assert row[2] == "task_tc01"
        assert row[3] == "coder"
        assert row[4] == "gemini-1.5-flash"
        assert row[5] == "1000"
        assert row[6] == "200"
        assert row[7] == "400"
        assert row[8] == "1200"
        assert row[9] == "0"
        assert float(row[10]) > 0.0
        assert float(row[11]) > 0.0


def test_token_logger_consecutive_appends(tmp_path: Path):
    """TC-02: Verify multiple appends without duplicating header."""
    csv_file = tmp_path / "log.csv"
    for i in range(3):
        res = RunResult(
            task_id=f"task_{i}",
            success=True,
            exit_code=0,
            duration_seconds=2.0,
            prompt_tokens=100 * (i + 1),
            completion_tokens=50 * (i + 1),
        )
        TokenLogger.log_run(result=res, csv_path=csv_file)

    with open(csv_file, mode="r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 4  # 1 header + 3 rows


def test_token_logger_compute_summary(tmp_path: Path):
    """TC-03: Metric summary aggregation."""
    csv_file = tmp_path / "summary_log.csv"
    # Empty summary check
    empty_summary = TokenLogger.compute_summary(csv_file)
    assert empty_summary["total_runs"] == 0
    assert empty_summary["prompt_tokens"] == 0

    # Log 3 tasks
    for i in range(3):
        res = RunResult(
            task_id=f"task_sum_{i}",
            success=True,
            exit_code=0,
            duration_seconds=1.0,
            prompt_tokens=1000,
            completion_tokens=500,
            cached_tokens=200,
        )
        TokenLogger.log_run(
            result=res,
            role="coder",
            model="gemini-1.5-flash",
            csv_path=csv_file,
        )

    summary = TokenLogger.compute_summary(csv_file)
    assert summary["total_runs"] == 3
    assert summary["prompt_tokens"] == 3000
    assert summary["completion_tokens"] == 1500
    assert summary["cached_tokens"] == 600
    assert summary["total_tokens"] == 4500
    assert summary["total_cost_usd"] > 0
    assert summary["estimated_savings_usd"] > 0


def test_extract_stream_data_nested_step_update_and_cache_read_tokens():
    """TC-01: Verify nested step_update usage parsing and cache_read_tokens extraction."""
    from harness_agent.core.runner import AgyRunner

    runner = AgyRunner()
    token_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
    }
    event = {
        "event": "step_update",
        "step_update": {
            "usage": {
                "input_tokens": 2860,
                "output_tokens": 12,
                "cache_read_tokens": 16518,
            }
        },
    }

    runner._extract_stream_data(
        event=event,
        text_pieces=[],
        tool_calls=[],
        token_usage=token_usage,
    )

    assert token_usage["prompt_tokens"] == 2860
    assert token_usage["completion_tokens"] == 12
    assert token_usage["cached_tokens"] == 16518


def test_extract_stream_data_nested_result_usage():
    """TC-02: Verify nested result usage parsing."""
    from harness_agent.core.runner import AgyRunner

    runner = AgyRunner()
    token_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
    }
    event = {
        "event": "result",
        "result": {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
            }
        },
    }

    runner._extract_stream_data(
        event=event,
        text_pieces=[],
        tool_calls=[],
        token_usage=token_usage,
    )

    assert token_usage["prompt_tokens"] == 100
    assert token_usage["completion_tokens"] == 50
    assert token_usage["cached_tokens"] == 0


def test_extract_stream_data_edge_cases():
    """Verify edge cases: missing usage, non-integer values, accumulation max."""
    from harness_agent.core.runner import AgyRunner

    runner = AgyRunner()
    token_usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cached_tokens": 2,
    }

    # Missing usage - should not fail or decrease
    runner._extract_stream_data(
        event={"event": "ping"},
        text_pieces=[],
        tool_calls=[],
        token_usage=token_usage,
    )
    assert token_usage["prompt_tokens"] == 10

    # Non-integer values in usage
    invalid_event = {
        "usage": {
            "prompt_tokens": "invalid_num",
            "completion_tokens": None,
            "cache_read_tokens": "not_an_int",
        }
    }
    runner._extract_stream_data(
        event=invalid_event,
        text_pieces=[],
        tool_calls=[],
        token_usage=token_usage,
    )
    assert token_usage["prompt_tokens"] == 10
    assert token_usage["completion_tokens"] == 5
    assert token_usage["cached_tokens"] == 2

    # Multiple events update to maximum observed
    higher_event = {
        "step_update": {
            "token_usage": {
                "input_tokens": 500,
                "output_tokens": 300,
                "cache_read_tokens": 150,
            }
        }
    }
    runner._extract_stream_data(
        event=higher_event,
        text_pieces=[],
        tool_calls=[],
        token_usage=token_usage,
    )
    assert token_usage["prompt_tokens"] == 500
    assert token_usage["completion_tokens"] == 300
    assert token_usage["cached_tokens"] == 150


def test_get_active_model_resolution(monkeypatch):
    """TC-01: get_active_model default, env override, and argument override."""
    monkeypatch.delenv("AGY_MODEL", raising=False)
    monkeypatch.delenv("HERNESS_MODEL", raising=False)
    monkeypatch.delenv("MODEL", raising=False)

    # Default catalog
    assert get_active_model() == "gemini-3.8-flash"

    # Override takes precedence
    assert get_active_model("claude-3-5-sonnet") == "claude-3-5-sonnet"

    # Environment variables
    monkeypatch.setenv("AGY_MODEL", "gpt-4o-mini")
    assert get_active_model() == "gpt-4o-mini"
    assert get_active_model("gemini-3.1-pro") == "gemini-3.1-pro"

    monkeypatch.delenv("AGY_MODEL", raising=False)
    monkeypatch.setenv("HERNESS_MODEL", "gemini-2.5-flash")
    assert get_active_model() == "gemini-2.5-flash"

    monkeypatch.delenv("HERNESS_MODEL", raising=False)
    monkeypatch.setenv("MODEL", "claude-3-5-haiku")
    assert get_active_model() == "claude-3-5-haiku"


def test_family_resolution_flash_and_pro():
    """TC-02 & TC-03: Smart family fallback for variants."""
    # Flash family (modern defaults to 0.75 / 3.75 / 0.075)
    flash_variant = ModelPricing.get_model_rates("gemini-3.8-flash-medium")
    assert flash_variant["input"] == 0.75
    assert flash_variant["output"] == 3.75
    assert flash_variant["cached"] == 0.075

    # Flash legacy family (1.5 / 2.5 returns 0.075 / 0.30 / 0.01875)
    flash_25_variant = ModelPricing.get_model_rates("gemini-2.5-flash-custom")
    assert flash_25_variant["input"] == 0.075
    assert flash_25_variant["output"] == 0.30
    assert flash_25_variant["cached"] == 0.01875

    # Pro family (modern defaults to 1.25 / 5.00 / 0.3125)
    pro_variant = ModelPricing.get_model_rates("gemini-3.1-pro-high")
    assert pro_variant["input"] == 1.25
    assert pro_variant["output"] == 5.00
    assert pro_variant["cached"] == 0.3125

    # Pro legacy family (1.5 returns 3.50 / 10.50 / 0.875)
    pro_15_variant = ModelPricing.get_model_rates("gemini-1.5-pro-custom")
    assert pro_15_variant["input"] == 3.50
    assert pro_15_variant["output"] == 10.50
    assert pro_15_variant["cached"] == 0.875

    # Additional families: mini, sonnet, haiku
    mini_variant = ModelPricing.get_model_rates("custom-mini-agent")
    assert mini_variant["input"] == 0.15

    sonnet_variant = ModelPricing.get_model_rates("claude-next-sonnet-v1")
    assert sonnet_variant["input"] == 3.00

    haiku_variant = ModelPricing.get_model_rates("claude-haiku-v2")
    assert haiku_variant["input"] == 0.80

    # Unrecognized model falls back to default rates
    unknown = ModelPricing.get_model_rates("unknown-llm-xyz")
    assert unknown == ModelPricing.RATES["default"]


def test_log_task_summary_defaults_to_active_model(tmp_path: Path, monkeypatch):
    """TC-04: log_task_summary defaults model to active model when model=None."""
    monkeypatch.setenv("AGY_MODEL", "gemini-3.8-flash")
    csv_file = tmp_path / "task_summary_model.csv"

    TokenLogger.log_task_summary(
        task_id="subtask_01_pricing",
        plan_id="plan_model_selection_and_pricing",
        model=None,
        prompt_tokens=1000,
        completion_tokens=200,
        csv_path=csv_file,
    )

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert row["model"] == "gemini-3.8-flash"
        assert row["model"] != "default"
