"""Named, inspectable system configurations; adding a preset adds no orchestration."""

from __future__ import annotations

import re
from copy import deepcopy
from importlib import metadata
from typing import Any, cast

from companybench.extensions import load_factory
from companybench.providers.anthropic import AnthropicProvider
from companybench.providers.avina import AvinaProvider
from companybench.providers.base import ImmediateProvider, JobProvider, Provider
from companybench.providers.exa import ExaAgentProvider, ExaWebsetsProvider
from companybench.providers.gemini import GeminiProvider
from companybench.providers.openai import OpenAIProvider
from companybench.providers.parallel import ParallelProvider
from companybench.providers.specstream import SpecStreamProvider
from companybench.providers.xai import XAIProvider

PRESETS: dict[str, dict[str, Any]] = {
    "avina": {
        "adapter": "avina",
        "description": "Avina public v1 company signals",
        "api_key_env": "AVINA_API_KEY",
        "options": {},
    },
    "exa-websets": {
        "adapter": "exa-websets",
        "description": "Exa Websets company discovery",
        "api_key_env": "EXA_API_KEY",
        "options": {},
    },
    "exa-agent-high": {
        "adapter": "exa-agent",
        "description": "Exa Agent High",
        "api_key_env": "EXA_API_KEY",
        "options": {"effort": "high"},
    },
    "exa-agent-auto": {
        "adapter": "exa-agent",
        "description": "Exa Agent Auto",
        "api_key_env": "EXA_API_KEY",
        "options": {"effort": "auto"},
    },
    "parallel-core": {
        "adapter": "parallel",
        "description": "Parallel FindAll Core",
        "api_key_env": "PARALLEL_API_KEY",
        "options": {"generator": "core"},
    },
    "parallel-pro": {
        "adapter": "parallel",
        "description": "Parallel FindAll Pro",
        "api_key_env": "PARALLEL_API_KEY",
        "options": {"generator": "pro"},
    },
    "specstream": {
        "adapter": "specstream",
        "description": "SpecStream Deep Search",
        "api_key_env": "SPECSTREAM_API_KEY",
        "options": {},
    },
    "openai-sol-medium": {
        "adapter": "openai",
        "description": "GPT-6.1 Sol, medium effort",
        "api_key_env": "OPENAI_API_KEY",
        "options": {
            "model": "gpt-6.1-sol",
            "effort": "medium",
            "max_output_tokens": 128000,
            "search_context_size": "medium",
        },
    },
    "openai-astra-max": {
        "adapter": "openai",
        "description": "GPT-6 Astra, maximum effort",
        "api_key_env": "OPENAI_API_KEY",
        "options": {
            "model": "gpt-6-astra",
            "effort": "max",
            "max_output_tokens": 128000,
            "search_context_size": "high",
            "return_token_budget": "unlimited",
        },
    },
    "claude-sonnet-medium": {
        "adapter": "claude",
        "description": "Claude Sonnet 5.5, medium effort",
        "api_key_env": "ANTHROPIC_API_KEY",
        "options": {"model": "claude-sonnet-5-5", "effort": "medium", "max_output_tokens": 128000},
    },
    "claude-opus-max": {
        "adapter": "claude",
        "description": "Claude Opus 5.5, maximum effort",
        "api_key_env": "ANTHROPIC_API_KEY",
        "options": {"model": "claude-opus-5-5", "effort": "max", "max_output_tokens": 128000},
    },
    "gemini-flash-high": {
        "adapter": "gemini",
        "description": "Gemini 3.8 Flash, high thinking",
        "api_key_env": "GEMINI_API_KEY",
        "options": {"model": "gemini-3.8-flash", "effort": "high", "max_output_tokens": 65536},
    },
    "gemini-pro-high": {
        "adapter": "gemini",
        "description": "Gemini 3.1 Pro Preview, high thinking",
        "api_key_env": "GEMINI_API_KEY",
        "options": {
            "model": "gemini-3.1-pro-preview",
            "effort": "high",
            "max_output_tokens": 65536,
        },
    },
    "grok-low": {
        "adapter": "grok",
        "description": "Grok 4.7, low effort",
        "api_key_env": "XAI_API_KEY",
        "options": {"model": "grok-4.7", "effort": "low", "max_output_tokens": 262144},
    },
    "grok-xhigh": {
        "adapter": "grok",
        "description": "Grok 4.7, highest effort",
        "api_key_env": "XAI_API_KEY",
        "options": {"model": "grok-4.7", "effort": "xhigh", "max_output_tokens": 262144},
    },
}
ADAPTERS = {
    "avina": AvinaProvider,
    "exa-websets": ExaWebsetsProvider,
    "exa-agent": ExaAgentProvider,
    "parallel": ParallelProvider,
    "specstream": SpecStreamProvider,
    "openai": OpenAIProvider,
    "claude": AnthropicProvider,
    "gemini": GeminiProvider,
    "grok": XAIProvider,
}


def provider_names() -> list[str]:
    """Discover entry-point names without importing their code or reading keys."""
    return [*PRESETS, *_entry_points()]


def _entry_points() -> dict[str, metadata.EntryPoint]:
    found: dict[str, metadata.EntryPoint] = {}
    for point in metadata.entry_points(group="companybench.providers"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", point.name):
            raise ValueError(f"Invalid provider entry-point name: {point.name!r}")
        if point.name in PRESETS or point.name in found:
            raise ValueError(f"Provider entry-point collision: {point.name!r}")
        found[point.name] = point
    return found


def resolve(name: str, options: dict[str, Any] | None = None) -> Provider:
    points = _entry_points()
    if name in PRESETS:
        preset = deepcopy(PRESETS[name])
        settings = {**preset["options"], **(options or {})}
        return cast(Provider, ADAPTERS[preset["adapter"]](name=name, **settings))
    if name in points:
        factory = points[name].load()
    elif ":" in name:
        factory = load_factory(name)
    else:
        raise ValueError(f"Unknown provider {name!r}. Available: {', '.join([*PRESETS, *points])}")
    if not callable(factory):
        raise TypeError(f"Provider factory {name!r} is not callable")
    provider = factory(**deepcopy(options or {}))
    if not isinstance(provider, (ImmediateProvider, JobProvider)):
        raise TypeError(f"Provider factory {name!r} must return ImmediateProvider or JobProvider")
    return provider
