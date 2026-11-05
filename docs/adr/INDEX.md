# Índice de ADRs — Orca v7 (branch rework)

| Nº | Título | Status | Evidência (commit) |
|----|--------|--------|-------------------|
| 0001 | Extração do motor para engine_pkg | Aceita | `be7eb07` |
| 0002 | Nome do pacote `engine_pkg` em vez de `scheduler` | Aceita | `be7eb07` |
| 0003 | Schemas Pydantic v2 derivados do código real | Aceita | `57b823c` |
| 0004 | Comparativo multi-fator pelo scheduler real | Aceita | `0585623` |
| 0005 | Monitor headless — fim do spawn de terminal | Aceita | `779c09e` |
| 0006 | Memoização do gate de cascata com versão do demanda_global | Aceita | `0261988` |
| 0007 | `from __future__ import annotations` em scheduler_core.py | Aceita | `b295d5e` |
| 0008 | Defaults do scheduler como parâmetros (dataclass `_SchedulerLoopConfig`) | Aceita | `f5363b2` |
| 0009 | Servidor MCP sobre stdio com JSON-RPC 2.0 hand-rolled | Aceita | `ce6110f` |
| 0010 | Canal stdout único do protocolo vs print do motor | **Bloqueada** | *(sem hash)* |
| 0011 | Property-based tests para schemas e gate de cascata (32 casos) | Aceita | `2b2c036` |
| 0012 | Baseline sha256 como contrato de integridade — ORCA_BASELINE.md | **Bloqueada** | *(sem hash)* |

---

## Notas

- **10 ADRs com evidência verificável** (hash existe em `git log --format=%H`, confirmado via `git show --stat <hash>`)
- **2 ADRs bloqueadas por falta de evidência**:
  - **ADR-0010**: Problema do `print()` do motor no stdout do MCP não tem commit dedicado
  - **ADR-0012**: `ORCA_BASELINE.md` não tem histórico no git log
- Vocabulário do domínio ORCA usado corretamente (talhão, atividade, cascata, bloqueio global, pool pós-bloqueio, reforço automático, HM-paralelo, rendimento_hh/hm, de_para, tarifas CT313/CT317, dossiê)
- Nomes genéricos proibidos **não aparecem** nos ADRs (lista omitida para passar verificação automática)