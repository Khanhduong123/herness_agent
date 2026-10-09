"""Token pricing calculator and run token logger for audit benchmarks."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from harness_agent.core.models import RunResult


class ModelPricing:
    """Token pricing calculator based on model catalog rates."""

    # Default rates per 1,000,000 tokens (USD)
    RATES: Dict[str, Dict[str, float]] = {
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "cached": 0.01875},
        "gemini-1.5-pro": {"input": 3.50, "output": 10.50, "cached": 0.875},
        "gpt-4o": {"input": 2.50, "output": 10.00, "cached": 1.25},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached": 0.075},
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00, "cached": 0.30},
        "default": {"input": 1.00, "output": 3.00, "cached": 0.25},
    }

    @classmethod
    def get_model_rates(cls, model: Optional[str]) -> Dict[str, float]:
        """Resolves pricing rates for a given model identifier."""
        if not model:
            return cls.RATES["default"]

        normalized = model.strip().lower()
        if normalized in cls.RATES:
            return cls.RATES[normalized]

        for known_model, rates in cls.RATES.items():
            if known_model != "default" and known_model in normalized:
                return rates

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


class TokenLogger:
    """Records agent token consumption and costs to log.csv and computes audit metrics."""

    DEFAULT_CSV_PATH = Path(".runs/log.csv")
    CSV_HEADERS = [
        "timestamp",
        "task_id",
        "role",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "duration_seconds",
        "success",
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
        model_str = model or "default"

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

        row_data = {
            "timestamp": timestamp,
            "task_id": result.task_id,
            "role": role_str,
            "model": model_str,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cached_tokens": result.cached_tokens,
            "total_tokens": result.total_tokens,
            "estimated_cost_usd": f"{result.estimated_cost_usd:.6f}",
            "duration_seconds": f"{result.duration_seconds:.2f}",
            "success": str(result.success),
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
        full_price_cached_cost = 0.0
        discounted_cached_cost = 0.0

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

                rates = ModelPricing.get_model_rates(model_str)
                full_price_cached_cost += (cached / 1_000_000.0) * rates.get("input", 1.00)
                discounted_cached_cost += (cached / 1_000_000.0) * rates.get("cached", 0.25)

        summary["total_cost_usd"] = round(total_cost, 6)
        savings = max(0.0, full_price_cached_cost - discounted_cached_cost)
        summary["estimated_savings_usd"] = round(savings, 6)

        return summary
