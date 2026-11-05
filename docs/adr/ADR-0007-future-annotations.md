# ADR-0007: `from __future__ import annotations` em scheduler_core.py — bug pré-existente no GitHub

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
O módulo `scheduler_core.py` usava `_SchedulerLoopConfig` em anotação de tipo (linha ~400) **antes** da definição da classe (linha ~981). Sem `from __future__ import annotations`, o Python avalia anotações em tempo de importação, causando `NameError: name '_SchedulerLoopConfig' is not defined` e quebrando:
- `from atm import orca`
- Entry point `python -m src.atm.atm_v6_3`

Bug pré-existente no branch rework, introduzido durante a refatoração que criou `_SchedulerLoopConfig` como dataclass.

## Decisão
Adicionar `from __future__ import annotations` no topo de `scheduler_core.py`. Isso faz as anotações serem armazenadas como strings (PEP 563), adiando a avaliação para tempo de execução via `typing.get_type_hints()` se necessário.

Mudança mínima: 2 linhas inseridas no topo do arquivo.

## Consequências
- Import do módulo `atm.orca` volta a funcionar
- Entry point `python -m src.atm.atm_v6_3` executa sem erro
- Zero impacto em runtime (anotações não são usadas em validação runtime no projeto)

## Alternativas consideradas
- Mover definição de `_SchedulerLoopConfig` para antes do uso (rejeitado: reorganização maior, dataclass depende de imports que vêm depois)
- Usar string quotes manuais nas anotações (rejeitado: propenso a erro, PEP 563 é padrão)
- `from __future__ import annotations` escolhido: fix minimal, padrão Python 3.7+

## Evidência
- Commit: `b295d5e4dea35e74e3ed734a57f9e9660858b06d` (`git show --stat b295d5e`)
  - `src/atm/orca/scheduler_core.py` | 2 ++
  - 1 file changed, 2 insertions(+)
  - Mensagem: "fix(scheduler_core): corrige NameError de forward reference no import — _SchedulerLoopConfig era usado em anotacao (L400) antes da definicao (L981). Sem 'from __future__ import annotations' o modulo explodia no import, quebrando 'from atm import orca' e o entry point python -m src.atm.atm_v6_3. Bug pre-existente no branch rework, corrigido agora."