from __future__ import annotations

from typing import Any, Dict

from fastapi.testclient import TestClient

from ciel.acp import AskRequest, AskResponse, _build_runtime, create_app


def test_build_runtime_uses_openai_compat_provider() -> None:
    runtime = _build_runtime(base_url="http://localhost:1234/v1", api_key="k", default_model="local")
    assert runtime.provider.provider_name == "openai_compat"
    assert runtime.provider.default_model == "local"
    toolset = runtime.dispatcher.default_toolset
    assert toolset == "demo"
