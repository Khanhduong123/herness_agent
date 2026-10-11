"""Runner module for executing agent tasks using the agy CLI."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from harness_agent.core.dispatch import verify_and_load_agents_rule
from harness_agent.core.models import AgyConfig, RunResult, Task, ToolCallRecord
from harness_agent.core.token_logger import ModelPricing, TokenLogger

STATIC_PREFIX = (
    "DO NOT output decorative emojis, pictographs, or icons such as "
    "\U0001f680, \U0001f4a1, \u26a0\ufe0f, \u274c, \u2705; "
    "keep output strictly plain ASCII/Markdown."
)


def build_cache_aligned_prompt(
    system_instructions: str,
    dynamic_context: Dict[str, Any],
    user_prompt: str,
    inject_agents_rule: bool = False,
    root_path: Optional[Union[str, Path]] = None,
) -> Tuple[str, str]:
    """Constructs prompt partitioned into static cacheable prefix and dynamic tail.

    Args:
        system_instructions: Invariant base instructions.
        dynamic_context: Dictionary of runtime context (timestamps, paths, etc.).
        user_prompt: Current turn prompt.
        inject_agents_rule: Whether to preflight-verify and inject AGENTS.md rules.
        root_path: Optional root directory path to locate AGENTS.md.

    Returns:
        Tuple of (static_prefix, dynamic_tail).
    """
    cleaned_instructions = system_instructions.strip() if system_instructions else ""
    if inject_agents_rule:
        agents_rule = verify_and_load_agents_rule(root_path or Path.cwd())
        if agents_rule.strip() not in cleaned_instructions:
            if cleaned_instructions:
                cleaned_instructions = f"{agents_rule.strip()}\n\n{cleaned_instructions}"
            else:
                cleaned_instructions = agents_rule.strip()

    if not cleaned_instructions:
        static_prefix = ""
    else:
        # Static prefix must be invariant and contain zero-emoji instruction
        if STATIC_PREFIX not in cleaned_instructions:
            static_prefix = f"{cleaned_instructions}\n\n{STATIC_PREFIX}".strip()
        else:
            static_prefix = cleaned_instructions

    # Build dynamic tail
    dynamic_lines: List[str] = []
    if dynamic_context:
        dynamic_lines.append("## Dynamic Context:")
        for key in sorted(dynamic_context.keys()):
            val = dynamic_context[key]
            dynamic_lines.append(f"- {key}: {val}")

    cleaned_prompt = user_prompt.strip() if user_prompt else ""
    if cleaned_prompt:
        if dynamic_lines:
            dynamic_lines.append("")
        dynamic_lines.append(cleaned_prompt)

    dynamic_tail = "\n".join(dynamic_lines).strip()
    return static_prefix, dynamic_tail


class AgyRunner:
    """Manages the execution of the agy CLI as a subprocess."""

    def __init__(self, config: Optional[AgyConfig] = None) -> None:
        self.config = config or AgyConfig()

    def find_executable(self) -> Optional[str]:
        """Locate the agy executable on PATH or via configured path."""
        if shutil.which(self.config.executable_path):
            return shutil.which(self.config.executable_path)
        # Check standard Windows paths if not found
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidate = os.path.join(local_app_data, "Programs", "Antigravity", "agy.exe")
        if os.path.exists(candidate):
            return candidate
        return None

    def check_version(self) -> Tuple[bool, str]:
        """Check if agy is accessible and return its version string."""
        exe = self.find_executable() or self.config.executable_path
        try:
            res = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if res.returncode == 0:
                version = res.stdout.strip() or res.stderr.strip()
                return True, version
            return False, f"Failed with exit code {res.returncode}: {res.stderr.strip()}"
        except Exception as exc:
            return False, str(exc)

    def build_command(self, prompt: str, task: Optional[Task] = None) -> List[str]:
        """Construct the CLI arguments for agy."""
        exe = self.find_executable() or self.config.executable_path
        cmd = [exe, "--print", prompt]

        if self.config.output_format:
            cmd.extend(["--output-format", self.config.output_format])

        if self.config.dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        if self.config.model:
            cmd.extend(["--model", self.config.model])

        if self.config.effort:
            cmd.extend(["--effort", self.config.effort])

        if self.config.mode:
            cmd.extend(["--mode", self.config.mode])

        if self.config.sandbox:
            cmd.append("--sandbox")

        timeout = (
            task.timeout_seconds if (task and task.timeout_seconds) else self.config.timeout_seconds
        )
        if timeout:
            cmd.extend(["--print-timeout", f"{timeout}s"])

        if self.config.extra_flags:
            cmd.extend(self.config.extra_flags)

        return cmd

    async def execute_task(
        self,
        task: Task,
        log_run: Optional[bool] = None,
        inject_agents_rule: bool = False,
        repo_root: Optional[Union[str, Path]] = None,
    ) -> RunResult:
        """Execute a single task asynchronously through agy."""
        start_time = time.time()
        effective_prompt = task.prompt
        if inject_agents_rule:
            root = repo_root or (Path(task.workspace_dir) if task.workspace_dir else Path.cwd())
            try:
                rule_content = verify_and_load_agents_rule(root)
                if rule_content.strip() not in effective_prompt:
                    effective_prompt = f"{rule_content.strip()}\n\n{effective_prompt}"
            except Exception as exc:
                return RunResult(
                    task_id=task.id,
                    success=False,
                    exit_code=1,
                    duration_seconds=0.0,
                    output_text="",
                    stderr=f"Pre-flight AGENTS.md verification failed: {exc}",
                    error_message=f"Pre-flight AGENTS.md verification failed: {exc}",
                )

        cmd = self.build_command(prompt=effective_prompt, task=task)
        cwd = task.workspace_dir or os.getcwd()

        events: List[Dict[str, Any]] = []
        tool_calls: List[ToolCallRecord] = []
        collected_text_pieces: List[str] = []
        token_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
        }
        error_message: Optional[str] = None
        exit_code = -1
        stderr_output = ""

        timeout = task.timeout_seconds or self.config.timeout_seconds or 120

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=float(timeout)
                )
                exit_code = proc.returncode if proc.returncode is not None else -1
                stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                stderr_output = stderr_bytes.decode("utf-8", errors="replace")

                # Parse output according to format
                if self.config.output_format == "stream-json":
                    for line in stdout_text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            events.append(event)
                            self._extract_stream_data(
                                event, collected_text_pieces, tool_calls, token_usage
                            )
                        except json.JSONDecodeError:
                            collected_text_pieces.append(line)
                else:
                    collected_text_pieces.append(stdout_text)

            except asyncio.TimeoutError:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                exit_code = -1
                error_message = f"Task timed out after {timeout} seconds"

        except Exception as exc:
            error_message = f"Process execution error: {exc}"

        duration = time.time() - start_time
        final_text = "".join(collected_text_pieces).strip()
        success = (exit_code == 0) and (error_message is None)

        prompt_tokens = token_usage["prompt_tokens"]
        completion_tokens = token_usage["completion_tokens"]
        cached_tokens = token_usage["cached_tokens"]
        total_tokens = prompt_tokens + completion_tokens
        model_name = self.config.model or "default"
        estimated_cost = ModelPricing.calculate_cost(
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )

        result = RunResult(
            task_id=task.id,
            success=success,
            exit_code=exit_code,
            duration_seconds=round(duration, 2),
            output_text=final_text,
            stderr=stderr_output,
            raw_events=events,
            tool_calls=tool_calls,
            error_message=error_message,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
        )

        should_log = self.config.auto_log if log_run is None else log_run
        if should_log:
            try:
                TokenLogger.log_run(
                    result=result,
                    role="coder",
                    model=model_name,
                )
            except Exception:
                pass

        return result

    def _extract_stream_data(
        self,
        event: Dict[str, Any],
        text_pieces: List[str],
        tool_calls: List[ToolCallRecord],
        token_usage: Optional[Dict[str, int]] = None,
    ) -> None:
        """Helper to extract text, tool calls, and tokens from stream-json events."""
        event_type = event.get("type") or event.get("event")
        # Standard Antigravity / Gemini stream event structure
        if event_type == "text" or "text" in event:
            text_pieces.append(event.get("text", ""))
        elif event_type == "content":
            text_pieces.append(str(event.get("content", "")))
        elif event_type == "tool_call" or "tool_call" in event:
            tc = event.get("tool_call", {})
            name = tc.get("name") or event.get("name", "unknown_tool")
            args = tc.get("args") or event.get("args", {})
            tool_calls.append(ToolCallRecord(name=name, args=args))
        elif "tool_calls" in event and isinstance(event["tool_calls"], list):
            for tc in event["tool_calls"]:
                tool_calls.append(
                    ToolCallRecord(
                        name=tc.get("name", "unknown_tool"),
                        args=tc.get("args", {}),
                        output=tc.get("output"),
                    )
                )

        # Extract token usage metrics if present
        if token_usage is not None:
            inner = event.get("step_update") or event.get("result") or {}
            usage = (
                event.get("usage")
                or (inner.get("usage") if isinstance(inner, dict) else None)
                or event.get("token_usage")
                or (inner.get("token_usage") if isinstance(inner, dict) else None)
                or event.get("tokens")
                or (inner.get("tokens") if isinstance(inner, dict) else None)
                or (event if event_type in ("usage", "token_usage", "metrics") else None)
            )
            if isinstance(usage, dict):

                def _safe_int(val: Any) -> int:
                    try:
                        return int(val)
                    except (TypeError, ValueError):
                        return 0

                pt = (
                    usage.get("prompt_tokens")
                    or usage.get("input_tokens")
                    or usage.get("prompt_token_count")
                    or 0
                )
                ct = (
                    usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or usage.get("candidates_token_count")
                    or 0
                )
                cached = (
                    usage.get("cache_read_tokens")
                    or usage.get("cached_tokens")
                    or usage.get("cached_content_token_count")
                    or (
                        usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                        if isinstance(usage.get("prompt_tokens_details"), dict)
                        else 0
                    )
                    or 0
                )
                token_usage["prompt_tokens"] = max(token_usage["prompt_tokens"], _safe_int(pt))
                token_usage["completion_tokens"] = max(
                    token_usage["completion_tokens"], _safe_int(ct)
                )
                token_usage["cached_tokens"] = max(token_usage["cached_tokens"], _safe_int(cached))


__all__ = [
    "STATIC_PREFIX",
    "AgyRunner",
    "build_cache_aligned_prompt",
    "verify_and_load_agents_rule",
]
