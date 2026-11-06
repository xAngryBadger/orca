"""Rotinas FastAPI — painel web headless estilo Harness."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .bridge import (
    carregar_micro,
    carregar_tarifas,
    validar_dados,
    simular,
    simular_unico,
    simular_com_cronograma,
    agregar_por_periodo,
    obter_estado,
    limpar_sessao,
    defaults_simulacao,
    GRADE_PADRAO_JORNADAS,
    GRADE_PADRAO_EQUIPES,
)

app = FastAPI(title="Orca Web — Painel de Cenários")

templates = Jinja2Templates(directory="src/atm/web/templates")

# Custom Jinja2 filters
def _unique_filter(seq):
    """Remove duplicatas mantendo ordem."""
    seen = set()
    result = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def _selectattr_filter(seq, attr, *args):
    """Filtra objetos ou dicts por atributo/chave. Compatível com selectattr do Jinja2:
    selectattr(attr) = truthy, selectattr(attr, 'equalto', valor) = igualdade."""
    if len(args) == 2:
        test_name, value = args
        if test_name != "equalto":
            raise ValueError(f"teste não suportado: {test_name}")
        pred = lambda v: v == value
    elif len(args) == 0:
        pred = lambda v: bool(v)
    else:
        raise ValueError("uso: selectattr(attr) ou selectattr(attr, 'equalto', valor)")
    result = []
    for item in seq:
        # Tenta como dict primeiro, depois como objeto
        if isinstance(item, dict):
            item_value = item.get(attr)
        else:
            item_value = getattr(item, attr, None)
        if pred(item_value):
            result.append(item)
    return result

templates.env.filters["unique"] = _unique_filter
templates.env.filters["selectattr"] = _selectattr_filter


def _get_session_id(request: Request) -> str:
    """Obtém ou cria session_id do cookie."""
    session_id = request.cookies.get("orca_session")
    if not session_id:
        import uuid
        session_id = str(uuid.uuid4())[:8]
    return session_id


def _render_with_session(response: HTMLResponse, session_id: str) -> HTMLResponse:
    """Adiciona cookie de sessão à resposta."""
    response.set_cookie("orca_session", session_id, httponly=True, max_age=86400)
    return response


_DEFAULTS = defaults_simulacao()


def _ctx_painel(request: Request, session_id: str, state) -> Dict[str, Any]:
    """Contexto padrão do painel — inclui defaults derivados do scheduler (sem hardcode no HTML)."""
    return {
        "request": request,
        "session_id": session_id,
        "state": state,
        "tem_micro": bool(state.micro_rows),
        "tem_tarifas": bool(state.tarifas),
        "tem_cenarios": bool(state.cenarios),
        "erro": state.erro,
        "defaults": _DEFAULTS,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Painel principal — botões de ação."""
    session_id = _get_session_id(request)
    state = obter_estado(session_id)
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.post("/carregar-micro", response_class=HTMLResponse)
def post_carregar_micro(request: Request, session_id: str = Form(...)):
    """Carrega microatual.xlsx."""
    state = carregar_micro(session_id)
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.post("/carregar-tarifas", response_class=HTMLResponse)
def post_carregar_tarifas(request: Request, session_id: str = Form(...)):
    """Carrega ct317real.xlsx (tarifas)."""
    state = carregar_tarifas(session_id)
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.post("/validar", response_class=HTMLResponse)
def post_validar(request: Request, session_id: str = Form(...)):
    """Valida se micro e tarifas estão carregados."""
    state = validar_dados(session_id)
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.post("/simular", response_class=HTMLResponse)
def post_simular(
    request: Request,
    session_id: str = Form(...),
    jornadas: str = Form(_DEFAULTS["jornadas"]),
    equipes: str = Form(_DEFAULTS["equipes"]),
    executores_base: int = Form(_DEFAULTS["executores_base"]),
    jornada_base: float = Form(_DEFAULTS["jornada_base"]),
):
    """Roda grade de cenários (jornada × equipe) pelo scheduler REAL."""
    try:
        jornadas_l = [float(x.strip()) for x in jornadas.split(",") if x.strip()]
        equipes_l = [int(x.strip()) for x in equipes.split(",") if x.strip()]
    except ValueError:
        state = obter_estado(session_id)
        state.erro = "Jornadas/equipes inválidos. Use números separados por vírgula."
        response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
        return _render_with_session(response, session_id)
    
    state = simular(session_id, jornadas_l, equipes_l, executores_base, jornada_base)
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.post("/simular-unico", response_class=HTMLResponse)
def post_simular_unico(
    request: Request,
    session_id: str = Form(...),
    jornada: float = Form(_DEFAULTS["jornada_base"]),
    equipe: int = Form(_DEFAULTS["executores_base"]),
):
    """Roda UM cenário específico."""
    state = simular_unico(session_id, jornada, equipe)
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.post("/comparar-grade", response_class=HTMLResponse)
def post_comparar_grade(
    request: Request,
    session_id: str = Form(...),
):
    """Atalho: roda grade padrão (definida uma única vez no bridge)."""
    state = simular(
        session_id,
        GRADE_PADRAO_JORNADAS,
        GRADE_PADRAO_EQUIPES,
        executores_base=_DEFAULTS["executores_base"],
        jornada_base=_DEFAULTS["jornada_base"],
    )
    
    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, state))
    return _render_with_session(response, session_id)


