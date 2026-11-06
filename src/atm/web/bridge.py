"""Ponte síncrona para o motor real — roda em thread pool (não bloqueia o loop do FastAPI)."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import pandas as pd

from ..orca.comparativo_real import simular_cenarios_reais, simular_cenario_real
from ..orca.io import (
    carregar_planilha_microplanejamento,
    _find_default_micro_path,
    _find_default_ct_path,
    buscar_arquivos_excel,
)
from ..orca.tarifas import carregar_stg_tarifas
from ..orca.config import carregar_config, modo_somente_hh
from ..orca.schemas import MicroRow, micro_de_dataframe, tarifas_de_dict
from ..orca.scheduler_core import _JORNADA_DEFAULT_H
from ..orca.engine_pkg.engine import _construir_demandas


# Defaults reais do scheduler (não do config.json)
_JORNADA_DEFAULT = _JORNADA_DEFAULT_H  # 4.6h
_EXECUTORES_DEFAULT = 9  # padrão do prompt interativo

# Grade padrão de cenários (mesma usada pelo CLI) — fonte única, sem duplicar em HTML/app.py
GRADE_PADRAO_JORNADAS = [4.6, 6.0, 8.0]
GRADE_PADRAO_EQUIPES = [4, 6, 9, 12]


def defaults_simulacao() -> Dict[str, Any]:
    """Defaults exibidos no painel (modo simples/detalhado) — derivados do scheduler, não hardcoded no HTML."""
    return {
        "jornadas": ",".join(str(j) for j in GRADE_PADRAO_JORNADAS),
        "equipes": ",".join(str(e) for e in GRADE_PADRAO_EQUIPES),
        "executores_base": _EXECUTORES_DEFAULT,
        "jornada_base": _JORNADA_DEFAULT,
    }


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
    """Encontra caminho do CT (tarifas).

    O painel só lê o formato STG (STG_TARIFAS.xlsx / CT_317_NORMALIZADA.xlsx) —
    CT cru precisa ser processado antes (normalizar_ct313 via CLI). Por isso o STG
    tem prioridade sobre o path default, que aponta pro CT cru.
    """
    # STG processado tem prioridade (é o que carregar_stg_tarifas sabe ler)
    base = os.path.join(os.getcwd(), "data", "planilhas")
    for nome in ["STG_TARIFAS.xlsx", "CT_317_NORMALIZADA.xlsx", "stg_tarifas.xlsx"]:
        p = os.path.join(base, nome)
        if os.path.exists(p):
            return p
    # Sem STG: cai no path default (CT cru) — o loader vai orientar a processar
    path = _find_default_ct_path()
    if path and os.path.exists(path):
        return path
    # Procura CT direto
    for f in buscar_arquivos_excel():
        n = f.lower()
        if "ct317" in n or ("ct" in n and "317" in n):
            return os.path.join(os.getcwd(), "data", "planilhas", f)
    return None


def _micro_rows_para_dataframe(micro_rows: List[MicroRow]) -> pd.DataFrame:
    """Converte lista de MicroRow para DataFrame compatível com _construir_demandas."""
    data = []
    for row in micro_rows:
        data.append({
            "fazenda": row.fazenda,
            "chave": row.chave,
            "area_ha": row.area_ha,
            "atividade": row.atividade,
            "penalidade": row.penalidade,
            "equipe": row.equipe,
            "municipio": row.municipio,
            "estado": row.estado,
            "metodologia": row.metodologia,
        })
    return pd.DataFrame(data)


def _construir_demanda_canonica(
    micro_rows: List[MicroRow],
    tarifas: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[Any, float]:
    """Constrói dicionário de demanda usando o construtor CANÔNICO do motor.

    Reutiliza _construir_demandas de engine_pkg/engine.py que:
    - Aplica de_para (mapeamento atividade micro -> chave tarifa)
    - Usa resolver_rendimento_hh com fallback correto (mediana/8.0)
    - Aplica penalidade
    - Identifica HM-only corretamente (não vira HH fake)
    - Respeita regra "HH zera HM"

    Retorna: Dict[(talhao, atividade_micro), float] com HH total por talhão/atividade.
    """
    if not micro_rows:
        return {}

    df_faz = _micro_rows_para_dataframe(micro_rows)

    # Extrai talhões ordenados e atividades reais
    talhoes_ordenados = sorted(df_faz["chave"].unique().tolist())
    atividades_reais = sorted(df_faz["atividade"].unique().tolist())

    # Parâmetros para o construtor canônico
    strict = cfg.get("orcamento_estrito", True)
    session_hh = {}  # sem overrides de HH em sessão no painel web
    # Passa a FUNÇÃO modo_somente_hh (callable), não o resultado booleano
    # O motor chama modo_somente_hh(cfg) internamente

    # Chama o construtor canônico
    resultado = _construir_demandas(
        talhoes_ordenados=talhoes_ordenados,
        df_faz=df_faz,
        cfg=cfg,
        tarifas=tarifas,
        strict=strict,
        session_hh=session_hh,
        modo_somente_hh=modo_somente_hh,
        atividades_reais=atividades_reais,
    )

    # Converte o resultado para o formato esperado por simular():
    # Dict[(talhao, atividade_micro)] -> float (HH total)
    demanda: Dict[Any, float] = {}
    for talhao, tarefas in resultado["demandas"].items():
        for tarefa in tarefas:
            # tarefa["atividade"] é o nome original do micro (atividade_micro)
            # tarefa["hh_total"] já inclui penalidade e usa rendimento_hh correto
            if tarefa["hh_total"] > 0:
                demanda[(talhao, tarefa["atividade"])] = round(tarefa["hh_total"], 2)

    return demanda


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


def simular(
    session_id: str,
    jornadas: List[float],
    equipes: List[int],
    executores_base: int = _EXECUTORES_DEFAULT,
    jornada_base: float = _JORNADA_DEFAULT,
) -> SessionState:
    """Roda a grade de cenários pelo scheduler REAL via thread pool.
    
    Args:
        executores_base: total de operários (default 9, do scheduler)
        jornada_base: horas por dia (default 4.6h, do scheduler)
    """
    state = _get_or_create_session(session_id)
    state.erro = None
    
    try:
        # Constrói demanda real usando o construtor CANÔNICO
        demanda = _construir_demanda_canonica(state.micro_rows, state.tarifas, state.config)
        
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


def simular_unico(
    session_id: str,
    jornada: float,
    equipe: int,
) -> SessionState:
    """Roda UM cenário pelo scheduler REAL."""
    state = _get_or_create_session(session_id)
    state.erro = None
    
    try:
        demanda = _construir_demanda_canonica(state.micro_rows, state.tarifas, state.config)
        
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


# ──────────────────────────────────────────────
# AGREGAÇÃO FINANCEIRA — Semana / Mês
# ──────────────────────────────────────────────

def simular_com_cronograma(
    session_id: str,
    jornada: float,
    equipe: int,
) -> SessionState:
    """Roda UM cenário pelo scheduler REAL e retorna cronograma completo no estado.
    
    Diferente de simular_unico, esta função também armazena o cronograma detalhado
    (com Custo_MO por linha) em state.cronograma para uso na agregação financeira.
    """
    state = _get_or_create_session(session_id)
    state.erro = None
    
    try:
        demanda = _construir_demanda_canonica(state.micro_rows, state.tarifas, state.config)
        
        if not demanda:
            state.erro = "Nenhuma demanda construída — verifique micro e tarifas"
            return state
        
        # Importa a função interna que retorna o cronograma
        from ..orca.comparativo_real import _config_cenario
        from ..orca.engine_pkg.engine import _executar_scheduler_loop
        
        turmas = [{"nome": "Geral", "operarios": int(equipe)}]
        config = _config_cenario(demanda, turmas, jornada)
        # _config_cenario entrega cfg/tarifas vazios (caminho de métricas é HH puro);
        # o cronograma financeiro precisa das tarifas reais da sessão (Custo_MO por linha).
        config.cfg = state.config or {}
        config.tarifas = state.tarifas or {}
        
        cronograma, dias, demanda_restante = _run_in_thread(
            _executar_scheduler_loop, config
        )
        
        total_hh = sum(v for v in demanda.values())
        pendente = sum(v for v in demanda_restante.values() if v > 0.01)
        capacidade_dia = float(equipe) * float(jornada)
        uso_pct = (100.0 * total_hh / (dias * capacidade_dia)) if dias > 0 and capacidade_dia > 0 else 0.0
        
        state.cenarios = [{
            "executores": int(equipe),
            "jornada": float(jornada),
            "dias_simulados": int(dias),
            "meses_simulados": round(dias / 22.0, 2),
            "hh_total": round(total_hh, 2),
            "hh_pendente": round(pendente, 2),
            "linhas_cronograma": len(cronograma),
            "capacidade_dia_hh": round(capacidade_dia, 2),
            "uso_capacidade_pct": round(uso_pct, 1),
            "aprovacao": "COMPLETO" if pendente <= 0.01 else "INCOMPLETO",
        }]
        # Armazena cronograma para agregação financeira
        state.cronograma = cronograma
        
    except Exception as e:
        state.erro = f"Erro na simulação: {e}"
        state.cenarios = []
        state.cronograma = []
    
    return state


def agregar_por_periodo(
    cronograma: List[Dict[str, Any]],
    periodo: str = "semana",
    modo_somente_hh: bool = True,
) -> Dict[str, Dict[str, float]]:
    """Agrega custos/HH por período (semana/mês) e por fazenda.
    
    Args:
        cronograma: Lista de linhas do cronograma (cada linha tem Dia, Fazenda, HH, Custo_MO).
        periodo: "semana" ou "mes".
        modo_somente_hh: Se True, retorna apenas HH (degradação quando sem dados financeiros).
        
    Returns:
        Dict[periodo_key, Dict[fazenda, valor]] onde valor é HH ou Custo_MO.
        NUNCA inventa número: sem tarifa = linha sem Custo_MO (não entra no sum).
        
    Exemplos de chaves de retorno:
        - semana: "Semana 1", "Semana 2", ...
        - mes: "Mês 1", "Mês 2", ...
    """
    from collections import defaultdict
    import math
    
    if not cronograma:
        return {}
    
    resultado: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    DIAS_UTEIS_POR_MES = 22.0
    
    for linha in cronograma:
        dia = int(linha.get("Dia", 0))
        fazenda = str(linha.get("Fazenda", "SEM_FAZENDA"))
        hh = float(linha.get("HH", 0.0))
        custo_mo = linha.get("Custo_MO")
        
        if periodo == "semana":
            # Semana 1 = dias 1-5, Semana 2 = dias 6-10, etc.
            semana = (dia - 1) // 5 + 1
            chave = f"Semana {semana}"
        elif periodo == "mes":
            # Mês 1 = dias 1-22, Mês 2 = dias 23-44, etc.
            mes = math.ceil(dia / DIAS_UTEIS_POR_MES)
            chave = f"Mês {mes}"
        else:
            raise ValueError(f"periodo deve ser 'semana' ou 'mes', recebido: {periodo}")
        
        if modo_somente_hh:
            # Modo HH-only: soma HH (degradação quando sem dados financeiros)
            resultado[chave][fazenda] += hh
        else:
            # Modo financeiro: soma Custo_MO apenas quando existe e > 0
            # NUNCA inventa número: sem tarifa (Custo_MO None/0) = linha não entra no sum
            if custo_mo is not None and custo_mo > 0:
                resultado[chave][fazenda] += custo_mo
            # Se Custo_MO é None ou 0: não soma nada (linha sem valor financeiro)
    
    # Converte defaultdict para dict normal
    return {k: dict(v) for k, v in resultado.items()}


def resumir_por_dia(cronograma: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resume o cronograma por dia: HH total, Custo_MO total e atividades (ordenado por dia)."""
    from collections import defaultdict

    acc: Dict[Any, Dict[str, Any]] = {}
    for linha in cronograma:
        dia = linha.get("Dia", 0)
        if dia not in acc:
            acc[dia] = {"dia": dia, "hh": 0.0, "custo": 0.0, "atividades": []}
        a = acc[dia]
        a["hh"] += float(linha.get("HH") or 0.0)
        custo = linha.get("Custo_MO")
        if custo is not None:
            a["custo"] += float(custo or 0.0)
        atv = str(linha.get("Atividade") or "")
        if atv and atv not in a["atividades"]:
            a["atividades"].append(atv)
    return [acc[d] for d in sorted(acc)]


