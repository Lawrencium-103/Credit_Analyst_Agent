"""LLM client abstraction with provider fallback.

All providers (Groq, NVIDIA NIM) expose an OpenAI-compatible API, so a single
OpenAI client per provider is enough. The :class:`FallbackClient` tries each
configured provider in order and transparently moves to the next one on failure
(rate limit, outage, unsupported parameter). Keys are read from the environment
and never persisted to disk by this codebase.

Provider discovery (env):
  - GROQ_API_KEY                -> Groq (model GROQ_MODEL, default llama-3.3-70b-versatile)
  - NVIDIA_API_KEY / NVIDIA_API_KEYS (comma/whitespace separated)
  - NVIDIA_MODEL / NVIDIA_MODELS (paired by index; default nemotron-3.5-lightning-30b)
  - NVIDIA_PROVIDERS            -> JSON list of {"key","model"} for explicit pairing
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
NVIDIA_DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


class _DROP:  # sentinel meaning "remove this kwarg for this provider"
    pass


@dataclass
class Provider:
    client: OpenAI
    model: str
    overrides: dict[str, Any] = field(default_factory=dict)


def _split(v: str | None) -> list[str]:
    if not v:
        return []
    return [x.strip() for x in v.replace("\n", ",").split(",") if x.strip()]


def _build_providers() -> list[Provider]:
    providers: list[Provider] = []

    gk = os.environ.get("GROQ_API_KEY")
    if gk:
        providers.append(Provider(
            OpenAI(api_key=gk, base_url=GROQ_BASE_URL),
            os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
            overrides={"tool_choice": "required", "parallel_tool_calls": False},
        ))

    # Explicit JSON pairing takes precedence.
    raw = os.environ.get("NVIDIA_PROVIDERS")
    if raw:
        try:
            for p in json.loads(raw):
                providers.append(Provider(
                    OpenAI(api_key=p["key"], base_url=NVIDIA_BASE_URL),
                    p.get("model", NVIDIA_DEFAULT_MODEL),
                    overrides={"tool_choice": "auto", "parallel_tool_calls": _DROP},
                ))
        except Exception:
            pass
    else:
        keys = _split(os.environ.get("NVIDIA_API_KEYS") or os.environ.get("NVIDIA_API_KEY"))
        models = _split(os.environ.get("NVIDIA_MODELS"))
        for i, k in enumerate(keys):
            m = models[i] if i < len(models) else NVIDIA_DEFAULT_MODEL
            providers.append(Provider(
                OpenAI(api_key=k, base_url=NVIDIA_BASE_URL),
                m,
                overrides={"tool_choice": "auto", "parallel_tool_calls": _DROP},
            ))

    return providers


class _Completions:
    def __init__(self, providers: list[Provider]):
        self._providers = providers

    def create(self, **kwargs: Any):
        last_err: Exception | None = None
        for p in self._providers:
            kws = dict(kwargs)
            kws["model"] = p.model
            for k, v in p.overrides.items():
                if v is _DROP:
                    kws.pop(k, None)
                else:
                    kws[k] = v
            try:
                return p.client.chat.completions.create(**kws)
            except Exception as e:  # rate limit / 4xx / network -> try next provider
                last_err = e
                continue
        raise last_err or RuntimeError("No LLM provider configured.")


class _Chat:
    def __init__(self, providers: list[Provider]):
        self.completions = _Completions(providers)


class FallbackClient:
    """OpenAI-compatible client that fails over across providers."""

    def __init__(self, providers: list[Provider]):
        self._providers = providers
        self.chat = _Chat(providers)

    @property
    def providers(self) -> list[Provider]:
        return self._providers


def get_client(api_key: str | None = None) -> FallbackClient:
    if api_key and not os.environ.get("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = api_key
    providers = _build_providers()
    if not providers:
        raise RuntimeError(
            "No LLM provider configured. Set GROQ_API_KEY and/or NVIDIA_API_KEY(S)."
        )
    return FallbackClient(providers)


def provider_summary() -> list[str]:
    return [f"{p.client.base_url.host} :: {p.model}" for p in _build_providers()]
