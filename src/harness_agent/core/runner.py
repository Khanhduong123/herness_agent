"""Runner module for executing agent tasks using the agy CLI."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from harness_agent.core.models import AgyConfig, RunResult, Task, ToolCallRecord

STATIC_PREFIX = (
    "DO NOT output decorative emojis, pictographs, or icons such as "
    "\U0001f680, \U0001f4a1, \u26a0\ufe0f, \u274c, \u2705; "
    "keep output strictly plain ASCII/Markdown."
)


def build_cache_aligned_prompt(
    system_instructions: str,
    dynamic_context: Dict[str, Any],
    user_prompt: str,
) -> Tuple[str, str]:
    """Constructs prompt partitioned into static cacheable prefix and dynamic tail.

    Args:
        system_instructions: Invariant base instructions.
        dynamic_context: Dictionary of runtime context (timestamps, paths, etc.).
        user_prompt: Current turn prompt.

    Returns:
        Tuple of (static_prefix, dynamic_tail).
    """
    cleaned_instructions = system_instructions.strip() if system_instructions else ""
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

    async def execute_task(self, task: Task) -> RunResult:
        """Execute a single task asynchronously through agy."""
        start_time = time.time()
        cmd = self.build_command(prompt=task.prompt, task=task)
        cwd = task.workspace_dir or os.getcwd()

        events: List[Dict[str, Any]] = []
        tool_calls: List[ToolCallRecord] = []
        collected_text_pieces: List[str] = []
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
                            self._extract_stream_data(event, collected_text_pieces, tool_calls)
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

        return RunResult(
            task_id=task.id,
            success=success,
            exit_code=exit_code,
            duration_seconds=round(duration, 2),
            output_text=final_text,
            stderr=stderr_output,
            raw_events=events,
            tool_calls=tool_calls,
            error_message=error_message,
        )

    def _extract_stream_data(
        self,
        event: Dict[str, Any],
        text_pieces: List[str],
        tool_calls: List[ToolCallRecord],
    ) -> None:
        """Helper to extract text and tool calls from stream-json events."""
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
