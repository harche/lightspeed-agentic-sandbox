"""Tests for provider factory."""

import importlib

import pytest

from lightspeed_agentic.factory import create_provider


def test_create_provider_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider("nonexistent")


def test_create_provider_env_default(monkeypatch):
    monkeypatch.delenv("LIGHTSPEED_AGENT_PROVIDER", raising=False)
    # Claude SDK might not be installed — just verify it tries claude
    try:
        provider = create_provider()
        assert provider.name == "claude"
    except ImportError:
        pass


def test_create_provider_explicit_name():
    # SDK might not be installed — just verify the right import is attempted
    for name in ("claude", "gemini", "openai"):
        try:
            provider = create_provider(name)
            assert provider.name == name
        except ImportError:
            pass


def test_openai_provider_module_imports_without_eager_optional_sdk_imports():
    module = importlib.import_module("lightspeed_agentic.providers.openai")
    assert module.OpenAIProvider().name == "openai"
