# WebBridge — Protocolo da interface web headless (Orca v7)

Documenta o contrato de integração entre o painel web (`src/atm/web/`) e o motor real do Orca. Só descreve o que o código faz.

---

## Arquivos do módulo

| Caminho | Responsabilidade |
|---------|------------------|
| `src/atm/web/__init__.py` | Exporta `app` e as funções da bridge |
| `src/atm/web/app.py` | Rotas FastAPI (HTML + HTMX) |
| `src/atm/web/bridge.py` | Ponte síncrona pro motor real; estado por `session_id` |
| `src/atm/web/templates/base.html` | Layout base: Tailwind CDN + HTMX CDN, max-width 640px, touch 48px |
| `src/atm/web/templates/painel.html` | Painel principal: carregar dados, simular, status da sessão |
| `src/atm/web/templates/resultado.html` | Painel de resultados: tabela de cenários, análises por jornada/equipe |

---

## Mapeamento rota ↔ template

| Método | Rota | Template renderizado | Função bridge chamada |
|--------|------|----------------------|----------------------|
| GET | `/` | `painel.html` | `obter_estado` |
| POST | `/carregar-micro` | `painel.html` | `carregar_micro` |
| POST | `/carregar-tarifas` | `painel.html` | `carregar_tarifas` |
| POST | `/validar` | `painel.html` | `validar_dados` |
| POST | `/simular` | `painel.html` | `simular` |
| POST | `/simular-unico` | `painel.html` | `simular_unico` |
| POST | `/comparar-grade` | `painel.html` | `simular` (grade padrão) |
| GET | `/resultado` | `resultado.html` | `obter_estado` |
| POST | `/limpar` | `painel.html` | `limpar_sessao` |

Todas as rotas devolvem `HTMLResponse` via `Jinja2Templates` e definem o cookie `orca_session` (httponly, max_age=86400) com o `session_id`.

---

## Session state

### SessionState (dataclass)

Campo | Tipo | Default | Descrição
------|------|---------|----------
`session_id` | `str` | — | ID da sessão (uuid truncado a 8 chars, nunca PID)
`micro_rows` | `List[MicroRow]` | `[]` | Linhas do microplanejamento carregadas
`tarifas` | `Dict[str, Any]` | `{}` | Tarifas carregadas (STG_TARIFAS ou CT)
`config` | `Dict[str, Any]` | `{}` | Config do scheduler (via `carregar_config()`)
`cenarios` | `List[Dict[str, Any]]` | `[]` | Cenários produzidos por `simular_cenarios_reais`
`erro` | `Optional[str]` | `None` | Mensagem de erro da última operação

### Armazenamento

`_sessions: Dict[str, SessionState]` — dicionário em memória indexado por `session_id`. `_get_or_create_session(session_id)` recupera a existente ou cria uma nova com `uuid.uuid4()[:8]`.

O cliente envia `session_id` via:
- Cookie `orca_session` (lido por `_get_session_id(request)`)
- Campo oculto `<input name="session_id">` nos formulários HTMX

---

## Funções da bridge

### `carregar_micro(session_id, caminho=None) -> SessionState`
Carrega `microatual.xlsx` via `carregar_planilha_microplanejamento(cfg, caminho, modo_auto=True)` e converte com `micro_de_dataframe(df)`. Guarda em `state.micro_rows`. Caminho padrão resolvido por `_encontrar_micro_path(cfg)` (config.json → `data/planilhas/microatual.xlsx`).

**Erros:** "Arquivo micro não encontrado: <caminho>", "Falha ao carregar micro (modo automático)", "Erro ao carregar micro: <exceção>".

### `carregar_tarifas(session_id, caminho=None) -> SessionState`
Carrega tarifas via `carregar_stg_tarifas(caminho)`. Caminho padrão por `_encontrar_ct_path()` (config.json → `data/planilhas/STG_TARIFAS.xlsx` → busca por arquivo com "ct317" no nome).

**Erros:** "Arquivo de tarifas não encontrado: <caminho>", "Arquivo CT precisa ser processado primeiro (gere STG_TARIFAS.xlsx via CLI)", "Erro ao carregar tarifas: <exceção>".

### `validar_dados(session_id) -> SessionState`
Valida se `micro_rows` e `tarifas` estão preenchidos. Define `state.erro` se faltar algum.

### `simular(session_id, jornadas, equipes, executores_base=9, jornada_base=4.6) -> SessionState`
Constrói demanda de `_construir_demanda(micro_rows, tarifas)` (chave `(talhao, atividade)`, valor HH calculado por `rendimento_hm` ou `rendimento_hh`). Roda `simular_cenarios_reais(demanda, executores_base, jornada_base, jornadas=..., equipes=...)` em `_run_in_thread` (ThreadPoolExecutor, `max_workers=2`). Guarda em `state.cenarios`.

### `simular_unico(session_id, jornada, equipe) -> SessionState`
Constrói demanda e roda `simular_cenario_real(demanda, executores=equipe, jornada=jornada)` em thread pool. Guarda `[cenario]` em `state.cenarios`.

### `obter_estado(session_id) -> SessionState`
Retorna (ou cria) o `SessionState` da sessão.

