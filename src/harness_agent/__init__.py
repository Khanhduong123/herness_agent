"""Harness Agent: A benchmark and execution harness for agents running via the agy CLI."""

from harness_agent.critics import (
    aggregate_critic_feedback,
    build_critic_prompt,
    detect_performance_issues,
    detect_requirement_issues,
    detect_security_issues,
    dispatch_parallel_critics,
)
from harness_agent.evaluator import (
    BaseEvaluator,
    CommandEvaluator,
    FileExistsEvaluator,
    TextMatchEvaluator,
)
from harness_agent.harness import AgentHarness
from harness_agent.models import (
    AgentRole,
    AggregatedCriticReview,
    AgyConfig,
    CriticalityLevel,
    CriticFeedback,
    EvalReport,
    FunctionSpec,
    OrchestrationPlan,
    OrchestrationResult,
    RiskLevel,
    RunResult,
    SpecStatus,
    SubSpec,
    SubTask,
    Task,
    TaskCheck,
    TaskStatus,
    TestCaseSpec,
    WorkerAgentConfig,
)
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.runner import AgyRunner

__version__ = "0.1.0"

__all__ = [
    "AgentHarness",
    "AgentOrchestrator",
    "AgentRole",
    "AggregatedCriticReview",
    "AgyConfig",
    "AgyRunner",
    "BaseEvaluator",
    "CommandEvaluator",
    "CriticFeedback",
    "CriticalityLevel",
    "EvalReport",
    "FileExistsEvaluator",
    "FunctionSpec",
    "OrchestrationPlan",
    "OrchestrationResult",
    "RiskLevel",
    "RunResult",
    "SpecStatus",
    "SubSpec",
    "SubTask",
    "Task",
    "TaskCheck",
    "TaskStatus",
    "TestCaseSpec",
    "TextMatchEvaluator",
    "WorkerAgentConfig",
    "aggregate_critic_feedback",
    "build_critic_prompt",
    "detect_performance_issues",
    "detect_requirement_issues",
    "detect_security_issues",
    "dispatch_parallel_critics",
]
