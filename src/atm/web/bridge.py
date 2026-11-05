"""Ponte síncrona para o motor real — roda em thread pool (não bloqueia o loop do FastAPI)."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from ..orca.comparativo_real import simular_cenarios_reais, simular_cenario_real
from ..orca.io import (
    carregar_planilha_microplanejamento,
    _find_default_micro_path,
    _find_default_ct_path,
    buscar_arquivos_excel,
)
from ..orca.tarifas import carregar_stg_tarifas
from ..orca.config import carregar_config
from ..orca.schemas import MicroRow, micro_de_dataframe, tarifas_de_dict


_executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class SessionState:
    """Estado por session_id (nunca PID)."""
    session_id: str
    micro_rows: List[MicroRow] = field(default_factory=list)
    tarifas: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    cenarios: List[Dict[str, Any]] = field(default_factory=list)
    erro: Optional[str] = None


_sessions: Dict[str, SessionState] = {}


def _get_or_create_session(session_id: Optional[str] = None) -> SessionState:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    new_id = session_id or str(uuid.uuid4())[:8]
    state = SessionState(session_id=new_id)
    _sessions[new_id] = state
    return state


def _run_in_thread(fn, *args, **kwargs):
    """Executa função síncrona no thread pool."""
    future = _executor.submit(fn, *args, **kwargs)
    return future.result()


def _encontrar_micro_path(cfg: Dict[str, Any]) -> Optional[str]:
    """Encontra caminho do microatual.xlsx."""
    # Tenta config.json primeiro
    path = _find_default_micro_path(cfg)
    if path and os.path.exists(path):
        return path
    # Fallback: procura em data/planilhas/
    base = os.path.join(os.getcwd(), "data", "planilhas")
    for nome in ["microatual.xlsx", "exame.xlsx", "EXAME.xlsx"]:
        p = os.path.join(base, nome)
        if os.path.exists(p):
            return p
    return None


def _encontrar_ct_path() -> Optional[str]:
    """Encontra caminho do CT (tarifas)."""
    path = _find_default_ct_path()
    if path and os.path.exists(path):
        return path
    # Fallback: procura STG_TARIFAS.xlsx gerado
    base = os.path.join(os.getcwd(), "data", "planilhas")
    for nome in ["STG_TARIFAS.xlsx", "stg_tarifas.xlsx"]:
        p = os.path.join(base, nome)
        if os.path.exists(p):
            return p
    # Procura CT direto
    for f in buscar_arquivos_excel():
        n = f.lower()
        if "ct317" in n or ("ct" in n and "317" in n):
            return os.path.join(os.getcwd(), "data", "planilhas", f)
    return None


def carregar_micro(session_id: str, caminho: Optional[str] = None) -> SessionState:
    """Carrega microatual.xlsx e armazena na sessão."""
    state = _get_or_create_session(session_id)
    try:
        cfg = carregar_config()
        state.config = cfg
        
        if not caminho:
            caminho = _encontrar_micro_path(cfg)
        
        if not caminho or not os.path.exists(caminho):
            state.erro = f"Arquivo micro não encontrado: {caminho}"
            return state
        
        # Carrega em modo automático (sem prompts interativos)
        df = carregar_planilha_microplanejamento(cfg, caminho=caminho, modo_auto=True)
        
        if df is None:
            state.erro = "Falha ao carregar micro (modo automático)"
            return state
        
        state.micro_rows = micro_de_dataframe(df)
        state.erro = None
    except Exception as e:
        state.erro = f"Erro ao carregar micro: {e}"
    return state


def carregar_tarifas(session_id: str, caminho: Optional[str] = None) -> SessionState:
    """Carrega tarifas (STG_TARIFAS.xlsx ou CT) e armazena na sessão."""
    state = _get_or_create_session(session_id)
    try:
        if not caminho:
            caminho = _encontrar_ct_path()
        
        if not caminho or not os.path.exists(caminho):
            state.erro = f"Arquivo de tarifas não encontrado: {caminho}"
            return state
        
        # Se for STG_TARIFAS.xlsx, usa carregar_stg_tarifas
        if "stg_tarifas" in caminho.lower():
            state.tarifas = carregar_stg_tarifas(caminho)
        else:
            # CT bruto: precisa processar via modulo_importar_tarifas
            # Para simplificar, tenta carregar como STG se tiver a aba correta
            try:
                state.tarifas = carregar_stg_tarifas(caminho)
            except Exception:
                state.erro = "Arquivo CT precisa ser processado primeiro (gere STG_TARIFAS.xlsx via CLI)"
                return state
        
        state.erro = None
    except Exception as e:
        state.erro = f"Erro ao carregar tarifas: {e}"
    return state


def validar_dados(session_id: str) -> SessionState:
    """Valida se micro e tarifas estão carregados."""
    state = _get_or_create_session(session_id)
    if not state.micro_rows:
        state.erro = "Micro não carregado. Carregue o microatual.xlsx primeiro."
    elif not state.tarifas:
        state.erro = "Tarifas não carregadas. Carregue o ct317real.xlsx (ou STG_TARIFAS.xlsx) primeiro."
    else:
        state.erro = None
    return state


def _construir_demanda(micro_rows: List[MicroRow], tarifas: Dict[str, Any]) -> Dict[Any, float]:
    """Constrói dicionário de demanda a partir do micro e tarifas."""
    demanda: Dict[Any, float] = {}
    for row in micro_rows:
        talhao = row.chave  # schemas usa 'chave' para talhão
        atividade = row.atividade
        area = float(row.area_ha)
        # Busca rendimento hm (hectare/mês) ou hh (hora/homem)
        tarifa = tarifas.get(atividade, {})
        rendimento_hm = tarifa.get("rendimento_hm", 0.0)
        if rendimento_hm and rendimento_hm > 0:
            hh = area / rendimento_hm
        else:
            rendimento_hh = tarifa.get("rendimento_hh", 0.0)
            hh = area * rendimento_hh if rendimento_hh else area
        demanda[(talhao, atividade)] = round(hh, 2)
    return demanda


def simular(session_id: str, jornadas: List[float], equipes: List[int]) -> SessionState:
    """Roda a grade de cenários pelo scheduler REAL via thread pool."""
    state = _get_or_create_session(session_id)
    state.erro = None
    
    try:
        config = state.config or carregar_config()
        jornada_base = float(config.get("jornada", 7.5))
        executores_base = int(config.get("executores", 4))
        
        # Constrói demanda real
        demanda = _construir_demanda(state.micro_rows, state.tarifas)
        
        if not demanda:
            state.erro = "Nenhuma demanda construída — verifique micro e tarifas"
            return state
        
        # Roda grade de cenários no scheduler real
        cenarios = _run_in_thread(
            simular_cenarios_reais,
            demanda,
            executores_base,
            jornada_base,
            jornadas=jornadas,
            equipes=equipes,
        )
        state.cenarios = cenarios
    except Exception as e:
        state.erro = f"Erro na simulação: {e}"
        state.cenarios = []
    
    return state


def simular_unico(session_id: str, jornada: float, equipe: int) -> SessionState:
    """Roda UM cenário pelo scheduler REAL."""
    state = _get_or_create_session(session_id)
    state.erro = None
    
    try:
        config = state.config or carregar_config()
        jornada_base = float(config.get("jornada", 7.5))
        executores_base = int(config.get("executores", 4))
        
        demanda = _construir_demanda(state.micro_rows, state.tarifas)
        
        if not demanda:
            state.erro = "Nenhuma demanda construída — verifique micro e tarifas"
            return state
        
        cenario = _run_in_thread(
            simular_cenario_real,
            demanda,
            executores=equipe,
            jornada=jornada,
        )
        state.cenarios = [cenario]
    except Exception as e:
        state.erro = f"Erro na simulação: {e}"
        state.cenarios = []
    
    return state


def obter_estado(session_id: str) -> SessionState:
    """Retorna estado atual da sessão."""
    return _get_or_create_session(session_id)


def limpar_sessao(session_id: str) -> None:
    """Remove sessão."""
    _sessions.pop(session_id, None)