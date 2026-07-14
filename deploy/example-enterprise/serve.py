"""Arranque del gateway enterprise Ciel a partir de ciel.yaml.

Lee el manifesto central (deploy/example-enterprise/ciel.yaml) usando el
módulo reutilizable ``ciel.config`` del paquete, cablea el provider remoto si
está configurado, y arranca la app compuesta (control + MCP host + webhook)
con uvicorn. Mantiene multi-tenancy estricto.
"""

from __future__ import annotations

import logging
import os

import uvicorn

from ciel.config import CielConfig, build_app, load

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ciel.enterprise")


def _configure_runtime(config_path: str) -> CielConfig:
    """Load the ciel.yaml manifesto via the reusable package module.

    Returns the resolved :class:`CielConfig` (default tenant, approval policy,
    providers, tenants, audit and gateway settings).
    """
    cfg = load(config_path)
    for entry in cfg.providers:
        if entry.base_url:
            logger.info(
                "provider '%s' -> %s (tenant=%s)",
                entry.name,
                entry.base_url,
                entry.tenant,
            )
    if cfg.tenants:
        logger.info("allowed tenants: %s", ", ".join(cfg.tenants))
    return cfg


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(here, "ciel.yaml")
    cfg = _configure_runtime(config_path)

    host = cfg.gateway.host
    port = cfg.gateway.port

    app = build_app(cfg)
    logger.info(
        "starting Ciel gateway on %s:%s (tenant=%s, policy=%s)",
        host,
        port,
        cfg.default_tenant,
        cfg.approval_policy,
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
