# ADR-0002: Nome do pacote `engine_pkg` em vez de `scheduler`

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
Ao extrair o motor do `scheduler_core.py` para um pacote dedicado (ver ADR-0001), o nome natural seria `scheduler`. Porém, o módulo `src/atm/orca/excel_export.py` já faz:

```python
from .scheduler import _fases_ordem_config
```

Isso importa do módulo `orca/scheduler.py` (existente no projeto). Um pacote chamado `scheduler` colidiria com esse módulo, quebrando o import do `excel_export.py`.

## Decisão
Nomear o novo pacote como `engine_pkg` (em vez de `scheduler`). O sufixo `_pkg` deixa explícito que é um pacote, não um módulo, e evita a colisão de namespace com `orca/scheduler.py`.

## Consequências
- Import no `scheduler_core.py`: `from atm.orca.engine_pkg import _construir_demandas, _executar_scheduler_loop, ...`
- Import no `comparativo_real.py`: `from .engine_pkg import _executar_scheduler_loop`
- Import no `mcp_server.py`: `from atm.orca.engine_pkg import _construir_demandas, _executar_scheduler_loop`
- Zero breaking changes: `excel_export.py` continua funcionando

## Alternativas consideradas
- Renomear `orca/scheduler.py` (rejeitado: impacto amplo, módulo estável)
- Usar `_engine` como prefixo privado (rejeitado: não resolve a colisão de import)
- `engine_pkg` escolhido por ser descritivo e não conflitar

## Evidência
- Commit: `be7eb079ce91b25d9a1b1508fa6381c0210898f2` (mesmo commit do ADR-0001)
  - Mensagem do commit: "Pacote chama-se engine_pkg (nao scheduler) porque excel_export.py faz 'from .scheduler import _fases_ordem_config' — um pacote com esse nome colidiria com o modulo orca/scheduler.py."
  - `src/atm/orca/engine_pkg/__init__.py` |  26 ++
  - `src/atm/orca/engine_pkg/engine.py`   | 658 ++++++++++++++++++++++++++++++++++++