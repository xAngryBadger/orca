# ADR-0010: Canal stdout único do protocolo vs print do motor

**Status:** Bloqueada (sem evidência de commit)
**Data:** 2026-11-05

## Contexto
O servidor MCP usa **stdout como canal exclusivo do protocolo JSON-RPC 2.0** (uma resposta por linha). Porém, o motor real (módulos `io.py`, `scheduler_core.py`, `engine.py`) usa `print()` para banners de progresso, logs de dia-a-dia do scheduler, etc. Essas linhas de "ruído" se misturam às respostas JSON-RPC no mesmo stream stdout, quebrando clientes que esperam JSON válido linha a linha.

O teste de contrato (`tests/test_mcp_contract.py`) contorna isso com `_extrair_jsonrpc()` que:
1. Tenta parsear a linha inteira como JSON
2. Se falha, busca `{` na linha e tenta `JSONDecoder.raw_decode()`
3. Descarta linhas que não contenham `"jsonrpc"`

## Decisão
**BLOQUEIO HONESTO:** Não foi encontrado commit específico que documente esta decisão/fix. O commit `ce6110f` cria o servidor MCP mas o problema do `print()` do motor no stdout é anterior e não tem commit dedicado no histórico verificado.

Para resolver corretamente, seria necessário:
1. Redirecionar `print()` do motor para `stderr` (ou logging)
2. Ou capturar stdout do motor em subprocess separado
3. Ou adicionar flag `quiet` no motor

## Alternativas consideradas
- Nenhuma documentada (falta evidência)

## Evidência
- **NENHUM HASH VERIFICÁVEL** — `git log --oneline --all --grep="stdout\|print"` não retorna commit relevante para esta decisão específica
- Commit relacionado: `ce6110ff730329be0f1c189d618bb653fe3ab9e7` (cria servidor MCP com `_extrair_jsonrpc` no teste, mas não fixa a raiz no motor)
- **REQUER INVESTIGAÇÃO ADICIONAL** para encontrar/criar evidência