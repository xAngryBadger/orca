# ADR-0003: Schemas Pydantic v2 derivados do código real

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
O projeto usava dicionários soltos e validação implícita espalhada pelo código (ex.: `io.py`, `tarifas.py`, `config.py`). Não havia contrato formal entre microplanejamento, de-para, tarifas e pipeline. Erros de estrutura só apareciam em tempo de execução no scheduler.

## Decisão
Criar `src/atm/orca/schemas.py` com modelos Pydantic v2 que **espelham exatamente as estruturas que o motor REAL produz/consume**:

| Modelo | Origem real no código |
|--------|----------------------|
| `MicroRow` | `io.py:325` — `["fazenda","chave","area_ha","atividade"]` + opcionais |
| `TarifaCT` | `tarifas.py:695-705` — retorno de `carregar_stg_tarifas` |
| `DeParaMap` | `cfg["de_para"]` — mapeamento nome-no-micro → nome-na-tarifa |
| `PrecoFinal` | `tarifas.py:_carregar_mapa_preco_final_json` — linhas de `preco_final.json` |
| `PipelineConfig` | Contrato cruzado: micro + de_para + tarifas |
| `TarifasDict` | Wrapper tipado para `cfg["tarifas"]` |

Funções de conversão:
- `micro_de_dataframe(df)` — valida DataFrame do loader em `List[MicroRow]`
- `tarifas_de_dict(d)` — injeta a chave como `atividade` no valor (no `cfg["tarifas"]` a CHAVE é a atividade, o valor não repete o nome)
- `depara_de_dict(d)` — wrapper tipado

**Regra de negócio real codificada (não inventada):**
- `TarifaCT`: quando `rendimento_hh > 0` implica `rendimento_hm = 0` (o que `normalizar_ct313`/`_aplicar_mapa_preco_final` fazem)
- `DeParaMap`: aceita auto-mapeamento `X→X` (legítimo no projeto); rejeita ciclo verdadeiro `A↔B` com `A != B`

## Consequências
- Validação estática de entrada antes de entrar no scheduler
- 107 tarifas CT317 + 21 pares de-para validados, 0 conflitos HH/HM, 13 HM-only
- 14 testes próprios + property-based tests (ver ADR-0011)
- Total de testes: 78 (49 oficiais + 15 integração + 14 schemas)

## Alternativas consideradas
- Dataclasses + validação manual (rejeitado: Pydantic v2 dá validação + serialização + JSON Schema grátis)
- Schemas imaginados/genéricos (rejeitado: decisão explícita de derivar do código real, não de especulação)

## Evidência
- Commit: `57b823c5e13a47eec734edf1ef2e3fe7fd90e288` (`git show --stat 57b823c`)
  - `src/atm/orca/schemas.py` | 190 ++++++++++++++++++++++++++++++++++++++++++++++++
  - `tests/test_schemas.py`   | 144 ++++++++++++++++++++++++++++++++++++
  - 2 files changed, 334 insertions(+)