"""Harness Agent: A benchmark and execution harness for agents running via the agy CLI."""

from harness_agent.evaluator import (
    BaseEvaluator,
    CommandEvaluator,
    FileExistsEvaluator,
    TextMatchEvaluator,
)
from harness_agent.harness import AgentHarness
from harness_agent.models import (
    AgentRole,
    AgyConfig,
    EvalReport,
    OrchestrationPlan,
    OrchestrationResult,
    RunResult,
    SubTask,
    Task,
    TaskCheck,
    TaskStatus,
    WorkerAgentConfig,
)
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.runner import AgyRunner

__version__ = "0.1.0"

__all__ = [
    "AgentHarness",
    "AgentOrchestrator",
    "AgentRole",
    "AgyConfig",
    "AgyRunner",
    "BaseEvaluator",
    "CommandEvaluator",
    "EvalReport",
    "FileExistsEvaluator",
    "OrchestrationPlan",
    "OrchestrationResult",
    "RunResult",
    "SubTask",
    "Task",
    "TaskCheck",
    "TaskStatus",
    "TextMatchEvaluator",
    "WorkerAgentConfig",
]
