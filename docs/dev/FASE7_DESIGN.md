# Ciel — Diseño Fase 7 (Enterprise duro)

Fecha: 2026-07-13. Base verificada: **165 passed, 1 skipped** (Fases 0–6 CERRADAS).
Esta fase entrega el **enterprise duro** que el Prompt.md pide: RBAC/OIDC, audit
inmutable (hash-chained), cost governance, secrets (Vault/K8s), y rate-limit +
cuotas transversales. Todo OFFLINE-SAFE y sin dependencias duras (OIDC/Vault son
backends opcionales con fallback a env; si falta el extra, el módulo importa y el
verificador/backend lanza `FeatureUnavailable` en lugar de romper el import).

## 1. Paquete `ciel.enterprise`

Nuevo paquete que agrupa los 5 módulos. No toca `observability.audit` (lo extiende
vía herencia) ni el `Supervisor` (el cost governor es una capa transversal que el
gateway/runtime pueden consultar; no acopla el supervisor).

```
src/ciel/enterprise/
  __init__.py      # re-exporta todo
  rbac.py          # RBACEngine + OIDCVerifier
  audit.py         # HashChainAuditSink (hash-chained, append-only)
  cost.py          # CostGovernor (presupuesto/alertas/corte)
  secrets.py       # SecretStore + backends (env/vault/k8s)
  ratelimit.py     # TenantRateLimiter (cuotas transversales)
```

CLI:
```
src/ciel/cli/rbac.py   # ciel rbac check|assign|list-roles
src/ciel/cli/cost.py   # ciel cost record|status|check
```

## 2. Contratos (FIRMAS EXACTAS — fuente de verdad para los subagentes)

### 2.1 `rbac.py`
```python
@dataclass(frozen=True)
class Role:
    name: str
    permissions: frozenset[str]            # acciones tipo "agent:run", "tools:exec", "admin:*"

@dataclass
class Assignment:
    subject: str
    role: str
    tenant_id: Optional[str] = None

class RBACError(Exception): ...
class FeatureUnavailable(Exception): ...    # OIDC sin deps disponibles

DEFAULT_ROLES: dict[str, Role] = {
    "admin":    Role("admin", frozenset({"agent:*", "tools:*", "admin:*", "board:*", "cost:*"})),
    "operator": Role("operator", frozenset({"agent:run", "tools:exec", "board:write"})),
    "viewer":   Role("viewer", frozenset({"agent:read", "board:read"})),
}

class RBACEngine:
    def __init__(self, *, tenant_id=None, roles=None, assignments=None):
        # roles: dict[str, Role] (mezcla DEFAULT_ROLES con los dados)
        # assignments: Iterable[Assignment] o dict[(tenant_id or "*", subject)] -> role
    def assign(self, subject: str, role_name: str, *, tenant_id=None) -> None
    def revoke(self, subject: str, *, tenant_id=None) -> None
    def role_of(self, subject: str, *, tenant_id=None) -> Optional[str]
    def has_permission(self, subject: str, action: str, *, tenant_id=None) -> bool
    def check(self, subject: str, action: str, *, tenant_id=None) -> None  # RBACError si deniega
    def list_roles(self) -> list[str]
    def snapshot(self) -> dict
    @classmethod
    def from_snapshot(cls, data: dict) -> "RBACEngine"

class OIDCVerifier:
    OIDC_AVAILABLE: bool                    # False si faltan PyJWT/cryptography
    def __init__(self, *, issuer=None, audience=None, jwks_uri=None, public_key=None): ...
    def verify(self, token: str) -> dict:   # claims {sub, roles, tenant_id, ...}; FeatureUnavailable si !OIDC_AVAILABLE
```
Regla de permisos: `action` coincide si hay un permiso exacto, o un prefijo
`"category:*"` (p. ej. `"agent:*"` autoriza `"agent:run"`). Búsqueda en orden:
asignación específica de tenant > asignación global (`"*"`) > denegado.

### 2.2 `audit.py`
```python
class HashChainAuditSink(JsonlAuditSink):
    # hereda JsonlAuditSink (observability.__init__) y su write(); añade hash-chain
    def __init__(self, base_path: Path | str = "audit", *, tenant_id=None): ...
    async def write(self, event: AuditEvent) -> None:
        # calcula hash = sha256(prev_hash || canonical_json(event)); guarda
        # "prev_hash" y "hash" en el payload jsonl. El primer evento usa prev_hash="".
    async def verify(self, *, tenant_id=None, session_id=None) -> bool:
        # recorre el jsonl y valida cada hash contra el anterior; False si se alteró.
    def last_hash(self, *, tenant_id, session_id) -> Optional[str]
```
Importante: respetar la ruta de partición de `JsonlAuditSink._jsonl_path` (tenant/session)
para no romper la escritura. El hash se mete en el `payload` que ya serializa el padre.
Como `JsonlAuditSink.write` ya construye el payload, el hijo debe sobreescribir `write`
reconstruyendo el payload con `prev_hash`/`hash` y reusando `_jsonl_path` + el lock.
Mantener `assert_tenant_event` (el evento requiere `tenant_id`).

