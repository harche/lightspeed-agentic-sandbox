"""Shared tool executors and utilities for non-Claude providers."""

from __future__ import annotations

import glob as globmod
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

DEFAULT_ALLOWED_TOOLS = ["Bash", "Read", "Glob", "Grep", "Skill"]


def parse_bash_restrictions(allowed_tools: list[str]) -> tuple[bool, list[str] | None]:
    bash_entries = [t for t in allowed_tools if t == "Bash" or t.startswith("Bash(")]
    if not bash_entries:
        return False, []
    if "Bash" in bash_entries or "Bash(*)" in bash_entries:
        return True, None
    patterns: list[str] = []
    for entry in bash_entries:
        m = re.match(r"^Bash\((\w+):\*\)$", entry)
        if m:
            patterns.append(m.group(1))
    return len(patterns) > 0, patterns


def validate_bash_command(command: str, patterns: list[str] | None) -> bool:
    if patterns is None:
        return True
    trimmed = command.lstrip()
    return any(trimmed.startswith(p + " ") or trimmed == p for p in patterns)


def execute_bash(command: str, cwd: str, patterns: list[str] | None, timeout: int = 120) -> str:
    if not validate_bash_command(command, patterns):
        return f"Error: Command not allowed. Permitted prefixes: {', '.join(patterns or [])}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=max(timeout, 1),
            executable="/bin/bash",
        )
        if result.returncode == 0:
            return result.stdout
        return f"Exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def execute_read(file_path: str, offset: int = 0, limit: int | None = None) -> str:
    try:
        with open(file_path) as f:
            lines: list[str] = []
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if limit is not None and len(lines) >= limit:
                    break
                lines.append(f"{offset + len(lines) + 1}\t{line.rstrip(chr(10))}")
            return "\n".join(lines)
    except Exception as e:
        return f"Error reading file: {e}"


def execute_write(file_path: str, content: str) -> str:
    try:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


_MAX_GLOB_RESULTS = 1000


def execute_glob(pattern: str, cwd: str, path: str | None = None) -> str:
    try:
        search_dir = path or cwd
        matches = sorted(globmod.glob(pattern, root_dir=search_dir, recursive=True))
        matches = [os.path.join(search_dir, m) for m in matches]
        if not matches:
            return "No files found"
        if len(matches) > _MAX_GLOB_RESULTS:
            return (
                "\n".join(matches[:_MAX_GLOB_RESULTS])
                + f"\n... (truncated, {len(matches)} total matches)"
            )
        return "\n".join(matches)
    except Exception as e:
        return f"Error: {e}"


def execute_grep(
    pattern: str, cwd: str, path: str | None = None, file_glob: str | None = None
) -> str:
    try:
        args = ["rg", "--no-heading", "--line-number"]
        if file_glob:
            args.extend(["--glob", file_glob])
        args.append(pattern)
        args.append(path or cwd)
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
        if result.returncode == 1:
            return "No matches found"
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        return result.stdout
    except Exception as e:
        return f"Error: {e}"


def build_gemini_tools(
    allowed_tools: list[str], cwd: str
) -> list[Callable[..., str]]:
    bash_allowed, patterns = parse_bash_restrictions(allowed_tools)
    tools: list[Callable[..., str]] = []

    if bash_allowed:

        def run_bash(command: str, timeout: int = 120) -> str:
            """Execute a bash command and return its output (stdout/stderr)."""
            return execute_bash(command, cwd, patterns, timeout)

        tools.append(run_bash)

    if "Read" in allowed_tools:

        def read_file(file_path: str, offset: int = 0, limit: int = 0) -> str:
            """Read a file and return its contents with line numbers."""
            return execute_read(file_path, offset, limit or None)

        tools.append(read_file)

    if "Write" in allowed_tools:

        def write_file(file_path: str, content: str) -> str:
            """Write content to a file, creating directories as needed."""
            return execute_write(file_path, content)

        tools.append(write_file)

    if "Glob" in allowed_tools:

        def glob_files(pattern: str, path: str = "") -> str:
            """Find files matching a glob pattern."""
            return execute_glob(pattern, cwd, path or None)

        tools.append(glob_files)

    if "Grep" in allowed_tools:

        def grep_files(pattern: str, path: str = "", file_glob: str = "") -> str:
            """Search for a regex pattern in files using ripgrep."""
            return execute_grep(pattern, cwd, path or None, file_glob or None)

        tools.append(grep_files)

    return tools


def resolve_skills_dir(skills_dir: str) -> str:
    skills_subdir = os.path.join(skills_dir, "skills")
    return skills_subdir if os.path.isdir(skills_subdir) else skills_dir



def discover_openai_skills(skills_dir: str) -> list[dict[str, str]]:
    skills: list[dict[str, str]] = []
    target_dir = resolve_skills_dir(skills_dir)

    try:
        entries = sorted(os.listdir(target_dir))
    except OSError:
        return skills

    for entry in entries:
        skill_md = os.path.join(target_dir, entry, "SKILL.md")
        try:
            content = Path(skill_md).read_text()
        except OSError:
            continue

        name = entry
        description = f"Skill: {entry}"
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped[5:].strip().strip("'\"")
            elif stripped.startswith("description:"):
                description = stripped[12:].strip().strip("'\"")

        skills.append({"name": name, "description": description, "path": os.path.join(target_dir, entry)})

    return skills