@app.get("/resultado", response_class=HTMLResponse)
def get_resultado(request: Request, session_id: Optional[str] = None):
    """Painel de resultados — lista cenários com dias/meses/uso%."""
    sid = session_id or _get_session_id(request)
    state = obter_estado(sid)
    
    # Verifica se há dados financeiros disponíveis (modo_somente_hh=False e tarifas com preço/custo)
    modo_financeiro = not state.config.get("modo_somente_hh", True)
    tem_dados_financeiros = modo_financeiro and state.tarifas and any(
        t.get("preco_ha", 0) > 0 or t.get("custo_hora", 0) > 0 for t in state.tarifas.values()
    )
    
    response = templates.TemplateResponse(request, "resultado.html",
        {
            "request": request,
            "session_id": sid,
            "cenarios": state.cenarios,
            "erro": state.erro,
            "modo_financeiro": modo_financeiro,
            "tem_dados_financeiros": tem_dados_financeiros,
        },
    )
    return _render_with_session(response, sid)


def _preparar_dados_grafico_semana(agregacao_semana: Dict[str, Dict[str, float]]) -> Dict[str, List]:
    """Prepara labels e valores para gráfico de barras por semana (Chart.js)."""
    if not agregacao_semana:
        return {"labels": [], "datasets": []}
    
    # Ordena semanas
    def _semana_key(k):
        try:
            return int(k.replace("Semana ", ""))
        except (ValueError, AttributeError):
            return 999
    
    labels = sorted(agregacao_semana.keys(), key=_semana_key)
    
    # Coleta todas as fazendas
    fazendas = set()
    for semana_data in agregacao_semana.values():
        fazendas.update(semana_data.keys())
    fazendas = sorted(fazendas)
    
    datasets = []
    colors = [
        "rgba(94, 139, 255, 0.8)",   # accent
        "rgba(62, 207, 142, 0.8)",   # ok
        "rgba(232, 179, 75, 0.8)",   # warn
        "rgba(240, 106, 106, 0.8)",  # err
        "rgba(180, 120, 255, 0.8)",  # purple
        "rgba(255, 160, 60, 0.8)",   # orange
    ]
    
    for i, fazenda in enumerate(fazendas):
        data = []
        for label in labels:
            val = agregacao_semana.get(label, {}).get(fazenda, 0.0)
            data.append(round(val, 2))
        datasets.append({
            "label": fazenda,
            "data": data,
            "backgroundColor": colors[i % len(colors)],
            "borderColor": colors[i % len(colors)].replace("0.8", "1.0"),
            "borderWidth": 1,
        })
    
    return {"labels": labels, "datasets": datasets}


def _preparar_dados_grafico_mes(agregacao_mes: Dict[str, Dict[str, float]]) -> Dict[str, List]:
    """Prepara labels e valores para gráfico de barras por mês (Chart.js)."""
    if not agregacao_mes:
        return {"labels": [], "datasets": []}
    
    # Ordena meses
    def _mes_key(k):
        try:
            return int(k.replace("Mês ", ""))
        except (ValueError, AttributeError):
            return 999
    
    labels = sorted(agregacao_mes.keys(), key=_mes_key)
    
    # Coleta todas as fazendas
    fazendas = set()
    for mes_data in agregacao_mes.values():
        fazendas.update(mes_data.keys())
    fazendas = sorted(fazendas)
    
    datasets = []
    colors = [
        "rgba(94, 139, 255, 0.8)",   # accent
        "rgba(62, 207, 142, 0.8)",   # ok
        "rgba(232, 179, 75, 0.8)",   # warn
        "rgba(240, 106, 106, 0.8)",  # err
        "rgba(180, 120, 255, 0.8)",  # purple
        "rgba(255, 160, 60, 0.8)",   # orange
    ]
    
    for i, fazenda in enumerate(fazendas):
        data = []
        for label in labels:
            val = agregacao_mes.get(label, {}).get(fazenda, 0.0)
            data.append(round(val, 2))
        datasets.append({
            "label": fazenda,
            "data": data,
            "backgroundColor": colors[i % len(colors)],
            "borderColor": colors[i % len(colors)].replace("0.8", "1.0"),
            "borderWidth": 1,
        })
    
    return {"labels": labels, "datasets": datasets}


