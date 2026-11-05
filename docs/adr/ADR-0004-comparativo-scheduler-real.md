# ADR-0004: Comparativo multi-fator pelo scheduler real (fim da aproximação)

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
A função legada `simular_cenarios_multifator` (em `comparativo_mec.py`) calculava dias pela aproximação:

```
dias = ceil(HH / (equipes * jornada))
```

Isso ignora completamente:
- Cascata por talhão (Rocada → Formiga → Coroamento → Coveamento → Adubação → Plantio → Irrigação → Limpeza)
- Bloqueio global (Plantio/Irrigação travam todo o talhão)
- Pool pós-bloqueio
- Reforço automático
- HM-paralelo

Auditoria marcou como P0: para cenários encadeados a aproximação subestimava os dias de forma grotesca.

## Decisão
Criar `src/atm/orca/comparativo_real.py` que roda **cada cenário da grade pelo `_executar_scheduler_loop` real**, com as regras reais de `_default_sequencia_dict()`.

Funções expostas:
- `simular_cenario_real(demanda, executores, jornada, ...)` — roda UM cenário
- `simular_cenarios_reais(demanda, jornadas[], equipes[], ...)` — grade multi-fator

**Prova da divergência (4 talhões × 4 atividades encadeadas, 1.508 HH):**
- Aproximação: 26 dias
- Scheduler real: 30 dias (+4 dias de atraso real da cascata)

**Grade validada (monotônica e com uso de capacidade 90-98%):**
- 6 ops @ 4.3h → 63d | 12 ops @ 8.8h → 16d

A função antiga permanece (compatibilidade), agora documentada como aproximação.

## Consequências
- Resultados confiáveis para planejamento operacional
- 8 testes, incluindo assert de que `real >= aproximação`
- Usado pelo MCP server nas ferramentas `orca_simular_cenario` e `orca_comparar_cenarios`

## Alternativas consideradas
- Melhorar a aproximação com fatores de correção (rejeitado: heurística frágil)
- Manter só a aproximação (rejeitado: auditoria P0)
- Scheduler real escolhido: custo computacional maior, resultado confiável

## Evidência
- Commit: `05856239df3e2007c1069b9d64ab157af0302d7e` (`git show --stat 0585623`)
  - `src/atm/orca/comparativo_real.py` | 145 +++++++++++++++++++++++++++++++++++++++
  - `tests/test_comparativo_real.py`   | 119 ++++++++++++++++++++++++++++++++
  - 2 files changed, 264 insertions(+)