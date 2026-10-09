"""Token pricing calculator and run token logger for audit benchmarks."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from harness_agent.core.models import RunResult


def get_active_model(override: Optional[str] = None) -> str:
    """Resolve active AI model identifier from override, environment, or default catalog."""
    if override and override.strip():
        return override.strip()

    env_model = (
        os.environ.get("AGY_MODEL") or os.environ.get("HERNESS_MODEL") or os.environ.get("MODEL")
    )
    if env_model and env_model.strip():
        return env_model.strip()

    return "gemini-3.8-flash"


class ModelPricing:
    """Token pricing calculator based on model catalog rates."""

    # Default rates per 1,000,000 tokens (USD)
    RATES: Dict[str, Dict[str, float]] = {
        "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
        "gemini-3.7-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
        "gemini-3.6-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
        "gemini-3.1-pro": {"input": 1.25, "output": 5.00, "cached": 0.3125},
        "gemini-2.5-pro": {"input": 1.25, "output": 5.00, "cached": 0.3125},
        "gemini-2.5-flash": {"input": 0.075, "output": 0.30, "cached": 0.01875},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "cached": 0.01875},
        "gemini-1.5-pro": {"input": 3.50, "output": 10.50, "cached": 0.875},
        "claude-3-5-haiku": {"input": 0.80, "output": 4.00, "cached": 0.08},
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00, "cached": 0.30},
        "gpt-4o": {"input": 2.50, "output": 10.00, "cached": 1.25},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached": 0.075},
        "default": {"input": 1.00, "output": 3.00, "cached": 0.25},
    }

    @classmethod
    def get_model_rates(cls, model: Optional[str]) -> Dict[str, float]:
        """Resolves pricing rates for a given model identifier."""
        if not model:
            model = get_active_model()

        normalized = model.strip().lower()
        if normalized in cls.RATES:
            return cls.RATES[normalized]

        for known_model, rates in cls.RATES.items():
            if known_model != "default" and known_model in normalized:
                return rates

        # Smart Family Fallback
        if "flash" in normalized:
            if "2.5" in normalized or "1.5" in normalized:
                return {"input": 0.075, "output": 0.30, "cached": 0.01875}
            return {"input": 0.75, "output": 3.75, "cached": 0.075}
        if "pro" in normalized:
            if "1.5" in normalized:
                return {"input": 3.50, "output": 10.50, "cached": 0.875}
            return {"input": 1.25, "output": 5.00, "cached": 0.3125}
        if "mini" in normalized:
            return {"input": 0.15, "output": 0.60, "cached": 0.075}
        if "sonnet" in normalized:
            return {"input": 3.00, "output": 15.00, "cached": 0.30}
        if "haiku" in normalized:
            return {"input": 0.80, "output": 4.00, "cached": 0.08}

        return cls.RATES["default"]

    @classmethod
    def calculate_cost(
        cls,
        model: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> float:
        """Calculates estimated cost in USD based on model rates.

        Prompt tokens count non-cached prompt tokens or standard input tokens.
        If cached_tokens are provided:
            non-cached input tokens = max(0, prompt_tokens - cached_tokens).
        """
        rates = cls.get_model_rates(model)
        non_cached_prompt = max(0, prompt_tokens - cached_tokens)

        input_cost = (non_cached_prompt / 1_000_000.0) * rates.get("input", 1.00)
        cached_cost = (cached_tokens / 1_000_000.0) * rates.get("cached", 0.25)
        output_cost = (completion_tokens / 1_000_000.0) * rates.get("output", 3.00)

        total_cost = input_cost + cached_cost + output_cost
        return round(total_cost, 6)

    @classmethod
    def calculate_savings(
        cls,
        model: Optional[str],
        cached_tokens: int,
        truncated_output_tokens: int = 0,
    ) -> float:
        """Calculates total financial savings in USD from cache hits and output truncation.

        Formula:
        total_savings_usd = [cached_tokens * (standard_input_rate - cached_input_rate) / 1_000_000]
                          + [truncated_output_tokens * output_rate / 1_000_000]
        """
        rates = cls.get_model_rates(model)
        standard_input_rate = rates.get("input", 1.00)
        cached_input_rate = rates.get("cached", 0.25)
        output_rate = rates.get("output", 3.00)

        cache_savings = (cached_tokens * (standard_input_rate - cached_input_rate)) / 1_000_000.0
        truncation_savings = (truncated_output_tokens * output_rate) / 1_000_000.0

        total_savings = cache_savings + truncation_savings
        return round(total_savings, 6)


class TokenLogger:
    """Records agent token consumption and costs to log.csv and computes audit metrics."""

    DEFAULT_CSV_PATH = Path(".runs/log.csv")
    CSV_HEADERS = [
        "timestamp",
        "plan_id",
        "task_id",
        "role",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "total_tokens",
        "truncated_output_tokens",
        "estimated_cost_usd",
        "total_savings_usd",
        "duration_seconds",
        "status",
    ]

    @classmethod
    def log_run(
        cls,
        result: RunResult,
        role: Optional[str] = None,
        model: Optional[str] = None,
        csv_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Appends a task run token metric and financial cost row to log.csv."""
        target_path = Path(csv_path) if csv_path is not None else cls.DEFAULT_CSV_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        role_str = role or "coder"
        model_str = model if (model and model.strip()) else get_active_model()

        # Update result's estimated cost if not already computed or if zero
        if result.estimated_cost_usd == 0.0 and (
            result.prompt_tokens > 0 or result.completion_tokens > 0 or result.cached_tokens > 0
        ):
            result.estimated_cost_usd = ModelPricing.calculate_cost(
                model=model_str,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cached_tokens=result.cached_tokens,
            )

        if result.total_tokens == 0:
            result.total_tokens = result.prompt_tokens + result.completion_tokens

        file_exists = target_path.exists()
        is_empty = file_exists and target_path.stat().st_size == 0

        timestamp = datetime.now(timezone.utc).isoformat()
        plan_id_str = getattr(result, "plan_id", None) or "default_plan"
        total_savings_usd = ModelPricing.calculate_savings(
            model=model_str,
            cached_tokens=result.cached_tokens,
            truncated_output_tokens=getattr(result, "truncated_output_tokens", 0),
        )

        row_data = {
            "timestamp": timestamp,
            "plan_id": plan_id_str,
            "task_id": result.task_id,
            "role": role_str,
            "model": model_str,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cached_tokens": result.cached_tokens,
            "total_tokens": result.total_tokens,
            "truncated_output_tokens": getattr(result, "truncated_output_tokens", 0),
            "estimated_cost_usd": f"{result.estimated_cost_usd:.6f}",
            "total_savings_usd": f"{total_savings_usd:.6f}",
            "duration_seconds": f"{result.duration_seconds:.2f}",
            "status": "COMPLETED" if result.success else "FAILED",
        }

        with open(target_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cls.CSV_HEADERS)
            if not file_exists or is_empty:
                writer.writeheader()
            writer.writerow(row_data)

        return target_path

    @classmethod
    def log_task_summary(
        cls,
        task_id: str,
        plan_id: Optional[str] = None,
        role: Optional[str] = None,
        model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        total_tokens: Optional[int] = None,
        truncated_output_tokens: int = 0,
        duration_seconds: float = 0.0,
        status: str = "COMPLETED",
        csv_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Appends an aggregated end-to-end task telemetry row to log.csv."""
        target_path = Path(csv_path) if csv_path is not None else cls.DEFAULT_CSV_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        plan_id_str = plan_id or "default_plan"
        role_str = role or "coder"
        model_str = model if (model and model.strip()) else get_active_model()

        calc_total_tokens = (
            total_tokens if total_tokens is not None else (prompt_tokens + completion_tokens)
        )
        cost = ModelPricing.calculate_cost(
            model=model_str,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )
        savings = ModelPricing.calculate_savings(
            model=model_str,
            cached_tokens=cached_tokens,
            truncated_output_tokens=truncated_output_tokens,
        )

        file_exists = target_path.exists()
        is_empty = file_exists and target_path.stat().st_size == 0
        timestamp = datetime.now(timezone.utc).isoformat()

        row_data = {
            "timestamp": timestamp,
            "plan_id": plan_id_str,
            "task_id": task_id,
            "role": role_str,
            "model": model_str,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": calc_total_tokens,
            "truncated_output_tokens": truncated_output_tokens,
            "estimated_cost_usd": f"{cost:.6f}",
            "total_savings_usd": f"{savings:.6f}",
            "duration_seconds": f"{duration_seconds:.2f}",
            "status": status,
        }

        with open(target_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cls.CSV_HEADERS)
            if not file_exists or is_empty:
                writer.writeheader()
            writer.writerow(row_data)

        return target_path

    @classmethod
    def compute_summary(
        cls,
        csv_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Calculates total prompt, completion, cached tokens, and total cost in USD."""
        target_path = Path(csv_path) if csv_path is not None else cls.DEFAULT_CSV_PATH

        summary: Dict[str, Any] = {
            "total_runs": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "estimated_savings_usd": 0.0,
        }

        if not target_path.exists() or target_path.stat().st_size == 0:
            return summary

        total_cost = 0.0
        total_savings = 0.0

        with open(target_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                summary["total_runs"] += 1
                pt = int(row.get("prompt_tokens") or 0)
                ct = int(row.get("completion_tokens") or 0)
                cached = int(row.get("cached_tokens") or 0)
                tt = int(row.get("total_tokens") or (pt + ct))
                cost = float(row.get("estimated_cost_usd") or 0.0)
                model_str = row.get("model") or "default"

                summary["prompt_tokens"] += pt
                summary["completion_tokens"] += ct
                summary["cached_tokens"] += cached
                summary["total_tokens"] += tt
                total_cost += cost

                if "total_savings_usd" in row and row["total_savings_usd"] != "":
                    total_savings += float(row["total_savings_usd"])
                else:
                    trunc = int(row.get("truncated_output_tokens") or 0)
                    total_savings += ModelPricing.calculate_savings(
                        model=model_str,
                        cached_tokens=cached,
                        truncated_output_tokens=trunc,
                    )

        summary["total_cost_usd"] = round(total_cost, 6)
        summary["estimated_savings_usd"] = round(total_savings, 6)

        return summary