def agregar_ganho_por_periodo(
    cronograma: List[Dict[str, Any]],
    demandas_originais: Dict[Any, float],
    tarifas: Dict[str, Any],
    periodo: str = "semana",
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Calcula ganho (receita - custo) por período e fazenda.
    
    Args:
        cronograma: Linhas do cronograma com Dia, Fazenda, HH, Custo_MO.
        demandas_originais: Dict[(talhao, atividade)] -> HH total (do _construir_demanda_canonica).
        tarifas: Dict de tarifas com preco_ha.
        periodo: "semana" ou "mes".
        
    Returns:
        Dict[periodo_key, Dict[fazenda, {"receita": float, "custo": float, "ganho": float, "hh": float}]]
        
    Nota: Receita é calculada uma vez (area * preco_ha) e rateada linearmente nos dias do cronograma.
    Sem tarifa/preco = receita 0 para aquela atividade (não inventa número).
    """
    from collections import defaultdict
    import math
    
    if not cronograma:
        return {}
    
    DIAS_UTEIS_POR_MES = 22.0
    
    # Calcula receita total por fazenda a partir das demandas originais
    receita_por_fazenda: Dict[str, float] = defaultdict(float)
    for (talhao, atividade), hh_total in demandas_originais.items():
        if hh_total <= 0:
            continue
        # Encontra a tarifa para esta atividade
        tarifa = tarifas.get(atividade, {})
        preco_ha = tarifa.get("preco_ha", 0.0)
        if preco_ha <= 0:
            continue  # Sem preço = receita 0 (não inventa)
        # Para obter area, precisamos do HH e rendimento: area = hh / (rendimento_hh * penalidade)
        # Como não temos penalidade aqui, usamos aproximação: assumimos que a receita
        # é proporcional ao HH executado no dia
        pass
    
    # Como não temos area direta no cronograma, usamos abordagem simplificada:
    # Receita total = soma de (HH_total_atividade / rendimento_hh) * preco_ha
    # Mas isso precisa da tarifa original...
    # Para MVP: retorna estrutura vazia - implementação completa precisa de mais dados
    return {}