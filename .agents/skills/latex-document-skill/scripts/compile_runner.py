#!/usr/bin/env python3
"""Cross-platform LaTeX compilation runner and Windows compiler bridge.

Provides multi-tier execution strategy:
  1. Tier 1 (Native Engine): pdflatex, xelatex, lualatex, latexmk in PATH.
  2. Tier 2 (Docker TeX Live): containerized compilation when Docker daemon is available.
  3. Tier 3 (Dry-Run / Syntax Validation Fallback): AST/syntax validation via validate_latex.py
     with actionable diagnostic installer instructions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def check_binary(binary_name: str) -> Optional[str]:
    """Find absolute path to an executable if available."""
    return shutil.which(binary_name)


def is_docker_daemon_running() -> bool:
    """Check if docker binary exists and docker daemon is reachable."""
    docker_bin = check_binary("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            [docker_bin, "info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            text=True,
            check=False,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def get_validate_script_path() -> Optional[Path]:
    """Find validate_latex.py in the same directory as this script."""
    script_dir = Path(__file__).resolve().parent
    validate_script = script_dir / "validate_latex.py"
    if validate_script.is_file():
        return validate_script
    return None


def inspect_environment() -> Dict[str, Any]:
    """Inspect environment capabilities for LaTeX compilation and validation."""
    engines = {
        "pdflatex": check_binary("pdflatex"),
        "xelatex": check_binary("xelatex"),
        "lualatex": check_binary("lualatex"),
        "latexmk": check_binary("latexmk"),
    }
    poppler = {
        "pdftoppm": check_binary("pdftoppm"),
    }
    docker_path = check_binary("docker")
    docker_daemon = is_docker_daemon_running() if docker_path else False
    validate_script = get_validate_script_path()

    available_native = [eng for eng, path in engines.items() if path is not None]

    return {
        "platform": sys.platform,
        "native_engines": engines,
        "available_native_engines": available_native,
        "docker": {
            "installed": docker_path is not None,
            "path": docker_path,
            "daemon_running": docker_daemon,
        },
        "preview_tools": poppler,
        "syntax_validator": {
            "available": validate_script is not None,
            "path": str(validate_script) if validate_script else None,
        },
    }


def auto_detect_engine(tex_path: Path) -> str:
    """Inspect .tex file content to determine whether xelatex, lualatex, or pdflatex is required."""
    if not tex_path.is_file():
        return "pdflatex"
    try:
        content = tex_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "pdflatex"

    uncommented_lines = []
    for line in content.splitlines():
        line_clean = line.split("%", 1)[0].strip()
        if line_clean:
            uncommented_lines.append(line_clean)
    clean_text = "\n".join(uncommented_lines)

    if re.search(r"\\usepackage\{(?:fontspec|xeCJK|polyglossia)\}", clean_text):
        return "xelatex"
    if re.search(r"\\usepackage\{(?:luacode|luatextra)\}|\\directlua", clean_text):
        return "lualatex"
    return "pdflatex"


def run_syntax_validation(
    tex_path: Path,
    preamble_path: Optional[Path] = None,
    as_json: bool = False,
    full_document: bool = True,
) -> Tuple[int, str]:
    """Execute validate_latex.py against the given file."""
    val_script = get_validate_script_path()
    if not val_script:
        return 1, "Error: validate_latex.py not found in script directory."

    cmd = [sys.executable, str(val_script)]
    if preamble_path and preamble_path.is_file():
        cmd.extend(["--preamble", str(preamble_path)])
    if as_json:
        cmd.append("--json")
    if full_document:
        cmd.append("--full-document")
    cmd.append(str(tex_path))

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        output = res.stdout if res.stdout else res.stderr
        return res.returncode, output.strip()
    except Exception as exc:
        return 1, f"Error running validate_latex.py: {exc}"


def get_windows_installer_guidance() -> str:
    """Return actionable guidance for setting up LaTeX compilers on Windows."""
    return (
        "=== Windows LaTeX Compiler Setup Guidance ===\n"
        "No native LaTeX engine (pdflatex/xelatex/latexmk) or running Docker container was detected.\n"
        "To compile PDFs natively on Windows, install one of the following:\n\n"
        "1. MiKTeX (Recommended for Windows):\n"
        "   Command: winget install MiKTeX.MiKTeX\n"
        "   After installation, restart your terminal so PATH updates take effect.\n\n"
        "2. TeX Live (Full TeX distribution):\n"
        "   Installer: https://www.tug.org/texlive/windows.html\n\n"
        "3. Docker TeX Live (Containerized):\n"
        "   Command: docker pull texlive/texlive:latest\n"
        "   Ensure Docker Desktop is running before invoking compile_runner.py."
    )


def compile_with_native(
    tex_path: Path,
    engine: str,
    output_dir: Path,
    use_latexmk: bool = False,
) -> Tuple[int, str]:
    """Compile document using native compiler command."""
    compiler = "latexmk" if (use_latexmk and check_binary("latexmk")) else engine
    cmd: List[str] = []

    if compiler == "latexmk":
        engine_flag = f"-{engine}" if engine in ("pdflatex", "xelatex", "lualatex") else "-pdf"
        cmd = [
            "latexmk",
            engine_flag,
            "-interaction=nonstopmode",
            f"-outdir={str(output_dir)}",
            str(tex_path),
        ]
    else:
        cmd = [
            compiler,
            "-interaction=nonstopmode",
            f"-output-directory={str(output_dir)}",
            str(tex_path),
        ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
            cwd=str(tex_path.parent),
            check=False,
        )
        output = res.stdout if res.stdout else res.stderr
        return res.returncode, output
    except Exception as exc:
        return 1, f"Failed executing native compiler {compiler}: {exc}"


def compile_with_docker(
    tex_path: Path,
    engine: str,
    output_dir: Path,
) -> Tuple[int, str]:
    """Compile document inside texlive/texlive docker container."""
    docker_bin = check_binary("docker") or "docker"
    workdir = tex_path.parent.resolve()
    filename = tex_path.name
    # Mounting current directory into container
    cmd = [
        docker_bin,
        "run",
        "--rm",
        "-v",
        f"{str(workdir)}:/workdir",
        "-w",
        "/workdir",
        "texlive/texlive:latest",
        engine,
        "-interaction=nonstopmode",
        filename,
    ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            cwd=str(workdir),
            check=False,
        )
        output = res.stdout if res.stdout else res.stderr
        return res.returncode, output
    except Exception as exc:
        return 1, f"Failed executing Docker compilation: {exc}"


def generate_png_previews(pdf_path: Path, output_dir: Path, scale: int = 1200) -> Tuple[int, str]:
    """Generate PNG preview images if pdftoppm is available."""
    pdftoppm = check_binary("pdftoppm")
    if not pdftoppm:
        return 1, "pdftoppm not found in PATH; skipping PNG preview generation."

    prefix = output_dir / pdf_path.stem
    cmd = [
        pdftoppm,
        "-png",
        "-r",
        "150",
        "-scale-to",
        str(scale),
        str(pdf_path),
        str(prefix),
    ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
        return res.returncode, res.stdout or res.stderr
    except Exception as exc:
        return 1, f"Failed generating preview: {exc}"


def build_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Cross-platform LaTeX compilation runner and Windows compiler bridge.",
    )
    parser.add_argument(
        "--file",
        "-f",
        dest="file",
        help="Path to the .tex file to compile or validate.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect system environment for LaTeX engines, Docker daemon, and validation tools.",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "pdflatex", "xelatex", "lualatex"],
        default="auto",
        help="LaTeX engine to use (default: auto).",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory for generated PDF and auxiliary files.",
    )
    parser.add_argument(
        "--use-latexmk",
        action="store_true",
        help="Use latexmk for compilation if available.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate PNG previews using pdftoppm if available.",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=1200,
        help="Max dimension in pixels for PNG previews (default: 1200).",
    )
    parser.add_argument(
        "--dry-run-ok",
        action="store_true",
        help="Exit code 0 if syntax validation passes when no compiler is available.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output environment inspection or diagnostics as JSON.",
    )
    parser.add_argument(
        "--preamble",
        help="Optional preamble file passed to validate_latex.py.",
    )
    return parser


def main() -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    # 1. Environment check mode
    if args.check:
        env_info = inspect_environment()
        if args.json:
            print(json.dumps(env_info, indent=2))
        else:
            print("=== LaTeX Compilation Environment Inspection ===")
            print(f"OS Platform: {env_info['platform']}")
            print("Native Engines:")
            for eng, path in env_info["native_engines"].items():
                status = f"[FOUND] ({path})" if path else "[NOT FOUND]"
                print(f"  - {eng:10s}: {status}")
            docker_info = env_info["docker"]
            doc_status = "[NOT FOUND]"
            if docker_info["installed"]:
                doc_status = "[FOUND - DAEMON ACTIVE]" if docker_info["daemon_running"] else "[FOUND - DAEMON INACTIVE]"
            print(f"Docker: {doc_status}")
            val_info = env_info["syntax_validator"]
            val_status = f"[FOUND] ({val_info['path']})" if val_info["available"] else "[NOT FOUND]"
            print(f"Syntax Validator (validate_latex.py): {val_status}")
            poppler_info = env_info["preview_tools"]["pdftoppm"]
            poppler_status = f"[FOUND] ({poppler_info})" if poppler_info else "[NOT FOUND]"
            print(f"Preview Tool (pdftoppm): {poppler_status}")
        return 0

    # Ensure a file was provided if not in --check mode
    if not args.file:
        parser.error("The following argument is required: --file (or specify --check)")

    tex_path = Path(args.file).resolve()
    if not tex_path.is_file():
        print(f"Error: LaTeX source file not found: {tex_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir).resolve() if args.output_dir else tex_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine desired engine
    selected_engine = args.engine
    if selected_engine == "auto":
        selected_engine = auto_detect_engine(tex_path)

    env = inspect_environment()
    has_native = env["native_engines"].get(selected_engine) is not None or (
        args.use_latexmk and env["native_engines"].get("latexmk") is not None
    )
    has_docker = env["docker"]["daemon_running"]

    # Tier 1: Native Compiler Execution
    if has_native:
        print(f":: Compiling {tex_path.name} using native {selected_engine}...")
        rc, out = compile_with_native(tex_path, selected_engine, output_dir, use_latexmk=args.use_latexmk)
        if rc == 0:
            pdf_path = output_dir / f"{tex_path.stem}.pdf"
            print(f":: Compilation succeeded: {pdf_path}")
            if args.preview:
                prev_rc, prev_out = generate_png_previews(pdf_path, output_dir, scale=args.scale)
                if prev_rc == 0:
                    print(f":: Generated preview images in {output_dir}")
                else:
                    print(f":: Preview generation notice: {prev_out}")
            return 0
        else:
            print(f"Error: Native compilation failed (exit code {rc}):\n{out}", file=sys.stderr)
            return rc

    # Tier 2: Docker Containerized Execution
    if has_docker:
        print(f":: Compiling {tex_path.name} via Docker texlive/texlive ({selected_engine})...")
        rc, out = compile_with_docker(tex_path, selected_engine, output_dir)
        if rc == 0:
            pdf_path = output_dir / f"{tex_path.stem}.pdf"
            print(f":: Docker compilation succeeded: {pdf_path}")
            if args.preview:
                prev_rc, prev_out = generate_png_previews(pdf_path, output_dir, scale=args.scale)
                if prev_rc == 0:
                    print(f":: Generated preview images in {output_dir}")
                else:
                    print(f":: Preview generation notice: {prev_out}")
            return 0
        else:
            print(f"Error: Docker compilation failed (exit code {rc}):\n{out}", file=sys.stderr)
            return rc

    # Tier 3: Syntax AST Validation Fallback
    preamble_path = Path(args.preamble).resolve() if args.preamble else None
    val_rc, val_output = run_syntax_validation(tex_path, preamble_path=preamble_path, as_json=args.json)

    if args.json:
        result = {
            "file": str(tex_path),
            "tier": 3,
            "status": "syntax_validated" if val_rc == 0 else "syntax_error",
            "syntax_validation_exit_code": val_rc,
            "validation_output": val_output,
            "compiler_available": False,
            "guidance": get_windows_installer_guidance(),
        }
        print(json.dumps(result, indent=2))
    else:
        print(":: No native LaTeX compiler or active Docker daemon detected.")
        print(f":: Executing syntax validation fallback on {tex_path.name}...")
        print(val_output)
        print()
        print(get_windows_installer_guidance())

    if val_rc == 0:
        if args.dry_run_ok:
            if not args.json:
                print("\n[OK] Document syntax is valid. Dry run passed with exit code 0.")
            return 0
        else:
            if not args.json:
                print("\n[NOTICE] Document syntax passed, but a compiler is required to generate the PDF.")
            return 1
    else:
        if not args.json:
            print("\n[ERROR] Document syntax validation failed.")
        return val_rc


if __name__ == "__main__":
    sys.exit(main())
