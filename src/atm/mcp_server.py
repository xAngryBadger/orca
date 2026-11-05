"""Servidor MCP do Orca — expõe o motor de cálculo para agentes de IA.

Protocolo: MCP (Model Context Protocol) sobre stdio, JSON-RPC 2.0.
Implementação própria, sem dependência externa: nenhum pip install
necessário, roda em qualquer Python 3.10+.

Um agente de IA (Claude Code, Cursor, etc.) descobre as ferramentas com
tools/list e chama com tools/call. O motor continua sendo a fonte da
verdade: o MCP só orquestra, nunca calcula por conta própria.

Ferramentas expostas:
  orca_carregar_micro      Carrega planilha de microplanejamento
  orca_listar_fazendas     Lista fazendas/talhões/atividades do micro
  orca_carregar_tarifas    Carrega/normaliza CT313/CT317
  orca_validar_pipeline    Roda o gate de validação cruzada
  orca_simular_cenario     Roda UM cenário pelo scheduler real
  orca_comparar_cenarios   Grade multi-fator pelo scheduler real
  orca_metricas            Métricas de um cenário já calculado

Recursos expostos (leitura):
  orca://baseline          Manifesto de integridade + HEAD
  orca://schemas           JSON Schema dos contratos
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

_RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_RAIZ_REPO, os.path.join(_RAIZ_REPO, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from atm.orca import comparativo_real, config as orca_config, io as orca_io  # noqa: E402
from atm.orca.config import _default_sequencia_dict  # noqa: E402
from atm.orca.constants import (  # noqa: E402
    CT317_HARDCODE_HH_BASE,
    DEFAULT_DEPARA_EXAME_CT317,
)
from atm.orca.engine_pkg import (  # noqa: E402
    _construir_demandas,
    _executar_scheduler_loop,
)
from atm.orca.schemas import (  # noqa: E402
    PipelineConfig,
    depara_de_dict,
    micro_de_dataframe,
    tarifas_de_dict,
)

_SESSAO: Dict[str, Any] = {
    "cfg": None,
    "micro": None,
    "tarifas": None,
    "de_para": None,
    "ultimo_cenario": None,
}


def _ok(id_req: Any, resultado: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_req, "result": resultado}


def _erro(id_req: Any, codigo: int, mensagem: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_req, "error": {"code": codigo, "message": mensagem}}


def _texto(conteudo: Any) -> Dict[str, Any]:
    if not isinstance(conteudo, str):
        conteudo = json.dumps(conteudo, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": conteudo}]}


def _cfg() -> Dict[str, Any]:
    if _SESSAO["cfg"] is None:
        _SESSAO["cfg"] = orca_config.carregar_config()
    return _SESSAO["cfg"]


def _tarifas_padrao() -> Dict[str, Any]:
    """Tarifas do hardcode CT317 — caminho real de fallback do motor."""
    saida: Dict[str, Any] = {}
    for nome, base in CT317_HARDCODE_HH_BASE.items():
        saida[nome] = {
            "atividade": nome,
            "rendimento_hh": base["rendimento_hh"],
            "rendimento_hm": base["rendimento_hm"],
            "tipo": base.get("tipo", "Manual"),
            "preco_ha": 0.0,
            "custo_hora": 0.0,
            "recurso": "homem" if base["rendimento_hh"] > 0 else "maquina",
        }
    return saida


def _demanda_do_micro(df: pd.DataFrame) -> Dict[Any, float]:
    """Monta o dict de demanda que o scheduler consome."""
    demanda: Dict[Any, float] = {}
    for _, row in df.iterrows():
        chave = (str(row["chave"]), str(row["atividade"]))
        demanda[chave] = float(row.get("area_ha", 0) or 0)
    return demanda


# ──────────────────────────────────────────────
# FERRAMENTAS
# ────────────────────────────���──────────────────

def tool_carregar_micro(args: Dict[str, Any]) -> Dict[str, Any]:
    caminho = args.get("caminho")
    if not caminho:
        raise ValueError("parâmetro 'caminho' é obrigatório")
    if not os.path.isfile(caminho):
        raise FileNotFoundError(f"planilha não encontrada: {caminho}")

    cfg = _cfg()
    df = orca_io.carregar_planilha_microplanejamento(
        cfg, caminho=caminho, modo_auto=bool(args.get("modo_auto", True))
    )
    if df is None:
        raise RuntimeError(
            "o loader recusou a planilha. Em modo_auto as colunas obrigatórias "
            "(fazenda, chave, area, atividade) precisam existir; o erro lista as disponíveis."
        )
    _SESSAO["micro"] = df
    return {
        "arquivo": os.path.basename(caminho),
        "linhas": int(len(df)),
        "fazendas": sorted(df["fazenda"].dropna().unique().tolist()),
        "talhoes": int(df["chave"].nunique()),
        "atividades": sorted(df["atividade"].dropna().unique().tolist()),
    }


def tool_listar_fazendas(args: Dict[str, Any]) -> Dict[str, Any]:
    df = _SESSAO.get("micro")
    if df is None:
        raise RuntimeError("nenhum micro carregado — chame orca_carregar_micro antes")
    resumo = []
    for fazenda, grupo in df.groupby("fazenda"):
        resumo.append(
            {
                "fazenda": str(fazenda),
                "talhoes": int(grupo["chave"].nunique()),
                "atividades": int(grupo["atividade"].nunique()),
                "area_total_ha": round(float(grupo["area_ha"].sum()), 2),
            }
        )
    return {"fazendas": sorted(resumo, key=lambda x: x["fazenda"])}


def tool_carregar_tarifas(args: Dict[str, Any]) -> Dict[str, Any]:
    """Sem argumentos: usa o fallback CT317 (caminho real do motor)."""
    ct = args.get("caminho_ct")
    if ct:
        if not os.path.isfile(ct):
            raise FileNotFoundError(f"CT não encontrada: {ct}")
        from atm.orca.tarifas import carregar_stg_tarifas, normalizar_ct313

        stg_path, n_tarifas, custo_h = normalizar_ct313(ct)
        if not stg_path:
            raise RuntimeError(
                "aba 'Preco Final' não encontrada nesta CT — o normalizador não reconheceu o layout."
            )
        tarifas = carregar_stg_tarifas(stg_path)
        _SESSAO["tarifas"] = tarifas
        return {
            "fonte": f"CT normalizado ({os.path.basename(ct)})",
            "tarifas": len(tarifas),
            "custo_hora_tf": custo_h,
        }
    tarifas = _tarifas_padrao()
    _SESSAO["tarifas"] = tarifas
    return {
        "fonte": "CT317_HARDCODE_HH_BASE (fallback do motor)",
        "tarifas": len(tarifas),
        "hm_only": sum(1 for v in tarifas.values() if v["rendimento_hh"] <= 0 and v["rendimento_hm"] > 0),
    }


def tool_validar_pipeline(args: Dict[str, Any]) -> Dict[str, Any]:
    df = _SESSAO.get("micro")
    tarifas = _SESSAO.get("tarifas") or _tarifas_padrao()
    if df is None:
        raise RuntimeError("nenhum micro carregado — chame orca_carregar_micro antes")
    cfg = _cfg()
    de_para = dict(DEFAULT_DEPARA_EXAME_CT317)
    de_para.update(cfg.get("de_para", {}) or {})
    pipeline = PipelineConfig(
        micro=micro_de_dataframe(df),
        tarifas=tarifas_de_dict(tarifas),
        de_para=depara_de_dict(de_para),
    )
    return {
        "cobertura": pipeline.cobertura(),
        "atividades_sem_tarifa": pipeline.actividades_sem_tarifa(),
        "veredicto": "PASSOU" if pipeline.cobertura()["atividades_sem_tarifa"] == 0 else "BARROU",
    }


def tool_simular_cenario(args: Dict[str, Any]) -> Dict[str, Any]:
    """Roda um cenário pelo scheduler real. Nunca aproxima."""
    df = _SESSAO.get("micro")
    if df is None:
        raise RuntimeError("nenhum micro carregado — chame orca_carregar_micro antes")

    executores = int(args.get("executores", 9))
    jornada = float(args.get("jornada", 6.5))
    fazenda = args.get("fazenda")

    df_uso = df if fazenda is None else df[df["fazenda"] == fazenda]
    if df_uso.empty:
        raise ValueError(f"fazenda '{fazenda}' não existe no micro carregado")

    if "penalidade" not in df_uso.columns:
        df_uso = df_uso.copy()
        df_uso["penalidade"] = float(args.get("penalidade", 1.0))

    tarifas = _SESSAO.get("tarifas") or _tarifas_padrao()
    cfg = _cfg()
    cfg["tarifas"] = tarifas
    cfg["orcamento_estrito"] = False
    de_para = dict(DEFAULT_DEPARA_EXAME_CT317)
    de_para.update(cfg.get("de_para", {}) or {})
    cfg["de_para"] = de_para

    atvs = sorted(df_uso["atividade"].dropna().unique().tolist())
    talhoes = sorted(df_uso["chave"].dropna().unique().tolist())

    demandas = _construir_demandas(
        talhoes, df_uso, cfg, tarifas, False, {}, orca_config.modo_somente_hh, atvs
    )
    d = demandas["demandas"]
    demanda_plana = {
        (th, t["atividade"]): t["hh_total"]
        for th, tl in d.items()
        for t in tl
    }

    turmas = [{"nome": "Geral", "operarios": executores}]
    config = _config_cenario_mcp(demanda_plana, turmas, jornada)
    cronograma, dias, restante = _executar_scheduler_loop(config)

    hh_total = demandas["total_hh"]
    resultado = {
        "fazenda": fazenda or "(todas)",
        "executores": executores,
        "jornada": jornada,
        "dias_simulados": int(dias),
        "meses_simulados": round(dias / 22.0, 2),
        "hh_total": round(hh_total, 1),
        "hm_total": round(demandas["total_hm"], 1),
        "talhoes": len(talhoes),
        "atividades": len(atvs),
        "linhas_cronograma": len(cronograma),
        "hh_pendente": round(sum(v for v in restante.values() if v > 0.01), 2),
        "veredicto": "COMPLETO" if sum(v for v in restante.values() if v > 0.01) <= 0.01 else "INCOMPLETO",
    }
    _SESSAO["ultimo_cenario"] = resultado
    return resultado


def tool_comparar_cenarios(args: Dict[str, Any]) -> Dict[str, Any]:
    """Grade multi-fator pelo scheduler REAL (não a aproximação)."""
    df = _SESSAO.get("micro")
    if df is None:
        raise RuntimeError("nenhum micro carregado — chame orca_carregar_micro antes")

    jornadas = args.get("jornadas") or [4.3, 6.5, 8.8]
    equipes = args.get("equipes") or [6, 9, 12]
    fazenda = args.get("fazenda")

    df_uso = df if fazenda is None else df[df["fazenda"] == fazenda]
    if df_uso.empty:
        raise ValueError(f"fazenda '{fazenda}' não existe")

    if "penalidade" not in df_uso.columns:
        df_uso = df_uso.copy()
        df_uso["penalidade"] = 1.0

    tarifas = _SESSAO.get("tarifas") or _tarifas_padrao()
    cfg = _cfg()
    cfg["tarifas"] = tarifas
    cfg["orcamento_estrito"] = False
    de_para = dict(DEFAULT_DEPARA_EXAME_CT317)
    de_para.update(cfg.get("de_para", {}) or {})
    cfg["de_para"] = de_para

    atvs = sorted(df_uso["atividade"].dropna().unique().tolist())
    demandas = _construir_demandas(
        sorted(df_uso["chave"].dropna().unique().tolist()),
        df_uso, cfg, tarifas, False, {}, orca_config.modo_somente_hh, atvs,
    )
    demanda_plana = {
        (th, t["atividade"]): t["hh_total"]
        for th, tl in demandas["demandas"].items()
        for t in tl
    }

    linhas = comparativo_real.simular_cenarios_reais(
        demanda_plana,
        executores_base=int(args.get("executores_base", 9)),
        jornada_base=float(args.get("jornada_base", 6.5)),
        jornadas=[float(x) for x in jornadas],
        equipes=[int(x) for x in equipes],
    )
    melhor = min(linhas, key=lambda x: x["dias_simulados"]) if linhas else None
    return {
        "fazenda": fazenda or "(todas)",
        "hh_total": round(demandas["total_hh"], 1),
        "cenarios": linhas,
        "melhor": melhor,
        "nota": "dias calculados pelo scheduler real (cascata, bloqueio, pool, reforço, HM)",
    }


def tool_metricas(args: Dict[str, Any]) -> Dict[str, Any]:
    c = _SESSAO.get("ultimo_cenario")
    if c is None:
        raise RuntimeError("nenhum cenário calculado — chame orca_simular_cenario antes")
    return c


def _config_cenario_mcp(demanda, turmas, jornada):
    from atm.orca.comparativo_real import _config_cenario

    return _config_cenario(demanda, turmas, jornada, seq_cfg=_default_sequencia_dict())


FERRAMENTAS = {
    "orca_carregar_micro": {
        "descricao": "Carrega uma planilha de microplanejamento (.xlsx/.xlsm/.csv) e a valida. "
        "Colunas obrigatórias: fazenda, chave, area, atividade.",
        "schema": {
            "type": "object",
            "properties": {
                "caminho": {"type": "string", "description": "caminho absoluto da planilha"},
                "modo_auto": {"type": "boolean", "description": "true = falha explícita se coluna obrigatória ausente", "default": True},
            },
            "required": ["caminho"],
        },
        "fn": tool_carregar_micro,
    },
    "orca_listar_fazendas": {
        "descricao": "Lista fazendas do micro carregado com talhões, atividades e área total.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_listar_fazendas,
    },
    "orca_carregar_tarifas": {
        "descricao": "Carrega tarifas CT313/CT317. Sem argumentos usa o fallback CT317 do motor. "
        "Com caminho_ct normaliza a planilha.",
        "schema": {
            "type": "object",
            "properties": {
                "caminho_ct": {"type": "string", "description": "caminho da CT bruta (.xlsm/.xlsx)"},
            },
        },
        "fn": tool_carregar_tarifas,
    },
    "orca_validar_pipeline": {
        "descricao": "Roda o gate de validação cruzada micro → de_para → tarifas. "
        "Devolve cobertura e atividades sem tarifa.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_validar_pipeline,
    },
    "orca_simular_cenario": {
        "descricao": "Roda um cenário pelo SCHEDULER REAL (cascata por talhão, bloqueio global, "
        "pool pós-bloqueio, reforço, HM-paralelo). Não é aproximação.",
        "schema": {
            "type": "object",
            "properties": {
                "executores": {"type": "integer", "default": 9},
                "jornada": {"type": "number", "default": 6.5},
                "fazenda": {"type": "string", "description": "opcional; sem ele usa todas"},
                "penalidade": {"type": "number", "default": 1.0, "description": "fator de declividade 1.0/1.15/1.30"},
            },
        },
        "fn": tool_simular_cenario,
    },
    "orca_comparar_cenarios": {
        "descricao": "Grade multi-fator (jornada × equipe) rodada pelo scheduler real. "
        "Devolve todos os cenários e o melhor.",
        "schema": {
            "type": "object",
            "properties": {
                "jornadas": {"type": "array", "items": {"type": "number"}, "default": [4.3, 6.5, 8.8]},
                "equipes": {"type": "array", "items": {"type": "integer"}, "default": [6, 9, 12]},
                "fazenda": {"type": "string"},
            },
        },
        "fn": tool_comparar_cenarios,
    },
    "orca_metricas": {
        "descricao": "Métricas do último cenário calculado.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_metricas,
    },
}


# ──────────────────────────────────────────────
# RECURSOS
# ────────────────────────────���──────────────────

def recurso_baseline() -> Dict[str, Any]:
    import subprocess

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_RAIZ_REPO, capture_output=True, text=True
    ).stdout.strip()
    return {
        "repo": _RAIZ_REPO,
        "head": head,
        "modulos_orca": sorted(
            f for f in os.listdir(os.path.join(_RAIZ_REPO, "src", "atm", "orca"))
            if f.endswith(".py")
        ),
        "tarifas_ct317": len(CT317_HARDCODE_HH_BASE),
        "de_para_padrao": len(DEFAULT_DEPARA_EXAME_CT317),
        "testes_oficiais": 49,
        "nota": "baseline verificado por hash em ORCA_BASELINE.md",
    }


def recurso_schemas() -> Dict[str, Any]:
    return {
        "MicroRow": MicroSchema(),
        "TarifaCT": TarifaSchema(),
        "PipelineConfig": {
            "micro": "lista de MicroRow",
            "tarifas": "TarifasDict",
            "de_para": "DeParaMap",
            "cobertura": "atividades_sem_tarifa deve ser 0",
        },
        "regra_hh_hm": "rendimento_hh > 0 implica rendimento_hm = 0",
    }


def MicroSchema():
    from atm.orca.schemas import MicroRow

    return MicroRow.model_json_schema()


def TarifaSchema():
    from atm.orca.schemas import TarifaCT

    return TarifaCT.model_json_schema()


RECURSOS = {
    "orca://baseline": {
        "nome": "Baseline de integridade",
        "descricao": "HEAD do git, módulos do pacote e fontes de dados",
        "fn": recurso_baseline,
    },
    "orca://schemas": {
        "nome": "Contratos de dados",
        "descricao": "JSON Schema dos modelos Pydantic do Orca",
        "fn": recurso_schemas,
    },
}


# ──────────────────────────────────────────────
# SERVIDOR JSON-RPC 2.0 (stdio)
# ────────────────────────────���──────────────────

def _tools_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": nome,
            "description": spec["descricao"],
            "inputSchema": spec["schema"],
        }
        for nome, spec in FERRAMENTAS.items()
    ]


def _tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    nome = params.get("name")
    args = params.get("arguments") or {}
    if nome not in FERRAMENTAS:
        raise ValueError(f"ferramenta desconhecida: {nome}")
    return FERRAMENTAS[nome]["fn"](args)


def _resources_list() -> List[Dict[str, Any]]:
    return [
        {"uri": uri, "name": spec["nome"], "description": spec["descricao"], "mimeType": "application/json"}
        for uri, spec in RECURSOS.items()
    ]


def _resources_read(params: Dict[str, Any]) -> Dict[str, Any]:
    uri = params.get("uri")
    if uri not in RECURSOS:
        raise ValueError(f"recurso desconhecido: {uri}")
    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(RECURSOS[uri]["fn"](), ensure_ascii=False, indent=2)}]}


def _despachar(requisicao: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metodo = requisicao.get("method")
    id_req = requisicao.get("id")
    params = requisicao.get("params") or {}

    if metodo == "initialize":
        return _ok(
            id_req,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "orca-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}, "resources": {}},
            },
        )
    if metodo == "notifications/initialized":
        return None
    if metodo == "tools/list":
        return _ok(id_req, {"tools": _tools_list()})
    if metodo == "tools/call":
        return _ok(id_req, _texto(_tools_call(params)))
    if metodo == "resources/list":
        return _ok(id_req, {"resources": _resources_list()})
    if metodo == "resources/read":
        return _ok(id_req, _resources_read(params))
    if metodo == "prompts/list":
        return _ok(id_req, {"prompts": []})
    if metodo == "ping":
        return _ok(id_req, {})
    return _erro(id_req, -32601, f"método não suportado: {metodo}")


def servir() -> None:
    """Loop stdio: uma requisição JSON-RPC por linha."""
    sys.stderr.write("orca-mcp: servidor ativo (stdio)\n")
    sys.stderr.flush()
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            requisicao = json.loads(linha)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_erro(None, -32700, f"JSON inválido: {exc}")) + "\n")
            sys.stdout.flush()
            continue

        try:
            resposta = _despachar(requisicao)
        except Exception as exc:
            rastreio = traceback.format_exc()
            sys.stderr.write(rastreio)
            resposta = _erro(requisicao.get("id"), -32603, f"{type(exc).__name__}: {exc}")

        if resposta is None:
            continue
        sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    servir()
