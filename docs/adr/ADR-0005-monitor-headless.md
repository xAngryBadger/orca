# ADR-0005: Monitor headless — fim do spawn de janelas de terminal

**Status:** Aceita
**Data:** 2026-11-05

## Contexto
O módulo `monitor.py` usava `_abrir_monitor_janela` com `subprocess.Popen` para criar janelas de terminal:
- Windows: `cmd /k`
- Linux: `kitty`, `foot`, `wezterm`, `alacritty`, `gnome-terminal`, `konsole`, `xfce4-terminal`, `xterm`

Três problemas críticos:
1. Múltiplas janelas sem health check
2. Script externo `srf_monitor.py` não versionado
3. Risco real de travar a máquina se o processo filho travasse

## Decisão
Tornar o monitor **headless**: o estado vive no JSON de sessão (`orca_monitor_state`) e qualquer consumidor — CLI, web, MCP — lê esse arquivo. Nenhum processo é criado. Degradação limpa quando o módulo não está disponível.

Mudanças em `monitor.py`:
- Removido `subprocess.Popen` e detecção de terminais
- Estado persiste em arquivo JSON com `session_id` (substitui PID no isolamento)
- Emissores aceitam `session_id` como parâmetro
- Zero subprocess no módulo (varrido por AST nos testes)

## Consequências
- Zero terminal no código (docstrings de remoção excluídas)
- `Popen` monitorado: chamar `_abrir_monitor_janela` não cria processo
- Zero `getpid` no estado
- 7 testes de monitor headless passam
- Total: 93 testes (49 oficiais + 15 integração + 14 schemas + 8 comparativo real + 7 monitor headless)

## Alternativas consideradas
- Manter spawn mas com health check (rejeitado: complexidade, script externo não versionado)
- Usar socket/pipe em vez de arquivo (rejeitado: arquivo JSON é mais simples e inspecionável)
- Headless escolhido: simplicidade, zero dependência de terminal, funciona em CI/headless servers

## Evidência
- Commit: `779c09ef9912a382ee1f73f497f07f3d641027c8` (`git show --stat 779c09e`)
  - `src/atm/orca/monitor.py`        |  71 ++++++++-------------------
  - `tests/test_monitor_headless.py` | 109 +++++++++++++++++++++++++++++++++++++++++
  - 2 files changed, 130 insertions(+), 50 deletions(-)