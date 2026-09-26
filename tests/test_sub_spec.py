"""Unit tests for SDLC Sub-Spec model and prompt rendering."""

from harness_agent.models import (
    AgentRole,
    AgyConfig,
    CriticalityLevel,
    FunctionSpec,
    OrchestrationPlan,
    RiskLevel,
    SpecStatus,
    SubSpec,
    SubTask,
    TestCaseSpec,
    WorkerAgentConfig,
)
from harness_agent.orchestrator import AgentOrchestrator


def test_sub_spec_model_creation():
    fn = FunctionSpec(
        name="calculate_metrics",
        signature="def calculate_metrics(values: List[float]) -> Dict[str, float]:",
        description="Calculates mean and standard deviation.",
        parameters={"values": "List of floating point numbers"},
        return_type="Dict[str, float]",
        raises=["ValueError"],
    )

    tc = TestCaseSpec(
        id="TC-01",
        description="Calculate metrics on non-empty list",
        input_data={"values": [1.0, 2.0, 3.0]},
        expected_output={"mean": 2.0},
    )

    spec = SubSpec(
        criticality=CriticalityLevel.CRITICAL,
        risk_level=RiskLevel.MEDIUM,
        blast_radius="Affects evaluation reporting",
        risk_mitigation="Fallback to zero on empty input",
        status=SpecStatus.APPROVED,
        functions=[fn],
        test_cases=[tc],
        acceptance_criteria=["Must pass with 100% test coverage"],
    )

    subtask = SubTask(
        id="calc_task",
        name="Calculate Metrics",
        role=AgentRole.CODER,
        instruction="Implement calculate_metrics function",
        spec=spec,
    )

    assert subtask.spec is not None
    assert subtask.spec.criticality == CriticalityLevel.CRITICAL
    assert subtask.spec.risk_level == RiskLevel.MEDIUM
    assert len(subtask.spec.functions) == 1
    assert subtask.spec.functions[0].name == "calculate_metrics"
    assert len(subtask.spec.test_cases) == 1
    assert subtask.spec.test_cases[0].id == "TC-01"


def test_sub_spec_prompt_rendering():
    fn = FunctionSpec(
        name="parse_event",
        signature="def parse_event(raw: str) -> Dict[str, Any]:",
        description="Parse raw stream JSON",
        raises=["json.JSONDecodeError"],
    )

    tc = TestCaseSpec(
        id="TC-02",
        description="Handle invalid JSON safely",
        input_data={"raw": "invalid"},
        expected_exception="json.JSONDecodeError",
    )

    spec = SubSpec(
        criticality=CriticalityLevel.HIGH,
        risk_level=RiskLevel.HIGH,
        blast_radius="src/harness_agent/runner.py",
        risk_mitigation="Wrap json.loads in try/except",
        functions=[fn],
        test_cases=[tc],
        acceptance_criteria=["Black 100 cols", "flake8 pass"],
    )

    subtask = SubTask(
        id="parse_task",
        name="Parse Stream Event",
        role=AgentRole.CODER,
        instruction="Implement parse_event",
        spec=spec,
    )

    plan = OrchestrationPlan(
        plan_id="plan_spec_test",
        goal="Verify sub-spec rendering",
        tasks=[subtask],
    )

    orchestrator = AgentOrchestrator(base_config=AgyConfig())
    worker = WorkerAgentConfig(role=AgentRole.CODER, name="coder-agent")
    prompt = orchestrator._build_worker_prompt(
        plan=plan, subtask=subtask, worker=worker, task_results={}
    )

    # Assert all sub-spec requirements appear in worker prompt
    assert "## Technical Sub-Specification (SDLC Contract):" in prompt
    assert "Criticality: HIGH" in prompt
    assert "Risk Level: HIGH" in prompt
    assert "Blast Radius: src/harness_agent/runner.py" in prompt
    assert "Risk Mitigation: Wrap json.loads in try/except" in prompt
    assert "def parse_event(raw: str) -> Dict[str, Any]:" in prompt
    assert "[TC-02] Handle invalid JSON safely" in prompt
    assert "Expected Exception: json.JSONDecodeError" in prompt
    assert "Black 100 cols" in prompt
