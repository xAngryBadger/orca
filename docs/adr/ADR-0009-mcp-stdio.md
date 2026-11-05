# ADR-0009: Servidor MCP sobre stdio com JSON-RPC 2.0 hand-rolled, zero dependência nova

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
Necessidade de expor o motor Orca (carregar micro, validar pipeline, simular cenários, comparar cenários, métricas) para agentes de IA (Claude Code, Cursor, etc.) via Model Context Protocol (MCP). Requisitos:
- Protocolo MCP sobre stdio (JSON-RPC 2.0)
- Zero dependência externa (nenhum `pip install` — roda em qualquer Python 3.10+)
- Ferramentas: 7 tools (carregar_micro, listar_fazendas, carregar_tarifas, validar_pipeline, simular_cenario, comparar_cenarios, metricas)
- Recursos: 2 resources (orca://baseline, orca://schemas)
- O motor continua sendo a fonte da verdade: o MCP só orquestra, nunca calcula por conta própria

## Decisão
Implementar `src/atm/mcp_server.py` com:
- Loop stdio: uma requisição JSON-RPC por linha (`for linha in sys.stdin`)
- Dispatch manual dos métodos MCP: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `ping`
- JSON-RPC 2.0 hand-rolled: `_ok()`, `_erro()`, `_texto()`, `_despachar()`
- Imports do motor real: `atm.orca.comparativo_real`, `atm.orca.engine_pkg`, `atm.orca.schemas`
- Sessão em memória (`_SESSAO` dict) para micro, tarifas, de_para, último cenário
- `_RAIZ_REPO` calculado dinamicamente + `sys.path.insert` para resolver imports

## Consequências
- Cliente MCP conecta via stdio, recebe `initialize` response com `protocolVersion: "2024-11-05"`, `serverInfo: {"name": "orca-mcp", "version": "1.0.0"}`, capabilities tools/resources
- `tools/list` expõe 7 ferramentas com inputSchema JSON Schema
- `tools/call` despacha para funções `tool_*` que delegam ao motor real
- `resources/list` expõe `orca://baseline` (HEAD git + módulos + tarifas) e `orca://schemas` (JSON Schema Pydantic)
- 9 testes de contrato passam (subprocess stdio end-to-end)

## Alternativas consideradas
- Usar biblioteca `mcp` ou `jsonrpcserver` (rejeitado: dependência nova, versão MCP instável)
- HTTP/WebSocket (rejeitado: MCP padrão é stdio para CLI agents)
- Hand-rolled escolhido: zero deps, controle total, ~560 linhas

## Evidência
- Commit: `ce6110ff730329be0f1c189d618bb653fe3ab9e7` (`git show --stat ce6110f`)
  - `src/atm/mcp_server.py`      | 568 +++++++++++++++++++++++++++++++++++++++++++++
  - `tests/test_mcp_contract.py` | 274 ++++++++++++++++++++++
  - 2 files changed, 842 insertions(+)
  - Commit message: "fix(mcp): _ok ecoa id da requisicao JSON-RPC 2.0 + teste de contrato (t1)"