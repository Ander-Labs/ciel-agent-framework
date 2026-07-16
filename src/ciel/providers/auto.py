"""Auto-provider resolution for ``ciel.Agent`` (Developer Experience II).

Lets users write ``ciel.Agent(model="gpt-4o-mini")`` and have Ciel pick the
right provider and read the matching API key from the environment, instead of
having to construct a provider object by hand. Explicit ``provider=`` always
wins over ``model=`` inference.

Offline-safe: if the inferred provider requires an API key that is not present
in the environment, the provider is still constructed but will raise a clear
``ProviderError`` only when a network call is attempted (mirroring the existing
provider contract). No network access happens at construction time.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from ciel.providers import ChatProvider

# Model id prefixes -> (env var holding the API key, provider label).
_MODEL_PREFIXES: Tuple[Tuple[str, str, str], ...] = (
    ("gpt-", "OPENAI_API_KEY", "openai"),
    ("o1", "OPENAI_API_KEY", "openai"),
    ("o3", "OPENAI_API_KEY", "openai"),
    ("claude-", "ANTHROPIC_API_KEY", "anthropic"),
    ("gemini-", "GEMINI_API_KEY", "gemini"),
    ("models/", "GEMINI_API_KEY", "gemini"),
)


def _resolve_prefix(model: str) -> Optional[str]:
    """Return the provider label inferred from a model id, or None."""
    lowered = model.lower()
    for prefix, _env, label in _MODEL_PREFIXES:
        if lowered.startswith(prefix):
            return label
    return None


def _default_base_url(label: str) -> Optional[str]:
    if label == "openai":
        return "https://api.openai.com/v1"
    # Anthropic / Gemini providers carry their own default base_url.
    return None


def auto_provider(model: Optional[str]) -> ChatProvider:
    """Build a provider from a model id using the cheapest inference.

    Resolution order:
      1. ``gpt-*`` / ``o1*`` / ``o3*``  -> OpenAI-compatible (reads ``OPENAI_API_KEY``)
      2. ``claude-*``                   -> Anthropic (reads ``ANTHROPIC_API_KEY``)
      3. ``gemini-*`` / ``models/*``    -> Gemini (reads ``GEMINI_API_KEY``)
      4. otherwise                      -> OpenAI-compatible with no key
         (so ``gpt-`` style ids keep working; other ids fail at call time with a
         clear provider error rather than a silent misconfiguration)

    API keys are read from the environment (``os.environ``) and never logged.
    """
    label = _resolve_prefix(model) if model else None
    if label is None:
        label = "openai"

    if label == "anthropic":
        # Local import avoids a hard dependency at module import time.
        from ciel.providers import AnthropicProvider

        return AnthropicProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    if label == "gemini":
        from ciel.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=os.environ.get("GEMINI_API_KEY"))

    # openai-compatible (default)
    from ciel.providers import OpenAICompatibleProvider

    base_url = _default_base_url("openai")
    return OpenAICompatibleProvider(
        base_url=base_url,  # type: ignore[arg-type]
        api_key=os.environ.get("OPENAI_API_KEY"),
        default_model=model,
    )