### `limpar_sessao(session_id) -> None`
Remove a sessão do dicionário `_sessions`.

### Defaults (não vêm de config.json)
- `_JORNADA_DEFAULT = _JORNADA_DEFAULT_H` (4.6h)
- `_EXECUTORES_DEFAULT = 9`

---

## Códigos de erro (strings em `state.erro`)

| Contexto | Mensagem | Causa |
|----------|----------|-------|
| Micro | `Arquivo micro não encontrado: <caminho>` | `microatual.xlsx` não existe no caminho resolvido |
| Micro | `Falha ao carregar micro (modo automático)` | `carregar_planilha_microplanejamento` retornou None |
| Micro | `Erro ao carregar micro: <exceção>` | Exceção durante leitura/conversão |
| Tarifas | `Arquivo de tarifas não encontrado: <caminho>` | CT/STG não encontrado |
| Tarifas | `Arquivo CT precisa ser processado primeiro (gere STG_TARIFAS.xlsx via CLI)` | CT bruto não é STG válido |
| Tarifas | `Erro ao carregar tarifas: <exceção>` | Exceção durante leitura |
| Validação | `Micro não carregado. Carregue o microatual.xlsx primeiro.` | `micro_rows` vazio |
| Validação | `Tarifas não carregadas. Carregue o ct317real.xlsx (ou STG_TARIFAS.xlsx) primeiro.` | `tarifas` vazio |
| Simulação | `Nenhuma demanda construída — verifique micro e tarifas` | Demanda vazia após cruzamento micro×tarifas |
| Simulação | `Erro na simulação: <exceção>` | Exceção em `simular_cenarios_reais` / `simular_cenario_real` |
| Formulário | `Jornadas/equipes inválidos. Use números separados por vírgula.` | Parse falhou em `/simular` |

Não há códigos numéricos; erros são strings descritivas em PT-BR.

---

## Fluxo ponta a ponta (exemplo)

1. Usuário abre `GET /`. Cookie `orca_session` não existe → novo `session_id` (ex: `a3f7b1c2`). Renderiza `painel.html` com estado vazio.
2. Usuário clica "Carregar microatual.xlsx" → `POST /carregar-micro` com `session_id=a3f7b1c2`. Bridge carrega `data/planilhas/microatual.xlsx`, preenche `state.micro_rows`. Re-renderiza `painel.html` com `tem_micro=True`.
3. Usuário clica "Carregar tarifas (ct317real.xlsx)" → `POST /carregar-tarifas`. Bridge carrega `STG_TARIFAS.xlsx`, preenche `state.tarifas`. Re-renderiza com `tem_tarifas=True`.
4. Usuário clica "Validar dados carregados" → `POST /validar`. Se ambos preenchidos, `state.erro = None`.
5. Usuário preenche jornadas (`4.6,6.0,8.0`) e equipes (`4,6,9,12`), clica "Simular Grade" → `POST /simular`. Bridge constrói demanda, chama `simular_cenarios_reais` no thread pool. `state.cenarios` preenchido (3 jornadas × 4 equipes = 12 cenários). Re-renderiza `painel.html` com tabela de últimos cenários.
6. Usuário clica "Ver Painel Completo de Resultados →" → `GET /resultado?session_id=a3f7b1c2`. Renderiza `resultado.html` com a grade completa (Equipe, Jornada, Dias, Meses, HH Total, HH Pendente, Cap. Dia, Uso%, Linhas, Status) + análises por jornada e por equipe.
7. Usuário clica "Limpar Sessão" → `POST /limpar`. `limpar_sessao(a3f7b1c2)` remove do dicionário `_sessions`. Volta ao painel vazio.

---

## Thread pool e não-bloqueio

`_executor = ThreadPoolExecutor(max_workers=2)` em `bridge.py`. `_run_in_thread(fn, *args, **kwargs)` submete e chama `future.result()` — bloqueia a **worker thread**, não o event loop do FastAPI.

Todas as rotas em `app.py` são definidas com `def` (não `async def`), para que o Starlette as execute em um threadpool separado, evitando qualquer bloqueio do loop principal.

---

## Restrições de implementação

- Sem `subprocess.Popen`, sem `os.system`, sem `os.spawn`, sem spawn de terminal.
- Sem build step: Tailwind via CDN (`https://cdn.tailwindcss.com`), HTMX via CDN (`https://unpkg.com/htmx.org@1.9.10`), apenas vanilla JS.
- Estado por `session_id` (cookie + campo oculto), nunca PID.
- Motor real: `comparativo_real.simular_cenarios_reais` / `simular_cenario_real`. Nunca recálculo local.
- PT-BR em todas as strings de UI.

---

## Verificação estática

```bash
# Sintaxe dos módulos Python
python -c "import ast, glob; files = glob.glob('src/atm/web/**/*.py', recursive=True); [ast.parse(open(f, encoding='utf-8').read()) for f in files]; print('syntax OK', len(files), 'arquivos')"

# Importação do módulo (não serve)
python -c "import src.atm.web.app"

# Templates válidos (Jinja2 parse)
python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/atm/web/templates')); [env.get_template(t) for t in ['base.html','painel.html','resultado.html']]; print('templates OK')"
```
