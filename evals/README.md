# Evals

End-to-end evaluations that run against the production container image. Each test is independent and runs in parallel.

> **Note:** On macOS, the eval suite runs all 60 tests in parallel to save time, which spikes memory usage. Ensure the podman machine has at least 8GB: check with `podman info | grep memTotal`, resize with `podman machine set --memory 8192`.

## Contents

- [Quick Start](#quick-start)
- [Providers & Models](#providers--models)
- [Test Categories](#test-categories)
- [Credentials](#credentials)
- [Running Evals](#running-evals)
- [Reports](#reports)
- [Adding Tests](#adding-tests)

## Quick Start

```bash
make eval
```

This builds the production container image, mounts `evals/`, forwards credentials, and runs all 60 tests in parallel.

## Providers & Models

| Provider | Default Model | Override Env Var |
|---|---|---|
| `claude` | `claude-sonnet-4-6` | `ANTHROPIC_MODEL` |
| `gemini` | `gemini-3.1-pro-preview` | `GEMINI_MODEL` |
| `openai` | `gpt-5.4` | `OPENAI_MODEL` |
| `deepagents` | `claude-opus-4-6` | `DEEPAGENTS_MODEL` |
| `deepagents-gemini` | `gemini-3.1-pro-preview` | `DEEPAGENTS_GEMINI_MODEL` |
| `deepagents-openai` | `gpt-5.4` | `DEEPAGENTS_OPENAI_MODEL` |

The `deepagents-*` variants run the same deepagents provider (langchain) with different LLM backends.

## Test Categories

10 tests per provider, 60 total:

| Category | Tests | What it validates |
|---|---|---|
| **Basic Query** | `test_basic_response`, `test_cost_tracking` | Prompt/response sanity and token usage reporting |
| **Structured Output** | `test_analysis_schema`, `test_calculation_schema`, `test_schema_with_enum` | JSON schema enforcement — nested objects, required fields, enum constraints |
| **Skill Invocation** | `test_calculator_skill`, `test_lookup_skill` | Model discovers and uses skills from `workspace/skills/` |
| **Tool Usage** | `test_greet_tool`, `test_compute_tool_with_structured_output`, `test_lookup_data_tool` | Model invokes bash scripts from `workspace/tools/` and uses their output |

## Credentials

Providers without valid credentials are automatically skipped. Credential detection order per provider:

| Provider | Primary | Fallbacks |
|---|---|---|
| `claude` | `ANTHROPIC_API_KEY` | Vertex AI (`CLAUDE_CODE_USE_VERTEX=1` + gcloud ADC), Bedrock (`CLAUDE_CODE_USE_BEDROCK=1` + AWS creds) |
| `gemini` | `GOOGLE_API_KEY` | `GEMINI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS` file, gcloud ADC |
| `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` (keyless endpoints) |
| `deepagents` | Depends on model | Checks credentials matching the configured `DEEPAGENTS_MODEL` |
| `deepagents-gemini` | Same as `gemini` | — |
| `deepagents-openai` | Same as `openai` | — |

## Running Evals

Evals always run inside the production container image. Use `EVAL_ARGS` to pass pytest flags.

```bash
# All providers
make eval

# Single provider
make eval EVAL_ARGS="-k claude"

# Single test category
make eval EVAL_ARGS="-k structured_output"

# Single test + single provider
make eval EVAL_ARGS="-k 'test_greet_tool and gemini'"

# Override model for a run
ANTHROPIC_MODEL=claude-opus-4-6 make eval EVAL_ARGS="-k claude"

# Sequential with stdout (debugging)
make eval EVAL_ARGS="-n0 -s"
```

## Reports

Generate a JSON report at `evals/report.json`:

```bash
make eval-report
```

## Adding Tests

```
evals/
├── test_basic_query.py          # basic prompt/response tests
├── test_skill_invocation.py     # skill discovery and usage tests
├── test_structured_output.py    # JSON schema enforcement tests
├── test_tool_usage.py           # bash tool invocation tests
├── schemas.py                   # reusable JSON Schema definitions
└── workspace/
    ├── skills/                  # dummy skills (SKILL.md files)
    └── tools/                   # bash scripts the model invokes
```

Everything a test needs is plain text and provider-agnostic:

- **Prompts** — plain text strings for the task (`prompt`) and role/behavior (`system_prompt`). Nothing provider-specific.
- **Skills** — add a `SKILL.md` under `workspace/skills/<name>/`. Each provider's SDK discovers and loads them automatically.
- **Tools** — add a bash script under `workspace/tools/`. The model invokes them via shell.
- **Schemas** — JSON Schema dicts in `schemas.py`. When passed as `output_schema`, the provider enforces structured JSON output using its native mechanism.

Tests are parametrized across all providers automatically — add a test once and it runs for all 6 providers.
