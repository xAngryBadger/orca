"""Pacote engine_pkg — engine extraído de scheduler_core (decomposição).

Renomeado de `scheduler` para `engine_pkg` porque `excel_export.py` faz
`from .scheduler import _fases_ordem_config` (módulo `orca/scheduler.py`);
um pacote com o mesmo nome colidiria com ele.
"""

from .engine import (
    _construir_demandas,
    _construir_filas_e_demanda_global,
    _executar_scheduler_loop,
    _merge_cronograma_base_e_metricas,
    _validar_input,
    _verificar_atividades_sem_executor,
    _verificar_atividades_sem_tarifa,
)

__all__ = [
    "_construir_demandas",
    "_construir_filas_e_demanda_global",
    "_executar_scheduler_loop",
    "_merge_cronograma_base_e_metricas",
    "_validar_input",
    "_verificar_atividades_sem_executor",
    "_verificar_atividades_sem_tarifa",
]
