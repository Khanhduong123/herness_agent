"""Knowledge reflector executing 100% native agy subprocesses.

Synthesizes learned rules, anti-patterns, and reusable procedural skills from incident trajectories.
Maintains state of truth in JSON and renders markdown views.
Enforces Decayed LFU eviction with a 7-day grace period and grace-period overflow fallback.
Caps active skills at 15 with automated archiving.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from harness_agent.learning.models import AntiPattern, IncidentTrajectory, LearnedRule

logger = logging.getLogger(__name__)

# System micro-prompt instructing agy to return concise JSON
MICRO_PROMPT_TEMPLATE = (
    "You are an autonomous cognitive reflector. Analyze this incident trajectory and return ONLY "
    "a strict JSON object (no markdown, no code fences, no commentary).\n"
    "Format:\n"
    "{{\n"
    '  "rule": {{\n'
    '    "id": "rule_<short_snake_case_id>",\n'
    '    "title": "<Concise descriptive title>",\n'
    '    "trigger_context": "<Specific trigger keywords/conditions, comma separated>",\n'
    '    "directive": "<Clear mandatory instruction on how to avoid or handle this>",\n'
    '    "tags": ["tag1", "tag2"]\n'
    "  }},\n"
    '  "anti_pattern": {{\n'
    '    "id": "ap_<short_snake_case_id>",\n'
    '    "pattern_name": "<Pattern name>",\n'
    '    "forbidden_behavior": "<Specific action/code pattern that fails>",\n'
    '    "reason": "<Why it causes an error>",\n'
    '    "alternative": "<What should be done instead>",\n'
    '    "tags": ["tag1", "tag2"]\n'
    "  }},\n"
    '  "procedural_skill": null\n'
    "}}\n"
    "Incident Data:\n"
    "- Session: {session_id}\n"
    "- Type: {incident_type}\n"
    "- Trigger Error: {trigger_error}\n"
    "- Failing Tool: {failing_tool}\n"
    "- Hypothesis: {root_cause}\n"
    "- Resolution: {resolution}\n"
)


class KnowledgeReflector:
    """Reflector that turns trajectories into structured rules, anti-patterns, and skills."""

    MAX_RULES: int = 30
    MAX_ANTI_PATTERNS: int = 20
    MAX_ACTIVE_SKILLS: int = 15

    def __init__(
        self,
        output_dir: str | Path = ".ai/learned",
        skills_dir: str | Path = ".agents/skills",
        skills_archive_dir: str | Path = ".agents/skills-archive",
        model: str = "gemini-3.8-flash-low",
        effort: str = "low",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.skills_dir = Path(skills_dir)
        self.skills_archive_dir = Path(skills_archive_dir)
        self.model = model
        self.effort = effort

    # -------------------------------------------------------------------------
    # State Persistence: Loading & Atomic Saving
    # -------------------------------------------------------------------------

    def load_rules(self) -> List[LearnedRule]:
        """Load rules from state of truth (.json)."""
        rules_path = self.output_dir / "rules.json"
        if not rules_path.exists():
            return []
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [LearnedRule(**item) for item in data]
        except Exception as e:
            logger.warning("Failed to load %s: %s", rules_path, e)
            return []

    def load_anti_patterns(self) -> List[AntiPattern]:
        """Load anti-patterns from state of truth (.json)."""
        ap_path = self.output_dir / "anti_patterns.json"
        if not ap_path.exists():
            return []
        try:
            with open(ap_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [AntiPattern(**item) for item in data]
        except Exception as e:
            logger.warning("Failed to load %s: %s", ap_path, e)
            return []

    def save_rules(self, rules: List[LearnedRule], render_markdown: bool = True) -> None:
        """Save rules atomically to .json and render readable markdown view."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rules_json_path = self.output_dir / "rules.json"
        temp_json_path = self.output_dir / "rules.json.tmp"

        data = [r.model_dump() for r in rules]
        with open(temp_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_json_path, rules_json_path)

        if render_markdown:
            self._render_rules_markdown(rules)

    def save_anti_patterns(
        self, anti_patterns: List[AntiPattern], render_markdown: bool = True
    ) -> None:
        """Save anti-patterns atomically to .json and render readable markdown view."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ap_json_path = self.output_dir / "anti_patterns.json"
        temp_json_path = self.output_dir / "anti_patterns.json.tmp"

        data = [ap.model_dump() for ap in anti_patterns]
        with open(temp_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_json_path, ap_json_path)

        if render_markdown:
            self._render_anti_patterns_markdown(anti_patterns)

    # -------------------------------------------------------------------------
    # Markdown Rendering
    # -------------------------------------------------------------------------

    def _render_rules_markdown(self, rules: List[LearnedRule]) -> None:
        """Render readable .ai/learned/rules.md view from JSON state."""
        lines = [
            "# Semantic Memory: Learned Rules",
            "",
            "> [!NOTE]",
            "> This view is auto-generated from `rules.json`. Do not edit manually.",
            "",
        ]
        sorted_rules = sorted(
            rules, key=lambda r: (r.calculate_priority_score(), r.last_hit_at), reverse=True
        )
        for r in sorted_rules:
            score = round(r.calculate_priority_score(), 3)
            tags_str = ", ".join(r.tags)
            lines.extend(
                [
                    f"## {r.title} (`{r.id}`)",
                    f"- **Score**: {score} | **Hits**: {r.hit_count} | **Tags**: {tags_str}",
                    f"- **Trigger Context**: `{r.trigger_context}`",
                    f"- **Directive**: {r.directive}",
                    "",
                ]
            )
        md_path = self.output_dir / "rules.md"
        temp_md_path = self.output_dir / "rules.md.tmp"
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")
        os.replace(temp_md_path, md_path)

    def _render_anti_patterns_markdown(self, anti_patterns: List[AntiPattern]) -> None:
        """Render readable .ai/learned/anti_patterns.md view from JSON state."""
        lines = [
            "# Semantic Memory: Learned Anti-Patterns",
            "",
            "> [!NOTE]",
            "> This view is auto-generated from `anti_patterns.json`. Do not edit manually.",
            "",
        ]
        sorted_aps = sorted(
            anti_patterns,
            key=lambda ap: (ap.calculate_priority_score(), ap.last_hit_at),
            reverse=True,
        )
        for ap in sorted_aps:
            score = round(ap.calculate_priority_score(), 3)
            tags_str = ", ".join(ap.tags)
            lines.extend(
                [
                    f"## {ap.pattern_name} (`{ap.id}`)",
                    f"- **Score**: {score} | **Hits**: {ap.hit_count} | **Tags**: {tags_str}",
                    f"- **Forbidden**: {ap.forbidden_behavior}",
                    f"- **Reason**: {ap.reason}",
                    f"- **Alternative**: {ap.alternative}",
                    "",
                ]
            )
        md_path = self.output_dir / "anti_patterns.md"
        temp_md_path = self.output_dir / "anti_patterns.md.tmp"
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")
        os.replace(temp_md_path, md_path)

    # -------------------------------------------------------------------------
    # Decayed LFU Eviction with Grace Period & Overflow Fallback
    # -------------------------------------------------------------------------

    def prune_rules(
        self,
        rules: List[LearnedRule],
        max_rules: Optional[int] = None,
        now: Optional[float] = None,
    ) -> List[LearnedRule]:
        """Prune rules down to max_rules using Decayed LFU with 7-day grace period.

        Fallback logic:
        1. Candidates: items where not r.is_in_grace_period(now=now).
        2. If candidates exist, evict min(candidates, key=(score, created_at)).
        3. Grace Period Overflow Fallback: If ALL items are within grace period,
           bypass immunity and evict min(rules, key=(score, created_at)).
        """
        cap = max_rules if max_rules is not None else self.MAX_RULES
        current_time = now if now is not None else time.time()
        rules_list = list(rules)

        while len(rules_list) > cap:
            candidates = [r for r in rules_list if not r.is_in_grace_period(now=current_time)]
            if candidates:
                evict_target = min(
                    candidates,
                    key=lambda x: (x.calculate_priority_score(now=current_time), x.created_at),
                )
            else:
                # Grace Period Overflow Fallback: All are within grace period, but cap is breached.
                evict_target = min(
                    rules_list,
                    key=lambda x: (x.calculate_priority_score(now=current_time), x.created_at),
                )
            rules_list.remove(evict_target)

        return rules_list

    def prune_anti_patterns(
        self,
        anti_patterns: List[AntiPattern],
        max_anti_patterns: Optional[int] = None,
        now: Optional[float] = None,
    ) -> List[AntiPattern]:
        """Prune anti-patterns down to cap using Decayed LFU with grace period fallback."""
        cap = max_anti_patterns if max_anti_patterns is not None else self.MAX_ANTI_PATTERNS
        current_time = now if now is not None else time.time()
        ap_list = list(anti_patterns)

        while len(ap_list) > cap:
            candidates = [ap for ap in ap_list if not ap.is_in_grace_period(now=current_time)]
            if candidates:
                evict_target = min(
                    candidates,
                    key=lambda x: (x.calculate_priority_score(now=current_time), x.created_at),
                )
            else:
                # Grace Period Overflow Fallback
                evict_target = min(
                    ap_list,
                    key=lambda x: (x.calculate_priority_score(now=current_time), x.created_at),
                )
            ap_list.remove(evict_target)

        return ap_list

    # -------------------------------------------------------------------------
    # Skill Auto-Generation & 15-Skill Cap Archiving
    # -------------------------------------------------------------------------

    def save_procedural_skill(
        self,
        skill_name: str,
        frontmatter: Dict[str, Any],
        content: str,
    ) -> Path:
        """Save procedural skill with yaml.safe_dump frontmatter and enforce 15-skill cap."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills_archive_dir.mkdir(parents=True, exist_ok=True)

        target_skill_dir = self.skills_dir / skill_name
        target_skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_skill_dir / "SKILL.md"

        yaml_header = yaml.safe_dump(frontmatter, sort_keys=False).strip()
        file_content = f"---\n{yaml_header}\n---\n\n{content.strip()}\n"

        temp_file = target_skill_dir / "SKILL.md.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(file_content)
        os.replace(temp_file, skill_file)

        self._enforce_skill_cap()
        return skill_file

    def _enforce_skill_cap(self) -> None:
        """Enforce maximum 15 active learned skills by archiving oldest to skills-archive."""
        if not self.skills_dir.exists():
            return

        # We look for learned skills or all skill directories
        skill_dirs = [
            p
            for p in self.skills_dir.iterdir()
            if p.is_dir() and (p.name.startswith("learned-") or (p / "SKILL.md").exists())
        ]

        if len(skill_dirs) <= self.MAX_ACTIVE_SKILLS:
            return

        # Sort by mtime ascending (oldest first)
        def _get_mtime(p: Path) -> float:
            skill_md = p / "SKILL.md"
            if skill_md.exists():
                return skill_md.stat().st_mtime
            return p.stat().st_mtime

        skill_dirs.sort(key=_get_mtime)

        # Archive excess skills
        excess_count = len(skill_dirs) - self.MAX_ACTIVE_SKILLS
        for dir_to_archive in skill_dirs[:excess_count]:
            dest_path = self.skills_archive_dir / dir_to_archive.name
            if dest_path.exists():
                shutil.rmtree(dest_path)
            shutil.move(str(dir_to_archive), str(dest_path))
            logger.info("Archived skill %s to %s", dir_to_archive.name, dest_path)

    # -------------------------------------------------------------------------
    # Reflection & Micro-Prompt Execution via agy CLI
    # -------------------------------------------------------------------------

    def synthesize_deterministic_rule(
        self, trajectory: IncidentTrajectory, now: Optional[float] = None
    ) -> Tuple[LearnedRule, AntiPattern]:
        """Synthesize pure python deterministic rule & anti-pattern (0 tokens)."""
        current_time = now if now is not None else time.time()
        safe_tool = trajectory.failing_tool.replace("-", "_").lower() or "tool"
        short_id = f"rule_{safe_tool}_{int(current_time) % 100000}"

        title = f"Avoid {trajectory.failing_tool} Failure: {trajectory.root_cause_hypothesis[:40]}"
        directive = f"{trajectory.resolution}. Root cause: {trajectory.root_cause_hypothesis}."

        rule = LearnedRule(
            id=short_id,
            title=title,
            trigger_context=trajectory.trigger_error[:100],
            directive=directive,
            tags=["deterministic", safe_tool],
            hit_count=1,
            created_at=current_time,
            last_hit_at=current_time,
            source_sessions=[trajectory.session_id],
        )

        anti_pattern = AntiPattern(
            id=f"ap_{safe_tool}_{int(current_time) % 100000}",
            pattern_name=f"Unchecked {safe_tool} Call",
            forbidden_behavior=trajectory.trigger_error[:120],
            reason=trajectory.root_cause_hypothesis or "Causes runtime execution failure",
            alternative=trajectory.resolution or "Check parameters before execution",
            tags=["deterministic", safe_tool],
            hit_count=1,
            created_at=current_time,
            last_hit_at=current_time,
        )

        return rule, anti_pattern

    def execute_native_reflection(self, trajectory: IncidentTrajectory) -> Optional[Dict[str, Any]]:
        """Execute agy subprocess to reflect on incident with gemini-3.8-flash-low."""
        prompt = MICRO_PROMPT_TEMPLATE.format(
            session_id=trajectory.session_id,
            incident_type=trajectory.incident_type.value,
            trigger_error=trajectory.trigger_error[:200],
            failing_tool=trajectory.failing_tool,
            root_cause=trajectory.root_cause_hypothesis or "Investigate failure reason",
            resolution=trajectory.resolution or "Investigate resolution step",
        )

        cmd = [
            "agy",
            "-p",
            prompt,
            "--model",
            self.model,
            "--effort",
            self.effort,
        ]

        kwargs: Dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "check": False,
            "timeout": 45,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            res = subprocess.run(
                cmd,
                **kwargs,
            )
            if res.returncode != 0:
                logger.warning(
                    "agy reflection returned non-zero %d: %s", res.returncode, res.stderr
                )
                return None

            output_text = res.stdout.strip()
            # Clean markdown JSON block if present
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", output_text)
            if json_match:
                output_text = json_match.group(1).strip()

            return json.loads(output_text)
        except Exception as e:
            logger.warning("Failed executing agy native reflection: %s", e)
            return None

    def reflect_and_learn(
        self,
        trajectories: List[IncidentTrajectory],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Process harvested trajectories, update semantic memory, and persist state."""
        current_time = now if now is not None else time.time()
        existing_rules = self.load_rules()
        existing_anti_patterns = self.load_anti_patterns()

        rules_by_id: Dict[str, LearnedRule] = {r.id: r for r in existing_rules}
        ap_by_id: Dict[str, AntiPattern] = {ap.id: ap for ap in existing_anti_patterns}

        added_rules: List[LearnedRule] = []
        added_anti_patterns: List[AntiPattern] = []

        for traj in trajectories:
            if traj.is_deterministic:
                rule, ap = self.synthesize_deterministic_rule(traj, now=current_time)
                self._upsert_rule(rules_by_id, rule, current_time)
                self._upsert_anti_pattern(ap_by_id, ap, current_time)
                added_rules.append(rule)
                added_anti_patterns.append(ap)
            else:
                reflection_data = self.execute_native_reflection(traj)
                if not reflection_data:
                    # Fallback to deterministic synthesis if agy CLI fails or is mocked
                    rule, ap = self.synthesize_deterministic_rule(traj, now=current_time)
                    self._upsert_rule(rules_by_id, rule, current_time)
                    self._upsert_anti_pattern(ap_by_id, ap, current_time)
                    added_rules.append(rule)
                    added_anti_patterns.append(ap)
                    continue

                rule_dict = reflection_data.get("rule")
                if rule_dict:
                    rule = LearnedRule(
                        id=rule_dict.get("id", f"rule_{int(current_time) % 100000}"),
                        title=rule_dict.get("title", "Learned Rule"),
                        trigger_context=rule_dict.get("trigger_context", traj.trigger_error),
                        directive=rule_dict.get("directive", traj.resolution),
                        tags=rule_dict.get("tags", []),
                        hit_count=1,
                        created_at=current_time,
                        last_hit_at=current_time,
                        source_sessions=[traj.session_id],
                    )
                    self._upsert_rule(rules_by_id, rule, current_time)
                    added_rules.append(rule)

                ap_dict = reflection_data.get("anti_pattern")
                if ap_dict:
                    ap = AntiPattern(
                        id=ap_dict.get("id", f"ap_{int(current_time) % 100000}"),
                        pattern_name=ap_dict.get("pattern_name", "Anti-Pattern"),
                        forbidden_behavior=ap_dict.get("forbidden_behavior", traj.trigger_error),
                        reason=ap_dict.get("reason", traj.root_cause_hypothesis),
                        alternative=ap_dict.get("alternative", traj.resolution),
                        tags=ap_dict.get("tags", []),
                        hit_count=1,
                        created_at=current_time,
                        last_hit_at=current_time,
                    )
                    self._upsert_anti_pattern(ap_by_id, ap, current_time)
                    added_anti_patterns.append(ap)

                skill_data = reflection_data.get("procedural_skill")
                if skill_data and isinstance(skill_data, dict):
                    skill_name = skill_data.get("name")
                    fm = skill_data.get("frontmatter", {})
                    content = skill_data.get("content", "")
                    if skill_name and content:
                        self.save_procedural_skill(skill_name, fm, content)

        # Apply Decayed LFU pruning
        final_rules = self.prune_rules(list(rules_by_id.values()), now=current_time)
        final_aps = self.prune_anti_patterns(list(ap_by_id.values()), now=current_time)

        # Atomic persistence
        self.save_rules(final_rules, render_markdown=True)
        self.save_anti_patterns(final_aps, render_markdown=True)

        return {
            "total_rules": len(final_rules),
            "total_anti_patterns": len(final_aps),
            "added_rules": [r.id for r in added_rules],
            "added_anti_patterns": [ap.id for ap in added_anti_patterns],
        }

    def _upsert_rule(
        self, rules_dict: Dict[str, LearnedRule], rule: LearnedRule, current_time: float
    ) -> None:
        """Update existing rule hit count or insert new rule."""
        if rule.id in rules_dict:
            target = rules_dict[rule.id]
            target.hit_count += 1
            target.last_hit_at = current_time
            if rule.source_sessions:
                target.source_sessions.extend(
                    [s for s in rule.source_sessions if s not in target.source_sessions]
                )
        else:
            rules_dict[rule.id] = rule

    def _upsert_anti_pattern(
        self, ap_dict: Dict[str, AntiPattern], ap: AntiPattern, current_time: float
    ) -> None:
        """Update existing anti-pattern hit count or insert new anti-pattern."""
        if ap.id in ap_dict:
            target = ap_dict[ap.id]
            target.hit_count += 1
            target.last_hit_at = current_time
        else:
            ap_dict[ap.id] = ap
