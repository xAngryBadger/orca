# ADR-0011: Property-based tests para schemas e gate de cascata (20 + 12 casos)

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
Testes unitários tradicionais cobrem casos conhecidos, mas não exploram o espaço de entrada. Necessidade de validar invariantes dos schemas Pydantic e da ordem das fases de cascata com geração própria de casos.

## Decisão
Implementar **property-based tests com geração própria** (sem Hypothesis, determinístico via `random.seed` fixo) em dois arquivos:

### `tests/test_property_schemas.py` (20 testes)
| Modelo | Propriedades testadas |
|--------|----------------------|
| `MicroRow` | `chave` vira maiúscula, `penalidade` ∈ [0.1, 5.0], `area_ha` ≥ 0, `fazenda`/`atividade` não vazias, conversão de DataFrame |
| `TarifaCT` | HH>0 ⇒ HM=0 (regra real do normalizador), HM-only vira `recurso=maquina`, rendimento negativo rejeitado |
| `DeParaMap` | Aceita auto-mapeamento `X→X`, rejeita ciclo `A↔B` com `A != B` |
| `PipelineConfig` | Cobertura e detecção de atividade sem tarifa |

### `tests/test_property_cascade.py` (12 testes)
- Ordem numérica das fases conforme `_default_sequencia_dict()`:
  - Rocada(0) < Formiga(1) < Coroamento(2) < Coveamento(3) < Adubação(4) < Plantio(6) < Irrigação(7) < Limpeza(8)
- Filtros reais do `_default_sequencia_dict` validados

**Todos read-only:** importam módulos e validam, **nunca rodam scheduler**.

## Consequências
- 32 testes property-based adicionados
- Determinísticos: `random.seed(42)` fixo, reprodutíveis em CI
- Zero dependência externa (sem Hypothesis)
- Cobrem edge cases que testes manuais não pegariam (ex.: ciclo A↔B no DeParaMap, HH>0 ⇒ HM=0)

## Alternativas consideradas
- Hypothesis (rejeitado: dependência extra, non-deterministic sem seed fixo)
- Mais testes unitários manuais (rejeitado: não escala, viés do autor)
- Geração própria com seed fixo escolhida: determinístico, zero deps, controle total

## Evidência
- Commit: `2b2c03695161bc6170518de59ad78382bdc14d07` (`git show --stat 2b2c036`)
  - `tests/test_property_cascade.py` | 14 ++++++++++----
  - `tests/test_property_schemas.py` | 19 ++++++++++++++-----
  - 2 files changed, 24 insertions(+), 9 deletions(-)
  - Mensagem: "test(property): property-based tests para schemas e gate de cascata — Geração propria de casos com random.seed fixo (deterministico, sem Hypothesis). 32 testes no total"