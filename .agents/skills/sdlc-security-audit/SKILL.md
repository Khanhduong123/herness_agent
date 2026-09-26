---
name: sdlc-security-audit
description: >-
  Security auditing and vulnerability prevention skill for SDLC tasks.
  Use to audit code diffs for secrets, injection vulnerabilities, and unsafe practices before committing.
---

# SDLC Security Audit: Vulnerability & Secret Prevention

This skill provides security review guidelines for verifying code safety before release or commit.

---

## 1. Secrets & Credentials Prevention
- **Rule**: NEVER hardcode API keys, passwords, bearer tokens, or sensitive URLs in code.
- Check environment variables:
  - Always use `os.environ.get("ENV_VAR_NAME")` or config models.
- Ensure `.gitignore` properly excludes `.env`, `credentials.json`, `runs/`, and local caches.

---

## 2. Command & Injection Vulnerabilities
- When using `subprocess` or `asyncio.create_subprocess_exec`:
  - Pass arguments as a list of strings (`["cmd", "arg1", "arg2"]`), NEVER as `shell=True` with concatenated strings.
  - Sanitize any user input that determines file paths or process execution.

---

## 3. Path Traversal & File Safety
- Use `os.path.abspath`, `os.path.normpath`, or `pathlib.Path.resolve()`.
- Validate that user-supplied paths do not traverse outside the intended directory.