@app.get("/cronograma", response_class=HTMLResponse)
def get_cronograma(request: Request, session_id: Optional[str] = None):
    """Renderiza o cronograma real que simular_com_cronograma guarda em state.cronograma.
    
    Visual por talhão/fazenda: tabela com Dia, Talhão, Atividade, Turma, HH, Custo_MO (se modo financeiro).
    Limita a 200 linhas com aviso.
    """
    sid = session_id or _get_session_id(request)
    state = obter_estado(sid)
    
    modo_financeiro = not state.config.get("modo_somente_hh", True)
    
    # Precisa de cenários para saber qual simular
    if not state.cenarios:
        response = templates.TemplateResponse(request, "cronograma.html",
            {
                "request": request,
                "session_id": sid,
                "erro": "Nenhum cenário simulado. Rode a simulação primeiro.",
                "modo_financeiro": modo_financeiro,
            },
        )
        return _render_with_session(response, sid)
    
    # Usa o primeiro cenário como representativo
    cenario_ref = state.cenarios[0]
    jornada = cenario_ref["jornada"]
    equipe = cenario_ref["executores"]
    
    # Roda cenário com cronograma
    state = simular_com_cronograma(sid, jornada, equipe)
    
    if state.erro:
        response = templates.TemplateResponse(request, "cronograma.html",
            {
                "request": request,
                "session_id": sid,
                "erro": state.erro,
                "modo_financeiro": modo_financeiro,
            },
        )
        return _render_with_session(response, sid)
    
    cronograma = getattr(state, "cronograma", [])
    
    # Limita a 200 linhas
    limite = 200
    cronograma_exibicao = cronograma[:limite]
    avisar_limite = len(cronograma) > limite
    
    response = templates.TemplateResponse(request, "cronograma.html",
        {
            "request": request,
            "session_id": sid,
            "cenario_ref": cenario_ref,
            "cronograma": cronograma_exibicao,
            "total_linhas": len(cronograma),
            "limite_exibicao": limite,
            "avisar_limite": avisar_limite,
            "modo_financeiro": modo_financeiro,
        },
    )
    return _render_with_session(response, sid)


@app.get("/financeiro", response_class=HTMLResponse)
def get_financeiro(request: Request, session_id: Optional[str] = None):
    """Painel financeiro — agregação de custo/ganho por semana/mês.
    
    Roda um cenário representativo (primeiro da grade ou default) com cronograma
    e exibe agregação por período + gráfico Chart.js.
    """
    sid = session_id or _get_session_id(request)
    state = obter_estado(sid)
    
    modo_financeiro = not state.config.get("modo_somente_hh", True)
    
    # Precisa de cenários para saber qual simular
    if not state.cenarios:
        response = templates.TemplateResponse(request, "financeiro.html",
            {
                "request": request,
                "session_id": sid,
                "erro": "Nenhum cenário simulado. Rode a simulação primeiro.",
                "modo_financeiro": modo_financeiro,
            },
        )
        return _render_with_session(response, sid)
    
    # Usa o primeiro cenário como representativo
    cenario_ref = state.cenarios[0]
    jornada = cenario_ref["jornada"]
    equipe = cenario_ref["executores"]
    
    # Roda cenário com cronograma
    state = simular_com_cronograma(sid, jornada, equipe)
    
    if state.erro:
        response = templates.TemplateResponse(request, "financeiro.html",
            {
                "request": request,
                "session_id": sid,
                "erro": state.erro,
                "modo_financeiro": modo_financeiro,
            },
        )
        return _render_with_session(response, sid)
    
    # Agrega por semana e mês
    cronograma = getattr(state, "cronograma", [])
    agregacao_semana = agregar_por_periodo(cronograma, "semana", modo_somente_hh=not modo_financeiro)
    agregacao_mes = agregar_por_periodo(cronograma, "mes", modo_somente_hh=not modo_financeiro)
    
    # Prepara dados para Chart.js
    grafico_semana = _preparar_dados_grafico_semana(agregacao_semana)
    grafico_mes = _preparar_dados_grafico_mes(agregacao_mes)
    
    response = templates.TemplateResponse(request, "financeiro.html",
        {
            "request": request,
            "session_id": sid,
            "cenario_ref": cenario_ref,
            "agregacao_semana": agregacao_semana,
            "agregacao_mes": agregacao_mes,
            "grafico_semana": grafico_semana,
            "grafico_mes": grafico_mes,
            "modo_financeiro": modo_financeiro,
            "tem_dados_financeiros": modo_financeiro and cronograma,
        },
    )
    return _render_with_session(response, sid)


@app.post("/limpar", response_class=HTMLResponse)
def post_limpar(request: Request, session_id: str = Form(...)):
    """Limpa sessão e volta ao painel inicial."""
    limpar_sessao(session_id)

    response = templates.TemplateResponse(request, "painel.html", _ctx_painel(request, session_id, obter_estado(session_id)))
    return _render_with_session(response, session_id)
