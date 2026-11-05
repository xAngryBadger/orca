# ADR-0008: Defaults do scheduler como parâmetros de função (dataclass _SchedulerLoopConfig), não chaves fantasma de config

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
A função `_executar_scheduler_loop` recebia **20+ parâmetros posicionais** (turmas, turma_filas, demanda_global, demandas, talhoes_ordenados, jornada, executores, seq_cfg, modo_seq, usar_cascata, usar_bloqueio_global, atividades_bloqueadas, usar_reforco_automatico, usar_pool_pos_bloqueio, atividades_plantio, atividades_irrig, fazenda, cfg, tarifas, modo_somente_hh, dia_termino_plantio, tem_plantio_por_talhao). Isso tornava:
- Chamadas propensas a erro (ordem, tipos)
- Testes difíceis (mock de 20+ args)
- Configuração espalhada entre `cfg` dict e parâmetros explícitos (chaves fantasma)

## Decisão
Introduzir `@dataclass _SchedulerLoopConfig` que agrupa **todos** os parâmetros do loop em um único objeto tipado. A função passa a receber apenas `config: _SchedulerLoopConfig`.

Campos da dataclass (21 campos):
- `turmas`, `turma_filas`, `demanda_global`, `demandas`, `talhoes_ordenados`
- `jornada`, `executores`
- `seq_cfg`, `modo_seq`
- `usar_cascata`, `usar_bloqueio_global`, `atividades_bloqueadas`
- `usar_reforco_automatico`, `usar_pool_pos_bloqueio`
- `atividades_plantio`, `atividades_irrig`
- `fazenda`, `cfg`, `tarifas`, `modo_somente_hh`
- `dia_termino_plantio`, `tem_plantio_por_talhao`

O chamador (`calcular_cronograma_inteligente`) instancia a dataclass explicitamente com `config = _SchedulerLoopConfig(...)` — cada campo nomeado, sem ambiguidade.

## Consequências
- Assinatura de `_executar_scheduler_loop`: 21 params → 1 param (`config`)
- Chamada explícita: zero ambiguidade de ordem/tipo
- Testes: mock de um objeto em vez de 20+ args
- Configuração centralizada: nada fica "escondido" no `cfg` dict
- Função funcionalmente pura w.r.t. `demanda_global` (retorna demanda atualizada, não muta in-place)

## Alternativas consideradas
- Manter 20+ parâmetros (rejeitado: manutenibilidade)
- Usar `**kwargs` (rejeitado: sem tipagem, propenso a typo)
- Dataclass escolhida: tipagem explícita, IDE autocomplete, documentação viva

## Evidência
- Commit: `f5363b29236ac23f90eab86792207a7e445b51a4` (`git show --stat f5363b2`)
  - `src/atm/orca/scheduler_core.py` | 160 ++++++++++++++++++++++++-----------------
  - 1 file changed, 96 insertions(+), 64 deletions(-)
  - Diff mostra: definição de `_SchedulerLoopConfig` (linhas 977-1003) + refatoração da assinatura e corpo de `_executar_scheduler_loop` para usar `config.xxx`