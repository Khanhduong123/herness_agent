"""Harness Agent: A benchmark and execution harness for agents running via the agy CLI."""

from harness_agent.evaluator import (
    BaseEvaluator,
    CommandEvaluator,
    FileExistsEvaluator,
    PatchOnlyEvaluator,
    TextMatchEvaluator,
    ToolLockEvaluator,
)
from harness_agent.harness import AgentHarness
from harness_agent.models import (
    AgentRole,
    AgyConfig,
    CriticalityLevel,
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
from harness_agent.patch import (
    DisallowedFullFileOverwriteError,
    PatchHunk,
    PatchResult,
    ToolLockViolationError,
    apply_patch,
    apply_unified_diff,
    multi_replace_file_content,
    parse_unified_diff,
    validate_tool_call,
)
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
    "CriticalityLevel",
    "DisallowedFullFileOverwriteError",
    "EvalReport",
    "FileExistsEvaluator",
    "FunctionSpec",
    "OrchestrationPlan",
    "OrchestrationResult",
    "PatchHunk",
    "PatchOnlyEvaluator",
    "PatchResult",
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
    "ToolLockEvaluator",
    "ToolLockViolationError",
    "WorkerAgentConfig",
    "apply_patch",
    "apply_unified_diff",
    "multi_replace_file_content",
    "parse_unified_diff",
    "validate_tool_call",
]
