"""Gemini provider — wraps google-adk.

Uses native ExecuteBashTool for shell execution and SkillToolset for
skill discovery. The SDK handles tool registration and command execution.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from collections.abc import AsyncIterator
from typing import Any

import pydantic

from lightspeed_agentic.tools import resolve_skills_dir
from lightspeed_agentic.types import (
    TOOL_INPUT_MAX_CHARS,
    TOOL_OUTPUT_MAX_CHARS,
    AgentProvider,
    ContentBlockStopEvent,
    ProviderEvent,
    ProviderQueryOptions,
    ResultEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    stringify,
)

logger = logging.getLogger(__name__)

_JSON_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _json_schema_to_pydantic(schema: dict[str, Any], name: str = "OutputModel") -> type[pydantic.BaseModel]:
    """Convert a JSON Schema dict to a dynamic Pydantic model.

    The ADK's SetModelResponseTool crashes on raw dicts (unhashable type)
    but works fine with Pydantic BaseModel subclasses.
    """
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}

    for field_name, field_schema in props.items():
        field_type = _resolve_field_type(field_schema, field_name)
        if field_name in required:
            fields[field_name] = (field_type, ...)
        else:
            fields[field_name] = (field_type | None, None)

    return pydantic.create_model(name, **fields)


def _resolve_field_type(schema: dict[str, Any], name: str) -> type:
    json_type = schema.get("type", "string")

    if json_type == "object":
        return _json_schema_to_pydantic(schema, name.title().replace("_", ""))

    if json_type == "array":
        items = schema.get("items", {})
        inner = _resolve_field_type(items, name + "Item")
        return list[inner]  # type: ignore[valid-type]

    if "enum" in schema:
        from enum import Enum
        members = {v.upper().replace(" ", "_"): v for v in schema["enum"]}
        return Enum(name.title().replace("_", "") + "Enum", members)  # type: ignore[return-value]

    return _JSON_SCHEMA_TYPE_MAP.get(json_type, str)


def _load_skills_toolset(skills_dir: str) -> Any:
    try:
        from google.adk.skills import list_skills_in_dir
        from google.adk.tools.skill_toolset import SkillToolset

        target = pathlib.Path(resolve_skills_dir(skills_dir))
        skills = list_skills_in_dir(target)
        if skills:
            return SkillToolset(skills=skills)
    except Exception as e:
        logger.debug("Failed to load skills toolset from %s: %s", skills_dir, e)
    return None


class GeminiProvider(AgentProvider):
    def __init__(self) -> None:
        self._cached_skills: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "gemini"

    async def query(self, options: ProviderQueryOptions) -> AsyncIterator[ProviderEvent]:
        from google.adk.agents import Agent, RunConfig
        from google.adk.agents.run_config import StreamingMode
        from google.adk.features import FeatureName, override_feature_enabled
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools import exit_loop, google_search, url_context
        from google.adk.tools.bash_tool import ExecuteBashTool
        from google.adk.tools.tool_confirmation import ToolConfirmation
        from google.genai import types

        workspace = pathlib.Path(options.cwd)

        bash = ExecuteBashTool(workspace=workspace)
        _orig_run = bash.run_async

        async def _auto_confirm_run(*, args: Any, tool_context: Any) -> Any:
            tool_context.tool_confirmation = ToolConfirmation(confirmed=True)
            return await _orig_run(args=args, tool_context=tool_context)

        bash.run_async = _auto_confirm_run

        # TODO: investigate more ADK built-in tools (load_artifacts, load_memory, computer_use, file_search, mcp_servers)
        tools: list[Any] = [
            bash,
            google_search,
            url_context,
            exit_loop,
        ]

        if options.cwd not in self._cached_skills:
            self._cached_skills[options.cwd] = _load_skills_toolset(options.cwd)
        skill_toolset = self._cached_skills[options.cwd]
        if skill_toolset is not None:
            tools.append(skill_toolset)

        agent_kwargs: dict[str, Any] = {
            "name": "lightspeed",
            "model": options.model,
            "instruction": options.system_prompt,
            "tools": tools,
            "generate_content_config": types.GenerateContentConfig(
                tool_config=types.ToolConfig(
                    include_server_side_tool_invocations=True,
                ),
            ),
        }

        if options.output_schema:
            # TODO: output_schema disables tools in ADK — workaround with strict instruction.
            # https://github.com/google/adk-python/issues/5054
            # https://github.com/google/adk-python/issues/5054#issuecomment-4160655023
            if isinstance(options.output_schema, dict):
                agent_kwargs["output_schema"] = _json_schema_to_pydantic(options.output_schema)
            else:
                agent_kwargs["output_schema"] = options.output_schema
            # TODO: remove this prompt workaround once ADK supports output_schema + tools properly.
            # https://github.com/google/adk-python/issues/5054#issuecomment-4160655023
            agent_kwargs["instruction"] = (
                (agent_kwargs.get("instruction") or "")
                + "\n\nCRITICAL: After completing all tool calls, you MUST call the "
                "set_model_response tool exactly once as your FINAL action. "
                "Do NOT respond with plain text. Do NOT call any other tools "
                "after set_model_response. This is the ONLY way to complete the task."
            )

        agent = Agent(**agent_kwargs)

        session_service = InMemorySessionService()
        runner = Runner(
            app_name="lightspeed",
            agent=agent,
            session_service=session_service,
        )

        user_id = f"agent-{int(time.time())}"
        session = await session_service.create_session(
            app_name="lightspeed", user_id=user_id
        )

        streaming_mode = StreamingMode.SSE if options.stream else StreamingMode.NONE
        run_config = RunConfig(
            streaming_mode=streaming_mode,
            max_llm_calls=options.max_turns,
        )

        result_text = ""
        total_input_tokens = 0
        total_output_tokens = 0

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=options.prompt)],
            ),
            run_config=run_config,
        ):
            if not event.content or not event.content.parts:
                continue

            is_partial = getattr(event, "partial", False)

            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    if options.stream and is_partial:
                        yield TextDeltaEvent(text=part.text)
                    if not is_partial and not event.get_function_calls():
                        result_text = part.text

                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    yield ToolCallEvent(
                        name=fc.name,
                        input=json.dumps(dict(fc.args) if fc.args else {})[:TOOL_INPUT_MAX_CHARS],
                    )

                if hasattr(part, "function_response") and part.function_response:
                    fr = part.function_response
                    yield ToolResultEvent(output=stringify(fr.response)[:TOOL_OUTPUT_MAX_CHARS])

            usage = getattr(event, "usage_metadata", None)
            if usage:
                total_input_tokens = getattr(usage, "prompt_token_count", 0) or 0
                total_output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        yield ContentBlockStopEvent()

        yield ResultEvent(
            text=result_text,
            cost_usd=0,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
