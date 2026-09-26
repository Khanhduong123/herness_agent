# Harness Agent 🤖⚡

> An evaluation, benchmarking, and orchestration harness for AI agents powered by the **Google Antigravity (`agy`) CLI**.

---

## 📌 Overview

**Harness Agent** provides an automated test and evaluation framework designed to run, validate, and benchmark coding agents executed through the `agy` CLI. It facilitates repeatable benchmark suites, streams agent reasoning and tool executions, validates workspace artifacts, and generates structured evaluation reports.

## 🚀 Key Features

- **Direct `agy` CLI Integration**: Wraps `agy` execution with configurable models, reasoning effort levels (`low`, `medium`, `high`, `max`), timeout management, and permission handling (`--dangerously-skip-permissions`).
- **Stream-JSON Event Parsing**: Ingests NDJSON streams from `agy` in real-time, tracking thoughts, tool calls, and text tokens.
- **Pluggable Evaluation Checks**:
  - `file_exists`: Validates that files/artifacts were created or modified.
  - `text_match`: Regex and substring pattern validation on agent responses.
  - `command_exit_zero`: Runs post-run test commands (e.g., `pytest`, linter checks) inside the workspace.
- **Suite Orchestration & Reporting**: Execute suites defined in YAML/JSON and output detailed pass/fail reports and execution metrics.
- **Developer Hygiene**: Equipped with `pre-commit` (formatting, linting, YAML/JSON hygiene, `black`, `isort`, `flake8`) and `pytest`.

---

## 🛠️ Repository Structure

```
herness_agent/
├── .github/                     # CI/CD workflows (optional)
├── .gitignore                   # Comprehensive Python & build ignore rules
├── .pre-commit-config.yaml      # Git pre-commit hooks configuration
├── pyproject.toml               # Package build, dependencies, and tool settings
├── README.md                    # Project documentation
├── examples/
│   └── sample_suite.yaml        # Sample benchmark evaluation suite
├── src/
│   └── harness_agent/
│       ├── __init__.py          # Package exports
│       ├── __main__.py          # Entrypoint for python -m harness_agent
│       ├── cli.py               # Click CLI (check, run-prompt, run-suite)
│       ├── evaluator.py         # Evaluators (files, text regex, commands)
│       ├── harness.py           # Suite runner and report aggregator
│       ├── models.py            # Pydantic schemas (Task, RunResult, Report, Config)
│       └── runner.py            # agy CLI subprocess execution and stream parser
└── tests/                       # Unit & integration test suite
    ├── test_evaluator.py
    ├── test_harness.py
    ├── test_models.py
    └── test_runner.py
```

---

## ⚡ Quickstart

### 1. Activate Environment

This repository is configured to run inside the Conda `pytorch` environment:

```powershell
conda activate pytorch
```

### 2. Install Development & Pre-commit Hooks

Install the git hook scripts so that every `git commit` automatically triggers code formatting and checks:

```powershell
pre-commit install
```

To run all pre-commit hooks manually across all files:

```powershell
pre-commit run --all-files
```

### 3. Verify `agy` CLI Installation

Ensure that `agy` is installed and on your PATH:

```powershell
python -m harness_agent check
```

---

## 🎯 Usage Guide

### Run a Single Prompt via `agy`

```powershell
python -m harness_agent run-prompt "Write a Python function to compute fibonacci numbers"
```

With custom flags:

```powershell
python -m harness_agent run-prompt "Refactor utils.py" --model gemini-2.5-pro --effort high --timeout 180
```

### Run an Evaluation Benchmark Suite

Define tasks in YAML (see [`examples/sample_suite.yaml`](examples/sample_suite.yaml)):

```yaml
suite_name: "Code Generation Suite"
tasks:
  - id: "task_01"
    name: "Generate Greeting"
    prompt: "Create a greeting function in greeting.py that returns 'Hello World'"
    checks:
      - type: "file_exists"
        target: "greeting.py"
      - type: "command_exit_zero"
        target: "python -c \"import greeting; assert greeting.greet() == 'Hello World'\""
```

Run the benchmark suite:

```powershell
python -m harness_agent run-suite examples/sample_suite.yaml --output runs/results.json
```

---

## 🧪 Running Tests

Run the test suite using `pytest`:

```powershell
pytest
```

---

## 📝 License

MIT
