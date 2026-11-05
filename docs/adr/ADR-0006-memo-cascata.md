# ADR-0006: Memoização do gate de cascata com versão do demanda_global na chave

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
A função `pode_agendar_atividade_cascata` era chamada **3x por item/dia** nos três pontos do loop do scheduler:
1. Pool pós-bloqueio
2. Fila de turma
3. Reforço automático

Sem cache, isso causava recálculo repetido da mesma lógica de cascata (ordem Rocada → Formiga → Coroamento → Coveamento → Adubação → Plantio → Irrigação → Limpeza).

## Decisão
Implementar memoização com chave composta: `(talhao, atividade, versão)`. A versão é `_ha_nao_bloqueado_version`, incrementada por `_demanda_global_touch` em **TODO** consumo de `demanda_global` — que é a única entrada mutável do gate.

Sem a versão na chave, o cache daria resultado velho (ex.: plantio zerado de manhã liberaria irrigação à tarde incorretamente). O cache nasce e morre a cada dia.

## Consequências
- Chamadas de `pode_agendar_atividade_cascata`: 65 → 36 versões únicas/dia
- Prova A/B contra baseline: cronograma idêntico (26 dias, 36 linhas, zero violação de cascata, soma HH bate)
- Cache local ao dia, sem vazamento entre dias

## Alternativas consideradas
- Cache simples `(talhao, atividade)` sem versão (rejeitado: resultado stale quando demanda_global muda no mesmo dia)
- LRU cache global (rejeitado: complexidade, invalidação difícil)
- Versão por demanda_global escolhida: granularidade correta, invalidação automática

## Evidência
- Commit: `026198816324ae3019246891c6de2c583cbcc54e` (`git show --stat 0261988`)
  - `src/atm/orca/scheduler_core.py` | 42 +++++++++++++++++++++---------------------
  - 1 file changed, 21 insertions(+), 21 deletions(-)