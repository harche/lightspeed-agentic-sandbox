"""Shared utilities for provider implementations."""

from __future__ import annotations

import os

DEFAULT_ALLOWED_TOOLS = ["Bash", "Read", "Glob", "Grep", "Skill"]


def resolve_skills_dir(skills_dir: str) -> str:
    for candidate in [
        os.path.join(skills_dir, "skills"),
        os.path.join(skills_dir, ".claude", "skills"),
    ]:
        if os.path.isdir(candidate):
            return candidate
    return skills_dir
