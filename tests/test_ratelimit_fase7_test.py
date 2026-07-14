"""Tests de TenantRateLimiter (Fase 7) — OFFLINE-SAFE, sin red."""

from ciel.enterprise.ratelimit import RateLimitError, TenantRateLimiter


def test_consume_permite_n_y_n_mas_1_lanza():
    lim = TenantRateLimiter(quotas={("t1", "u1"): 3}, window_s=60)
    for _ in range(3):
        lim.consume(tenant_id="t1", user="u1")
    try:
        lim.consume(tenant_id="t1", user="u1")
    except RateLimitError:
        return
    raise AssertionError("se esperaba RateLimitError en la petición N+1")


def test_check_false_al_agotar():
    lim = TenantRateLimiter(quotas={("t1", "u1"): 2}, window_s=60)
    assert lim.check(tenant_id="t1", user="u1") is True
    lim.consume(tenant_id="t1", user="u1")
    lim.consume(tenant_id="t1", user="u1")
    assert lim.check(tenant_id="t1", user="u1") is False


def test_remaining_decrece():
    lim = TenantRateLimiter(quotas={("t1", "u1"): 3}, window_s=60)
    assert lim.remaining(tenant_id="t1", user="u1") == 3
    lim.consume(tenant_id="t1", user="u1")
    assert lim.remaining(tenant_id="t1", user="u1") == 2
    lim.consume(tenant_id="t1", user="u1")
    assert lim.remaining(tenant_id="t1", user="u1") == 1
    lim.consume(tenant_id="t1", user="u1")
    assert lim.remaining(tenant_id="t1", user="u1") == 0


def test_reset_restaura():
    lim = TenantRateLimiter(quotas={("t1", "u1"): 2}, window_s=60)
    lim.consume(tenant_id="t1", user="u1")
    lim.consume(tenant_id="t1", user="u1")
    assert lim.remaining(tenant_id="t1", user="u1") == 0
    assert lim.check(tenant_id="t1", user="u1") is False
    lim.reset(tenant_id="t1", user="u1")
    assert lim.remaining(tenant_id="t1", user="u1") == 2
    assert lim.check(tenant_id="t1", user="u1") is True


def test_cuota_por_tenant_aisla_de_otro_tenant():
    lim = TenantRateLimiter(
        quotas={("t1", "*"): 3, ("t2", "*"): 3}, window_s=60
    )
    for _ in range(3):
        lim.consume(tenant_id="t1", user="u1")
    # t1 agotado
    assert lim.check(tenant_id="t1", user="u1") is False
    # t2 no debe verse afectado
    assert lim.check(tenant_id="t2", user="u1") is True
    assert lim.remaining(tenant_id="t2", user="u1") == 3
    lim.consume(tenant_id="t2", user="u1")
    lim.consume(tenant_id="t2", user="u1")
    lim.consume(tenant_id="t2", user="u1")
    try:
        lim.consume(tenant_id="t2", user="u1")
    except RateLimitError:
        return
    raise AssertionError("se esperaba RateLimitError en t2 tras agotar su cuota")


def test_cuota_especifica_prevalece_sobre_tenant_wildcard():
    lim = TenantRateLimiter(
        quotas={("t1", "*"): 5, ("t1", "u1"): 2}, window_s=60
    )
    # u1 usa su cuota específica (2), no la de tenant (5)
    for _ in range(2):
        lim.consume(tenant_id="t1", user="u1")
    try:
        lim.consume(tenant_id="t1", user="u1")
    except RateLimitError:
        pass
    else:
        raise AssertionError("u1 debería respetar su cuota específica de 2")
    # otro usuario del mismo tenant usa la cuota de tenant (5)
    assert lim.remaining(tenant_id="t1", user="u2") == 5
    for _ in range(5):
        lim.consume(tenant_id="t1", user="u2")
    assert lim.check(tenant_id="t1", user="u2") is False
