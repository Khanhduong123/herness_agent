"""Harness Agent: A benchmark and execution harness for agents running via the agy CLI."""

from harness_agent.evaluator import (
    BaseEvaluator,
    CommandEvaluator,
    FileExistsEvaluator,
    TextMatchEvaluator,
)
from harness_agent.harness import AgentHarness
from harness_agent.models import AgyConfig, EvalReport, RunResult, Task
from harness_agent.runner import AgyRunner

__version__ = "0.1.0"

__all__ = [
    "AgyConfig",
    "AgyRunner",
    "AgentHarness",
    "BaseEvaluator",
    "CommandEvaluator",
    "EvalReport",
    "FileExistsEvaluator",
    "RunResult",
    "Task",
    "TextMatchEvaluator",
]
