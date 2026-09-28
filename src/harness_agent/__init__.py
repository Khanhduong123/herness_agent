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
    UntrustedSource,
    WorkerAgentConfig,
)
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.researcher import (
    extract_text_from_html,
    fetch_web_page,
    read_external_file,
    read_external_source,
    read_issue_tracker,
    read_pdf_document,
)
from harness_agent.runner import AgyRunner
from harness_agent.security import (
    UNTRUSTED_SOURCE_INSTRUCTION,
    detect_injection_risk,
    extract_untrusted_content,
    sanitize_delimiters,
    wrap_untrusted_content,
)

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
    "UNTRUSTED_SOURCE_INSTRUCTION",
    "UntrustedSource",
    "WorkerAgentConfig",
    "detect_injection_risk",
    "extract_text_from_html",
    "extract_untrusted_content",
    "fetch_web_page",
    "read_external_file",
    "read_external_source",
    "read_issue_tracker",
    "read_pdf_document",
    "sanitize_delimiters",
    "wrap_untrusted_content",
]
