"""Eval runner — POSTs to /v1/agent/analyze and captures the response."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class AnalyzeResult:
    provider: str = ""
    success: bool = False
    summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    latency_seconds: float = 0.0
    error: str | None = None


async def run_analyze(
    server_url: str,
    query: str,
    system_prompt: str = "You are a helpful assistant.",
    output_schema: dict | None = None,
) -> AnalyzeResult:
    result = AnalyzeResult()
    start = time.monotonic()

    body: dict[str, Any] = {
        "query": query,
        "systemPrompt": system_prompt,
    }
    if output_schema:
        body["outputSchema"] = output_schema

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(f"{server_url}/v1/agent/analyze", json=body)
            resp.raise_for_status()
            data = resp.json()

        result.success = data.get("success", False)
        result.summary = data.get("summary", "")
        result.raw = data
    except Exception as e:
        result.error = str(e)

    result.latency_seconds = time.monotonic() - start
    return result


def assert_tool_token(
    eval_workspace: Path,
    token_file_name: str,
    result: AnalyzeResult,
    provider_name: str,
    script_name: str,
) -> None:
    matches = list(eval_workspace.rglob(token_file_name))
    if not matches:
        raise AssertionError(
            f"{provider_name} did not run {script_name} "
            f"(no {token_file_name} found in {eval_workspace})"
        )

    response_text = json.dumps(result.raw)
    tokens = matches[0].read_text().strip().splitlines()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        assert token in response_text, (
            f"{provider_name} did not report verification token {token} from {script_name}. "
            f"response={result.summary[:200]}"
        )
