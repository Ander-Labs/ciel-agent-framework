from __future__ import annotations

import os

import pytest

from ciel.credentials import (
    CredentialPoolError,
    CredentialPoolExhausted,
    CredentialPools,
    CredentialRecord,
    EnvCredentialManager,
    ProviderCredentials,
    ProviderCredentialPool,
    load_pools_from_env,
)


def _cred(provider: str, api_key: str, base_url: str = "https://api.example.com") -> ProviderCredentials:
    return ProviderCredentials(provider=provider, api_key=api_key, base_url=base_url)


def test_provider_credential_pool_round_robin() -> None:
    pool = ProviderCredentialPool(
        "openai",
        [
            _cred("openai", "sk-1"),
            _cred("openai", "sk-2"),
            _cred("openai", "sk-3"),
        ],
    )
    assert pool.next().api_key == "sk-1"
    assert pool.next().api_key == "sk-2"
    assert pool.next().api_key == "sk-3"
    assert pool.next().api_key == "sk-1"


def test_mark_exhausted_skips_agotados() -> None:
    pool = ProviderCredentialPool(
        "openai",
        [
            _cred("openai", "sk-1"),
            _cred("openai", "sk-2"),
        ],
    )
    pool.mark_exhausted(_cred("openai", "sk-1"), reason="rate-limited")

    assert pool.next().api_key == "sk-2"
    assert pool.next().api_key == "sk-2"
    assert pool.available == 1


def test_all_exhausted_raises_or_skips_with_error_policy() -> None:
    pool = ProviderCredentialPool(
        "openai",
        [_cred("openai", "sk-1"), _cred("openai", "sk-2")],
        on_exhausted="error",
    )
    pool.mark_exhausted(_cred("openai", "sk-1"))
    pool.mark_exhausted(_cred("openai", "sk-2"))

    with pytest.raises(CredentialPoolExhausted):
        pool.next()


def test_all_exhausted_returns_unavailable_on_skip_policy() -> None:
    pool = ProviderCredentialPool(
        "openai",
        [_cred("openai", "sk-1")],
        on_exhausted="skip",
    )
    pool.mark_exhausted(_cred("openai", "sk-1"))
    assert pool.available == 0
    with pytest.raises(CredentialPoolExhausted):
        pool.next()


def test_reset_restores_credential() -> None:
    pool = ProviderCredentialPool("openai", [_cred("openai", "sk-1")])
    pool.mark_exhausted(_cred("openai", "sk-1"))
    assert pool.available == 0
    pool.reset(_cred("openai", "sk-1"))
    assert pool.available == 1
    record = next(record for record in pool.iter_records() if not record.exhausted)
    assert record.value.api_key == "sk-1"


def test_env_manager_loads_credentials() -> None:
    os.environ["CIEL_OPENAI_API_KEY"] = "sk-env"
    os.environ["CIEL_OPENAI_BASE_URL"] = "https://api.openai.com/v1"
    os.environ["CIEL_OPENAI_DEFAULT_MODEL"] = "gpt-4o"
    os.environ["CIEL_OPENAI_EXTRA"] = "value"

    manager = EnvCredentialManager()
    creds = manager.load("openai")
    assert creds.provider == "openai"
    assert creds.api_key == "sk-env"
    assert creds.base_url == "https://api.openai.com/v1"
    assert creds.default_model == "gpt-4o"
    assert creds.metadata["extra"] == "value"


def test_load_pools_from_env_reads_pool_var() -> None:
    os.environ["CIEL_OPENAI_POOL"] = (
        '{"api_key": "sk-extra", "base_url": "https://api.extra/v1"}\n'
        '{"api_key": "sk-other", "base_url": "https://api.other/v1"}'
    )
    pools = load_pools_from_env(["openai"])
    pool = pools.pool("openai")
    assert pool.total == 3
    assert pool.next().api_key == "sk-env"
    assert pool.next().api_key == "sk-extra"
    assert pool.next().api_key == "sk-other"


def test_credential_pools_registry() -> None:
    pools = CredentialPools()
    pool = ProviderCredentialPool("anthropic", [_cred("anthropic", "sk-anthro")])
    pools.register(pool)
    assert pools.providers() == ["anthropic"]
    assert pools.next("anthropic").api_key == "sk-anthro"
