"""Cost governance: presupuesto por modelo/tenant, alertas y corte.

OFFLINE-SAFE. Estado en memoria (dict por tenant). El gateway/runtime consulta
``allowed``/``check_budget`` antes de ejecutar (capa transversal, no acopla al
Supervisor).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelCost:
    per_1k_input: float
    per_1k_output: float


class BudgetExceededError(Exception):
    """Se lanza cuando una operación superaría el presupuesto del tenant."""


class CostError(Exception):
    """Error genérico de cost governance (p. ej. modelo desconocido)."""


class CostGovernor:
    """Gobernador de costos por tenant con presupuesto, alertas y corte."""

    def __init__(
        self,
        *,
        tenant_id: Optional[str] = None,
        budgets: Optional[dict] = None,
        models: Optional[dict] = None,
        alert_threshold: float = 0.8,
    ) -> None:
        # ``budgets``: dict[tenant_id o "*"] -> float ($ límite)
        # ``models``: dict[model] -> ModelCost
        self.tenant_id = tenant_id
        self.budgets: dict = dict(budgets or {})
        self.models: dict = dict(models or {})
        self.alert_threshold = alert_threshold
        # gasto acumulado por tenant (estado en memoria)
        self._spent: dict[str, float] = {}

    # -- cálculo -----------------------------------------------------------
    def estimate(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Costo estimado de una llamada (en $)."""
        if model not in self.models:
            raise CostError(f"modelo desconocido: {model!r}")
        cost = self.models[model]
        est_in = (input_tokens / 1000.0) * cost.per_1k_input
        est_out = (output_tokens / 1000.0) * cost.per_1k_output
        return est_in + est_out

    # -- registro ----------------------------------------------------------
    def record(
        self,
        tenant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Acumula el gasto del tenant y devuelve el gasto actual."""
        amount = self.estimate(model, input_tokens, output_tokens)
        self._spent[tenant_id] = self._spent.get(tenant_id, 0.0) + amount
        return self._spent[tenant_id]

    def spent(self, tenant_id: str) -> float:
        """Gasto acumulado del tenant."""
        return self._spent.get(tenant_id, 0.0)

    # -- presupuesto -------------------------------------------------------
    def budget_of(self, tenant_id: str) -> float:
        """Presupuesto efectivo: el del tenant o el global "*"."""
        if tenant_id in self.budgets:
            return float(self.budgets[tenant_id])
        if "*" in self.budgets:
            return float(self.budgets["*"])
        return 0.0

    def remaining(self, tenant_id: str) -> float:
        """Presupuesto restante del tenant."""
        return self.budget_of(tenant_id) - self.spent(tenant_id)

    # -- corte / alertas ---------------------------------------------------
    def allowed(
        self,
        tenant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> bool:
        """False si gasto actual + estimado supera el presupuesto."""
        if model not in self.models:
            raise CostError(f"modelo desconocido: {model!r}")
        projected = self.spent(tenant_id) + self.estimate(
            model, input_tokens, output_tokens
        )
        return projected <= self.budget_of(tenant_id)

    def check_budget(
        self,
        tenant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Lanza ``BudgetExceededError`` si la operación no está permitida."""
        if not self.allowed(tenant_id, model, input_tokens, output_tokens):
            raise BudgetExceededError(
                f"presupuesto excedido para tenant {tenant_id!r}"
            )

    def alerted(self, tenant_id: str) -> bool:
        """True si el gasto cruzó el umbral de alerta (alert_threshold)."""
        budget = self.budget_of(tenant_id)
        if budget <= 0:
            return False
        return self.spent(tenant_id) >= self.alert_threshold * budget
