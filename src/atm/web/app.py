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
    obter_estado,
    limpar_sessao,
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

def _selectattr_filter(seq, attr, value=None):
    """Filtra objetos ou dicts por atributo/chave."""
    result = []
    for item in seq:
        # Tenta como dict primeiro, depois como objeto
        if isinstance(item, dict):
            item_value = item.get(attr)
        else:
            item_value = getattr(item, attr, None)
        
        if value is None:
            if item_value:
                result.append(item)
        elif item_value == value:
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Painel principal — botões de ação."""
    session_id = _get_session_id(request)
    state = obter_estado(session_id)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.post("/carregar-micro", response_class=HTMLResponse)
async def post_carregar_micro(request: Request, session_id: str = Form(...)):
    """Carrega microatual.xlsx."""
    state = carregar_micro(session_id)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.post("/carregar-tarifas", response_class=HTMLResponse)
async def post_carregar_tarifas(request: Request, session_id: str = Form(...)):
    """Carrega ct317real.xlsx (tarifas)."""
    state = carregar_tarifas(session_id)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.post("/validar", response_class=HTMLResponse)
async def post_validar(request: Request, session_id: str = Form(...)):
    """Valida se micro e tarifas estão carregados."""
    state = validar_dados(session_id)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.post("/simular", response_class=HTMLResponse)
async def post_simular(
    request: Request,
    session_id: str = Form(...),
    jornadas: str = Form("7.5,8.0,9.0"),
    equipes: str = Form("2,3,4,5"),
):
    """Roda grade de cenários (jornada × equipe) pelo scheduler REAL."""
    try:
        jornadas_l = [float(x.strip()) for x in jornadas.split(",") if x.strip()]
        equipes_l = [int(x.strip()) for x in equipes.split(",") if x.strip()]
    except ValueError:
        state = obter_estado(session_id)
        state.erro = "Jornadas/equipes inválidos. Use números separados por vírgula."
        response = templates.TemplateResponse(
            "painel.html",
            {
                "request": request,
                "session_id": session_id,
                "state": state,
                "tem_micro": bool(state.micro_rows),
                "tem_tarifas": bool(state.tarifas),
                "tem_cenarios": bool(state.cenarios),
                "erro": state.erro,
            },
        )
        return _render_with_session(response, session_id)
    
    state = simular(session_id, jornadas_l, equipes_l)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.post("/simular-unico", response_class=HTMLResponse)
async def post_simular_unico(
    request: Request,
    session_id: str = Form(...),
    jornada: float = Form(7.5),
    equipe: int = Form(4),
):
    """Roda UM cenário específico."""
    state = simular_unico(session_id, jornada, equipe)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.post("/comparar-grade", response_class=HTMLResponse)
async def post_comparar_grade(
    request: Request,
    session_id: str = Form(...),
):
    """Atalho: roda grade padrão (jornadas 7.5/8/9 × equipes 2/3/4/5)."""
    state = simular(session_id, [7.5, 8.0, 9.0], [2, 3, 4, 5])
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": state,
            "tem_micro": bool(state.micro_rows),
            "tem_tarifas": bool(state.tarifas),
            "tem_cenarios": bool(state.cenarios),
            "erro": state.erro,
        },
    )
    return _render_with_session(response, session_id)


@app.get("/resultado", response_class=HTMLResponse)
async def get_resultado(request: Request, session_id: Optional[str] = None):
    """Painel de resultados — lista cenários com dias/meses/uso%."""
    sid = session_id or _get_session_id(request)
    state = obter_estado(sid)
    
    response = templates.TemplateResponse(
        "resultado.html",
        {
            "request": request,
            "session_id": sid,
            "cenarios": state.cenarios,
            "erro": state.erro,
        },
    )
    return _render_with_session(response, sid)


@app.post("/limpar", response_class=HTMLResponse)
async def post_limpar(request: Request, session_id: str = Form(...)):
    """Limpa sessão e volta ao painel inicial."""
    limpar_sessao(session_id)
    
    response = templates.TemplateResponse(
        "painel.html",
        {
            "request": request,
            "session_id": session_id,
            "state": obter_estado(session_id),
            "tem_micro": False,
            "tem_tarifas": False,
            "tem_cenarios": False,
            "erro": None,
        },
    )
    return _render_with_session(response, session_id)