### 2.3 `cost.py`
```python
@dataclass
class ModelCost:
    per_1k_input: float
    per_1k_output: float

class BudgetExceededError(Exception): ...
class CostError(Exception): ...

class CostGovernor:
    def __init__(self, *, tenant_id=None, budgets=None, models=None, alert_threshold=0.8):
        # budgets: dict[tenant_id or "*"]: float ($ límite)
        # models:  dict[model]: ModelCost
    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float
    def record(self, tenant_id: str, model: str, input_tokens: int, output_tokens: int) -> float
        # acumula y devuelve el gasto actual del tenant
    def spent(self, tenant_id: str) -> float
    def budget_of(self, tenant_id: str) -> float            # presupuesto efectivo (tenant o "*")
    def remaining(self, tenant_id: str) -> float
    def allowed(self, tenant_id: str, model: str, input_tokens: int, output_tokens: int) -> bool
        # False si gasto+estimado > presupuesto
    def check_budget(self, tenant_id: str, model: str, input_tokens: int, output_tokens: int) -> None
        # lanza BudgetExceededError si !allowed
    def alerted(self, tenant_id: str) -> bool                # cruzó alert_threshold
```
Estado en memoria (dict por tenant). OFFLINE-SAFE. El gateway/runtime consulta
`allowed`/`check_budget` antes de ejecutar (capa transversal, no acopla al Supervisor).

### 2.4 `secrets.py`
```python
class SecretError(Exception): ...
class FeatureUnavailable(Exception): ...

class EnvSecretBackend:
    def get(self, name: str) -> Optional[str]: return os.getenv(name)

class KubernetesSecretBackend:
    def __init__(self, mount_dir: str | Path): ...   # lee archivos montados por K8s
    def get(self, name: str) -> Optional[str]:        # nombre en minusculas+guiones -> archivo

class VaultSecretBackend:
    VAULT_AVAILABLE: bool
    def __init__(self, *, url: str, token: str, path_prefix: str = "/secret/data"): ...
        # requiere `hvac`; si falta -> VAULT_AVAILABLE=False y get lanza FeatureUnavailable
    def get(self, name: str) -> Optional[str]: ...

class SecretStore:
    def __init__(self, backends: list): ...           # orden de prioridad
    def get(self, name: str) -> Optional[str]:
    def require(self, name: str) -> str:              # SecretError si None
```
Nunca hardcodea secretos; prefiere Vault > K8s > env. Offline-safe por defecto
(EnvSecretBackend siempre disponible).

### 2.5 `ratelimit.py`
```python
class RateLimitError(Exception): ...

class TenantRateLimiter:
    def __init__(self, *, quotas=None, window_s: int = 60):
        # quotas: dict[(tenant_id or "*", user or "*")]: max_requests en la ventana
    def check(self, *, tenant_id=None, user=None) -> bool       # False si excede
    def consume(self, *, tenant_id=None, user=None) -> None     # RateLimitError si excede
    def reset(self, *, tenant_id=None, user=None) -> None
    def remaining(self, *, tenant_id=None, user=None) -> int
```
Ventana deslizante en memoria (timestamps). La clave efectiva: quotas más
específicos (tenant,user) > (tenant,"*") > ("*","*").

## 3. CLI

### `ciel rbac` (`cli/rbac.py`)
- `ciel rbac list-roles` — imprime roles y permisos (offline, DEFAULT_ROLES).
- `ciel rbac assign --subject X --role admin [--tenant T]` — asigna en un engine en memoria (demo).
- `ciel rbac check --subject X --action agent:run [--tenant T]` — imprime allow/deny.

### `ciel cost` (`cli/cost.py`)
- `ciel cost record --tenant T --model gpt-4o --in 1000 --out 500 [--price-in X --price-out Y]`
- `ciel cost status --tenant T` — gasto actual / presupuesto / restante.
- `ciel cost check --tenant T --model gpt-4o --in 1000 --out 500` — allow/deny (corte).

Ambos OFFLINE-SAFE, sin red.

## 4. Criterio de avance — Fase 7 (cuándo cerrarla)
- [x] `RBACEngine` deniega acción sin rol; `OIDCVerifier` verifica token (o avisa si falta dep).
- [x] `HashChainAuditSink` es inmutable y `verify()` detecta alteración.
- [x] `CostGovernor` corta al superar presupuesto (`check_budget` lanza).
- [x] `SecretStore` resuelve por backend (Vault/K8s/env) sin hardcode.
- [x] `TenantRateLimiter` aplica cuotas por tenant/usuario.
- [x] `ciel rbac` / `ciel cost` funcionan offline.
- [x] Cada módulo tiene core + test verde; integración documentada; suite verde.
