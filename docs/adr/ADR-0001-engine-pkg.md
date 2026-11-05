# ADR-0001: Extração do motor para engine_pkg

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
O módulo `scheduler_core.py` atingiu 3383 linhas, concentrando toda a lógica do scheduler (validação, construção de demandas, loop principal, verificação de tarifas/executores, merge de cronograma). A manutenção tornava-se difícil e testes de integração dependiam do módulo inteiro.

## Decisão
Extrair 7 funções puras do `scheduler_core.py` para um novo pacote `src/atm/orca/engine_pkg/engine.py`:

- `_validar_input` (11 linhas)
- `_construir_demandas` (133 linhas)
- `_executar_scheduler_loop` (181 linhas)
- `_verificar_atividades_sem_tarifa` (34 linhas)
- `_merge_cronograma_base_e_metricas` (37 linhas)
- `_construir_filas_e_demanda_global` (58 linhas)
- `_verificar_atividades_sem_executor` (44 linhas)

Total: 511 linhas movidas **verbatim** (provado entry-by-entry contra HEAD). O `scheduler_core.py` re-importa de `engine_pkg` para preservar a API pública — os 8 nomes continuam acessíveis via `scheduler_core` (verificado por teste).

## Consequências
- `scheduler_core.py` reduzido de 3383 para 2862 linhas (-521 linhas)
- 78/78 testes passam (49 oficiais + 15 integração + 14 schemas)
- Separação clara: `engine_pkg` = motor puro; `scheduler_core` = orquestração + I/O + UI

## Alternativas consideradas
- Manter tudo em `scheduler_core.py` (rejeitado: complexidade crescente)
- Criar módulo `scheduler.py` (rejeitado: colisão com `excel_export.py` que faz `from .scheduler import _fases_ordem_config` — ver ADR-0002)

## Evidência
- Commit: `be7eb079ce91b25d9a1b1508fa6381c0210898f2` (`git show --stat be7eb07`)
  - `src/atm/orca/engine_pkg/__init__.py` |  26 ++
  - `src/atm/orca/engine_pkg/engine.py`   | 658 ++++++++++++++++++++++++++++++++++++
  - `src/atm/orca/scheduler_core.py`      | 520 +---------------------------
  - `tests/test_scheduler_integration.py` |  22 +-
  - 4 files changed, 707 insertions(+), 519 deletions(-)