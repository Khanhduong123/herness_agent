"""Unit tests for role-based and phased tool schema masking."""

import logging
from typing import Any, Dict, List

import pytest

from harness_agent.core.dispatch import filter_tools_for_role
from harness_agent.core.models import AgentRole


@pytest.fixture
def sample_toolset() -> List[Dict[str, Any]]:
    """Sample tool declarations including coding, review, pr, git, and custom tools."""
    return [
        {
            "name": "view_file",
            "description": "View contents of a file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
        {
            "name": "replace_file_content",
            "description": "Replace file content block.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
        {
            "name": "write_to_file",
            "description": "Write brand-new file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
        {
            "name": "run_command",
            "description": "Run shell commands.",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
        },
        {
            "name": "create_pull_request",
            "description": "Open PR on github.",
            "parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
        },
        {
            "name": "git_merge",
            "description": "Merge git branch directly.",
            "parameters": {"type": "object", "properties": {"branch": {"type": "string"}}},
        },
        {
            "name": "read_url_content",
            "description": "Fetch url content.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
        {
            "name": "search_web",
            "description": "Search the web.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
        {
            "name": "invoke_subagent",
            "description": "Spawn subagents.",
            "parameters": {"type": "object", "properties": {}},
        },
    ]


def test_tc01_coder_tool_filtering(sample_toolset):
    """TC-01: Coder role filtering should include edit/test tools and exclude
    PR/git/orchestrator tools.
    """
    filtered = filter_tools_for_role(sample_toolset, AgentRole.CODER)
    tool_names = [t["name"] for t in filtered]

    # Must contain coder tools
    assert "view_file" in tool_names
    assert "replace_file_content" in tool_names
    assert "write_to_file" in tool_names
    assert "run_command" in tool_names

    # Must exclude PR and direct git merge / subagent orchestration tools
    assert "create_pull_request" not in tool_names
    assert "git_merge" not in tool_names
    assert "invoke_subagent" not in tool_names
    assert "read_url_content" not in tool_names
    assert "search_web" not in tool_names


def test_tc02_critic_tool_filtering(sample_toolset):
    """TC-02: Critic role filtering should include read-only tools and exclude
    write/edit/mutation tools.
    """
    for critic_role in [
        AgentRole.REVIEWER,
        AgentRole.SECURITY_REVIEWER,
        AgentRole.PERFORMANCE_REVIEWER,
        AgentRole.REQUIREMENT_REVIEWER,
    ]:
        filtered = filter_tools_for_role(sample_toolset, critic_role)
        tool_names = [t["name"] for t in filtered]

        # Read-only tools must be included
        assert "view_file" in tool_names
        assert "read_url_content" in tool_names
        assert "search_web" in tool_names

        # File modification and command execution must be excluded
        assert "replace_file_content" not in tool_names
        assert "write_to_file" not in tool_names
        assert "run_command" not in tool_names
        assert "create_pull_request" not in tool_names
        assert "git_merge" not in tool_names
        assert "invoke_subagent" not in tool_names


def test_empty_tool_list():
    """Edge Case: Empty tool list returns empty list."""
    assert filter_tools_for_role([], AgentRole.CODER) == []
    assert filter_tools_for_role([], AgentRole.REVIEWER) == []


def test_unknown_or_custom_role(sample_toolset, caplog):
    """Edge Case: Unknown or custom role falls back to safe read-only default without crashing."""
    with caplog.at_level(logging.WARNING):
        filtered = filter_tools_for_role(sample_toolset, "unknown_custom_role")  # type: ignore

    tool_names = [t["name"] for t in filtered]
    # Safe default is read-only (REVIEWER)
    assert "view_file" in tool_names
    assert "replace_file_content" not in tool_names
    assert "write_to_file" not in tool_names
    assert "run_command" not in tool_names


def test_missing_or_malformed_tool_schemas(caplog):
    """Edge Case: Malformed tool schemas without names or non-dict elements are skipped cleanly."""
    malformed_tools = [
        {"name": "view_file"},
        {"no_name_field": "test"},
        {"name": None},
        {"name": 12345},
        "not_a_dict_schema",
        {"function": {"name": "run_command"}},  # OpenAI style schema supported
    ]

    with caplog.at_level(logging.WARNING):
        filtered = filter_tools_for_role(malformed_tools, AgentRole.CODER)  # type: ignore

    assert len(filtered) == 2
    assert filtered[0]["name"] == "view_file"
    assert filtered[1]["function"]["name"] == "run_command"


def test_orchestrator_tool_filtering(sample_toolset):
    """Orchestrator role has access to orchestration and execution tools."""
    filtered = filter_tools_for_role(sample_toolset, AgentRole.ORCHESTRATOR)
    tool_names = [t["name"] for t in filtered]

    assert "view_file" in tool_names
    assert "replace_file_content" in tool_names
    assert "write_to_file" in tool_names
    assert "run_command" in tool_names
    assert "invoke_subagent" in tool_names
