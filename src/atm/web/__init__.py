"""Orca Web — Interface headless estilo Harness (FastAPI + HTMX + Tailwind CDN)."""

from .app import app
from .bridge import (
    carregar_micro,
    carregar_tarifas,
    validar_dados,
    simular,
    simular_unico,
    obter_estado,
    limpar_sessao,
)

__all__ = [
    "app",
    "carregar_micro",
    "carregar_tarifas",
    "validar_dados",
    "simular",
    "simular_unico",
    "obter_estado",
    "limpar_sessao",
]