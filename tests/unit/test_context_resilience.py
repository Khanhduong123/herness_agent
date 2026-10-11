"""Unit tests for rolling token compaction, history checkpointing, and re-anchoring prompts."""

import pytest

from harness_agent.core.runner import build_pre_step_reanchoring_prompt
from harness_agent.core.state import check_token_compaction_trigger, compact_history_to_checkpoint


class TestTokenCompactionTrigger:
    def test_tc01_usage_below_threshold(self) -> None:
        """Usage below threshold (<65%) returns False."""
        assert check_token_compaction_trigger(current_tokens=50000, max_tokens=100000) is False

    def test_tc02_usage_above_or_at_threshold(self) -> None:
        """Usage above or at threshold (>=65%) returns True."""
        assert check_token_compaction_trigger(current_tokens=65000, max_tokens=100000) is True
        assert check_token_compaction_trigger(current_tokens=70000, max_tokens=100000) is True

    def test_edge_zero_or_negative_tokens(self) -> None:
        """Guard against division by zero or negative tokens."""
        assert check_token_compaction_trigger(0, 0) is False
        assert check_token_compaction_trigger(0, 100000) is False
        assert check_token_compaction_trigger(10000, 0) is False
        assert check_token_compaction_trigger(-10, 100000) is False
        assert check_token_compaction_trigger(10000, -100) is False

    def test_edge_threshold_ratio_out_of_range(self) -> None:
        """Threshold ratio must be between 0.1 and 1.0."""
        with pytest.raises(ValueError, match="threshold_ratio must be between"):
            check_token_compaction_trigger(50000, 100000, threshold_ratio=0.05)

        with pytest.raises(ValueError, match="threshold_ratio must be between"):
            check_token_compaction_trigger(50000, 100000, threshold_ratio=1.5)


class TestCompactHistoryToCheckpoint:
    def test_tc03_older_turns_compaction(self) -> None:
        """Older turns are condensed into checkpoint summary while preserving recent window."""
        turns = [{"role": "user", "content": f"User request {i}", "step": i} for i in range(1, 11)]
        compacted = compact_history_to_checkpoint(turns, preserve_recent=3)
        # Expected: 1 checkpoint turn + 3 recent turns = 4 items
        assert len(compacted) == 4
        assert compacted[0]["role"] == "system"
        assert compacted[0]["checkpoint"] is True
        assert compacted[0]["summarized_turns_count"] == 7
        assert "Execution History Summary" in compacted[0]["content"]

        # Check recent turns preserved verbatim
        assert compacted[1]["content"] == "User request 8"
        assert compacted[2]["content"] == "User request 9"
        assert compacted[3]["content"] == "User request 10"

    def test_empty_turns(self) -> None:
        """Empty turn history returns empty list without error."""
        assert compact_history_to_checkpoint([]) == []

    def test_turns_less_than_preserve_recent(self) -> None:
        """If turn count <= preserve_recent, no checkpoint is created and turns returned."""
        turns = [
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "turn 2"},
        ]
        compacted = compact_history_to_checkpoint(turns, preserve_recent=3)
        assert len(compacted) == 2
        assert compacted[0]["content"] == "turn 1"
        assert compacted[1]["content"] == "turn 2"

    def test_preserve_recent_zero_or_negative(self) -> None:
        """Preserve zero turns summarizes all turns into checkpoint."""
        turns = [{"role": "user", "content": "only turn"}]
        compacted = compact_history_to_checkpoint(turns, preserve_recent=0)
        assert len(compacted) == 1
        assert compacted[0]["checkpoint"] is True
        assert compacted[0]["summarized_turns_count"] == 1


class TestPreStepReanchoringPrompt:
    def test_tc04_reanchoring_prompt_formatting(self) -> None:
        """Generates deterministic re-anchoring reminder prompt."""
        prompt = build_pre_step_reanchoring_prompt(
            objective="Implement feature X",
            active_constraints=["No full file overwrite", "Execute synchronously"],
            modified_files=["src/core/state.py", "tests/unit/test_state.py"],
        )
        expected = (
            "[RE-ANCHORING REMINDER: Objective: Implement feature X | "
            "Constraints: No full file overwrite; Execute synchronously | "
            "Modified Files: src/core/state.py, tests/unit/test_state.py]"
        )
        assert prompt == expected

    def test_edge_empty_modified_files(self) -> None:
        """Empty modified files formats gracefully as 'None yet'."""
        prompt = build_pre_step_reanchoring_prompt(
            objective="Do task",
            active_constraints=["Constraint A"],
            modified_files=[],
        )
        assert "Modified Files: None yet" in prompt

    def test_edge_empty_constraints_and_objective(self) -> None:
        """Empty constraints and objective handle empty values gracefully."""
        prompt = build_pre_step_reanchoring_prompt(
            objective="",
            active_constraints=[],
            modified_files=[],
        )
        assert prompt == (
            "[RE-ANCHORING REMINDER: Objective: None | "
            "Constraints: None | Modified Files: None yet]"
        )
