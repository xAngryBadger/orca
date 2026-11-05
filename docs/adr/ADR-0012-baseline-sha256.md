# ADR-0012: Baseline sha256 como contrato de integridade — ORCA_BASELINE.md com 21 módulos + HEAD

**Status:** Bloqueada (sem evidência de commit)
**Data:** 2026-11-05

## Contexto
Necessidade de um manifesto de integridade que garanta: os 21 módulos do pacote `orca` não foram alterados acidentalmente, o HEAD do git é conhecido, e qualquer agente pode verificar a baseline antes de rodar.

## Decisão
**BLOQUEIO HONESTO:** O arquivo `ORCA_BASELINE.md` existe na raiz do repo mas **não tem histórico no git log** (`git log --oneline --all -- ORCA_BASELINE.md` retorna vazio). Não há commit que registre a criação/atualização deste manifesto.

O manifesto deveria conter:
- SHA256 de cada um dos 21 módulos em `src/atm/orca/*.py`
- HEAD do git (`git rev-parse HEAD`)
- Contagem de testes oficiais (49)
- Data/autor da verificação

O recurso `orca://baseline` do MCP server (`recurso_baseline()` em `mcp_server.py:411-428`) lê o HEAD via `git rev-parse HEAD` e lista módulos via `os.listdir()`, mas **não lê o ORCA_BASELINE.md** — ele computa na hora.

## Alternativas consideradas
- Nenhuma documentada (falta evidência)

## Evidência
- **NENHUM HASH VERIFICÁVEL** — `git log --oneline --all -- ORCA_BASELINE.md` → (vazio)
- `ORCA_BASELINE.md` existe no working tree mas não está versionado (ou foi adicionado sem commit rastreável)
- Commit relacionado: `ce6110ff730329be0f1c189d618bb653fe3ab9e7` (MCP server lê HEAD/modules em runtime, não do manifesto)
- **REQUER:** commit que adicione/atualize `ORCA_BASELINE.md` com sha256 dos 21 módulos + HEAD para ter evidência