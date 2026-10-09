"""Unit tests for prompt cache alignment and static prefix invariance."""

import hashlib
from typing import Any, Dict

from harness_agent.core.runner import STATIC_PREFIX, build_cache_aligned_prompt


def test_static_prefix_invariance_across_invocations():
    """TC-01: Verify static prefix hash stability across successive invocations.

    Checks with varying timestamps.
    """
    system_instructions = (
        "You are an expert autonomous software engineer operating inside an agent harness."
    )

    ctx1: Dict[str, Any] = {
        "timestamp": "2026-10-09T10:00:00Z",
        "session_id": "sess-alpha-001",
        "turn": 1,
    }
    user_prompt1 = "Implement feature A"

    ctx2: Dict[str, Any] = {
        "timestamp": "2026-10-09T12:34:56Z",
        "session_id": "sess-alpha-002",
        "turn": 42,
    }
    user_prompt2 = "Run test suite B"

    prefix1, tail1 = build_cache_aligned_prompt(system_instructions, ctx1, user_prompt1)
    prefix2, tail2 = build_cache_aligned_prompt(system_instructions, ctx2, user_prompt2)

    assert prefix1 == prefix2
    hash1 = hashlib.sha256(prefix1.encode("utf-8")).hexdigest()
    hash2 = hashlib.sha256(prefix2.encode("utf-8")).hexdigest()
    assert hash1 == hash2

    # Verify dynamic tails differ and contain their respective contexts
    assert tail1 != tail2
    assert "sess-alpha-001" in tail1
    assert "sess-alpha-002" in tail2


def test_zero_emoji_instruction_present_in_static_prefix():
    """Verify presence of zero-emoji / no-icon instruction in static prefix."""
    system_instructions = "You are a code generation agent."
    prefix, _ = build_cache_aligned_prompt(system_instructions, {}, "hello")

    assert STATIC_PREFIX in prefix
    assert "DO NOT output decorative emojis" in prefix


def test_empty_system_instructions_edge_case():
    """Edge Case 1: Empty system instructions should return empty static prefix."""
    prefix, tail = build_cache_aligned_prompt("", {"timestamp": "2026-10-09T00:00:00Z"}, "do work")
    assert prefix == ""
    assert "do work" in tail
    assert "timestamp: 2026-10-09T00:00:00Z" in tail


def test_dynamic_values_leakage_and_isolation():
    """TC-02 & Edge Case 2: Ensure dynamic variables remain strictly in dynamic tail."""
    system_instructions = "Base invariant agent role instructions."
    dyn_ctx: Dict[str, Any] = {
        "timestamp": "2026-10-09T13:45:00Z",
        "uuid": "urn:uuid:f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        "workspace_dir": "/tmp/agent/worktree_01",
    }
    user_prompt = "Refactor module X"

    prefix, tail = build_cache_aligned_prompt(system_instructions, dyn_ctx, user_prompt)

    # Invariant prefix must NOT contain dynamic values
    assert "2026-10-09T13:45:00Z" not in prefix
    assert "urn:uuid:f81d4fae-7dec-11d0-a765-00a0c91e6bf6" not in prefix
    assert "/tmp/agent/worktree_01" not in prefix

    # Dynamic tail MUST contain dynamic values and user prompt
    assert "2026-10-09T13:45:00Z" in tail
    assert "urn:uuid:f81d4fae-7dec-11d0-a765-00a0c91e6bf6" in tail
    assert "/tmp/agent/worktree_01" in tail
    assert "Refactor module X" in tail


def test_multiline_whitespace_normalization():
    """Edge Case 3: Leading and trailing whitespaces normalized to prevent cache drift."""
    inst1 = "   System instructions with leading and trailing spaces   \n\n"
    inst2 = "System instructions with leading and trailing spaces"

    prefix1, _ = build_cache_aligned_prompt(inst1, {}, "p1")
    prefix2, _ = build_cache_aligned_prompt(inst2, {}, "p2")

    assert prefix1 == prefix2
