"""Ciel plugin system.

Lets third parties register providers, tools and agents without editing core
code, via ``importlib.metadata`` entry points (groups: ``ciel.providers``,
``ciel.tools``, ``ciel.agents``). Built-in providers/tools are auto-registered
so the framework is usable out of the box.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence

from ciel.common import CielError
from ciel.providers import AnthropicProvider, ChatProvider, OpenAICompatibleProvider, ProviderRegistry
from ciel.providers.gemini import GeminiProvider
from ciel.runtime.tools import ToolRegistry
from ciel.runtime.tools_builtins import register_builtin_tools


class PluginRegistry:
    """Central registry for discovered providers, tools and agents."""

    def __init__(self) -> None:
        self.providers: ProviderRegistry = ProviderRegistry()
        self.tools: ToolRegistry = ToolRegistry(default_toolset="builtins")
        self._agents: Dict[str, Any] = {}
        self._loaded = False

    # -- providers --------------------------------------------------------
    def register_provider(self, name: str, provider: ChatProvider, *, config: Optional[Dict[str, Any]] = None) -> None:
        self.providers.register(name, provider, config=config)

    def get_provider(self, name: str) -> ChatProvider:
        return self.providers.get(name)

    def list_providers(self) -> Sequence[str]:
        return list(self.providers.available())

    # -- tools ------------------------------------------------------------
    def register_tool(self, toolset: str, tool: Any) -> None:
        self.tools.register_tool(toolset, tool)

    def get_toolset_schema(self, name: str):
        return self.tools.get_toolset(name)

    def list_toolsets(self) -> Sequence[str]:
        return tuple(self.tools.toolset_names())

    # -- agents -----------------------------------------------------------
    def register_agent(self, name: str, agent: Any) -> None:
        self._agents[name] = agent

    def get_agent(self, name: str) -> Any:
        if name not in self._agents:
            raise CielError(f"Agent not registered: {name}")
        return self._agents[name]

    def list_agents(self) -> Sequence[str]:
        return tuple(self._agents.keys())

    # -- builtins + discovery --------------------------------------------
    def load_builtins(self) -> None:
        if self._loaded:
            return
        self.register_provider("openai", OpenAICompatibleProvider(base_url="https://api.openai.com/v1"))
        self.register_provider("anthropic", AnthropicProvider())
        self.register_provider("gemini", GeminiProvider())
        self._register_litellm()
        register_builtin_tools(self.tools)
        self._loaded = True

    def _register_litellm(self) -> None:
        """Register the LiteLLM meta-provider only if the extra is installed.

        Offline-safe: the heavy ``litellm`` dependency is never imported unless
        it is actually present, so the default framework stays lightweight.
        """
        try:
            from ciel.providers.litellm import LiteLLMProvider
        except ImportError:
            return
        # Register a placeholder factory keyed by provider name "litellm"; the
        # concrete model/api_key are supplied at use time via ProviderFactory
        # or an explicit LiteLLMProvider instance. We expose the class so
        # discover_installed / direct registration can build one on demand.
        self._litellm_provider_cls = LiteLLMProvider  # type: ignore[attr-defined]

    def discover_installed(self) -> None:
        """Discover third-party plugins via entry points (offline-safe)."""
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover - py<3.8
            return
        try:
            eps = entry_points()
            groups = ("ciel.providers", "ciel.tools", "ciel.agents")
            for group in groups:
                selected = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])
                for ep in selected:
                    try:
                        loader = ep.load()
                        if group == "ciel.providers":
                            loader(self) if _is_register_fn(loader) else self.register_provider(ep.name, loader)
                        elif group == "ciel.tools":
                            loader(self) if _is_register_fn(loader) else self.register_tool(ep.name, loader)
                        else:
                            self.register_agent(ep.name, loader)
                    except Exception:  # pragma: no cover - third-party plugin failure
                        continue
        except Exception:  # pragma: no cover - metadata unavailable
            return


def _is_register_fn(obj: Any) -> bool:
    return callable(obj) and getattr(obj, "_ciel_register", False)


def plugin_register(group: str) -> Callable[[Callable], Callable]:
    """Decorator to mark a ``def register(registry)`` function as a plugin hook."""

    def deco(func: Callable) -> Callable:
        func._ciel_register = True  # type: ignore[attr-defined]
        func._ciel_group = group  # type: ignore[attr-defined]
        return func

    return deco


_DEFAULT: Optional[PluginRegistry] = None


def default_registry() -> PluginRegistry:
    """Process-wide singleton: builtins + installed plugins loaded once."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = PluginRegistry()
        _DEFAULT.load_builtins()
        _DEFAULT.discover_installed()
    return _DEFAULT


__all__ = [
    "PluginRegistry",
    "plugin_register",
    "default_registry",
]
