"""
Orca configuration — loading, saving, sequence defaults, territory config.

Depends on: orca.text_utils (normalizar_chave)
External: os, json
"""

import json
import os
import shutil
import tempfile

from .text_utils import normalizar_chave

# ──────────────────────────────────────────────
# PATH CONSTANTS
# ──────────────────────────────────────────────

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFGP = os.path.join(DIR, "config.json")
DOSSIER_DIRNAME = "dossiês"
ROOT_DIR = os.path.dirname(os.path.dirname(DIR))
DATA_DIR = os.path.join(ROOT_DIR, "data")
INPUT_DIR = os.path.join(DATA_DIR, "planilhas")
OUTPUT_DIR = os.path.join(DATA_DIR, DOSSIER_DIRNAME)
PERFIS_DIR = os.path.join(DATA_DIR, "perfis_equipe")

PRECO_FINAL_JSON_DEFAULT = "preco_final.json"
PRECO_FINAL_JSON_DOWNLOADS = os.path.join(
    os.path.expanduser("~"), "Downloads", PRECO_FINAL_JSON_DEFAULT
)
_PRECO_FINAL_JSON_CACHE = {"path": "", "mtime": None, "mapa": {}}

# ATM 6.1: foco operacional (atividades + HH). Valores em R$ ficam desativados temporariamente.
# Tornou-se toggle via config.json (chave "modo_somente_hh"). Constante e' o fallback.
MODO_SOMENTE_HH = True


def modo_somente_hh(cfg=None):
    """Retorna True se o modo somente HH esta ativo. Le de cfg se disponivel, senao usa a constante."""
    if cfg is not None:
        return cfg.get("modo_somente_hh", MODO_SOMENTE_HH)
    return MODO_SOMENTE_HH
CT_REAL_FILENAME = "ct317real.xlsx"
STG_FILENAME = "CT_317_NORMALIZADA.xlsx"

# Known column mapping (fallback semantico so se nenhuma bater)
KNOWN_COLUMNS = {
    "fazenda": ["NOME FAZENDA", "CODIGO FAZENDA"],
    "chave": ["CHAVE POLIGONO", "CHAVE POLIGONO"],
    "area": [
        "AREA TRABALHADA ESTIMADA (HECTARE)",
        "AREA POLIGONO (HECTARE)",
        "AREA POLIGONO (HECTARE)",
        "AREA TRABALHADA ESTIMADA (HECTARE)",
    ],
    "atividade": ["ATIVIDADES", "ATIVIDADE"],
    "municipio": ["MUNICIPIO", "CIDADE"],
    "estado": ["ESTADO", "UF"],
}


# ──────────────────────────────────────────────
# MODE DETECTION
# ──────────────────────────────────────────────


def _is_legacy_mode():
    import sys as _sys

    v = os.environ.get("ATM_LEGACY", "").strip().lower()
    if v in ("1", "true", "yes", "sim", "on"):
        return True
    return "--legacy" in _sys.argv


def _is_beta_mode():

    # Fluxo beta promovido a padrao; legado fica opt-in por flag/env.
    if _is_legacy_mode():
        return False
    v = os.environ.get("ATM_BETA", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


# ──────────────────────────────────────────────
# SEQUENCE DEFAULTS
# ──────────────────────────────────────────────


def _default_sequencia_dict():
    return {
        "modo": "implantacao",
        "offset_limpeza_quimica_dias": 30,
        "filtros_plantio": ["plantio"],
        "filtros_irrigacao": ["irrig"],
        "limpeza_quimica_filtros": ["limpeza", "quim"],
        "limpeza_quimica_exclusoes": ["impl", "impl."],
        "implantacao_outras_fase": 5.5,
        "implantacao_fases": [
            {"id": "rocada", "filtros": ["rocada", "rocada"], "exclusoes": []},
            {
                "id": "formiga",
                "filtros": ["formiga", "combate a formiga", "combate a formigas"],
                "exclusoes": [],
            },
            {"id": "coroamento", "filtros": ["coroamento", "coroa"], "exclusoes": []},
            {"id": "coveamento", "filtros": ["coveamento", "coveam"], "exclusoes": []},
            {
                "id": "adubacao_quimica",
                "filtros": ["adubacao quim", "adubacao quim", "melhora quim"],
                "exclusoes": [],
            },
        ],
        "personalizado_ordem": [],
    }


def _preset_implantacao_padrao():
    """Preset de implantação padrão (a cascata atual)."""
    d = _default_sequencia_dict()
    d["modo"] = "implantacao"
    return d


def _preset_manutencao_seco_sugerido():
    """Preset sugerido para manutenção período seco (sem cascata de implantação).
    
    Fases típicas: roçada de manutenção, controle de formigas, adubação de cobertura.
    Sem plantio/irrigacao/coroamento/coveamento/adubação química de implantação.
    O dono pode ajustar via modo personalizado depois.
    """
    return {
        "modo": "manutencao_seco",
        "offset_limpeza_quimica_dias": 30,
        "filtros_plantio": [],
        "filtros_irrigacao": [],
        "limpeza_quimica_filtros": ["limpeza", "quim"],
        "limpeza_quimica_exclusoes": [],
        "implantacao_outras_fase": 5.5,
        "implantacao_fases": [
            {"id": "rocada_manutencao", "filtros": ["rocada", "roçada", "roca"], "exclusoes": ["impl", "plantio"]},
            {"id": "formiga_manutencao", "filtros": ["formiga", "combate a formiga", "combate a formigas"], "exclusoes": []},
            {"id": "adubacao_cobertura", "filtros": ["adubacao cobertura", "adubacao de cobertura", "cobertura"], "exclusoes": []},
        ],
        "personalizado_ordem": [],
    }


def _preset_manutencao_umido_sugerido():
    """Preset sugerido para manutenção período úmido (sem cascata de implantação).
    
    Fases típicas: roçada de manutenção, controle de formigas, adubação de cobertura,
    controle de invasoras, aceiro. Sem plantio/irrigacao/coroamento/coveamento.
    O dono pode ajustar via modo personalizado depois.
    """
    return {
        "modo": "manutencao_umido",
        "offset_limpeza_quimica_dias": 30,
        "filtros_plantio": [],
        "filtros_irrigacao": [],
        "limpeza_quimica_filtros": ["limpeza", "quim"],
        "limpeza_quimica_exclusoes": [],
        "implantacao_outras_fase": 5.5,
        "implantacao_fases": [
            {"id": "rocada_manutencao", "filtros": ["rocada", "roçada", "roca"], "exclusoes": ["impl", "plantio"]},
            {"id": "formiga_manutencao", "filtros": ["formiga", "combate a formiga", "combate a formigas"], "exclusoes": []},
            {"id": "adubacao_cobertura", "filtros": ["adubacao cobertura", "adubacao de cobertura", "cobertura"], "exclusoes": []},
            {"id": "invasoras_aceiro", "filtros": ["invasora", "aceiro", "aceiro", "limpeza area"], "exclusoes": []},
        ],
        "personalizado_ordem": [],
    }


def _merge_sequencia_defaults(seq):
    """Preenche chaves ausentes em cfg['sequencia'] (muta seq)."""
    d0 = _default_sequencia_dict()
    for k, v in d0.items():
        if k not in seq:
            seq[k] = v
        elif k in ("implantacao_fases", "personalizado_ordem") and not seq[k]:
            seq[k] = v


def _aplicar_preset_sequencia(seq_cfg: dict, modo: str) -> dict:
    """Aplica preset de sequência conforme o modo.
    
    Se o modo não tem preset válido, levanta ValueError com mensagem clara.
    """
    presets = {
        "implantacao": _preset_implantacao_padrao,
        "manutencao_seco": _preset_manutencao_seco_sugerido,
        "manutencao_umido": _preset_manutencao_umido_sugerido,
    }
    if modo in presets:
        preset = presets[modo]()
        seq_cfg.update(preset)
        return seq_cfg
    if modo == "personalizado":
        return seq_cfg
    raise ValueError(
        f"Modo '{modo}' não tem configuração de sequência válida. "
        f"Configure a sequência do modo '{modo}' via personalizado ou use um modo com preset."
    )


_SEQUENCIAS_DISPONIVEIS = [
    (
        "implantacao",
        "Rocada > Formiga > Coroamento > Coveamento > Adubacao > Plantio > Irrigacao (cascata)",
    ),
    (
        "manutencao_seco",
        "Manutencao periodo seco — roçada, formiga, adubação cobertura (preset sugerido)",
    ),
    (
        "manutencao_umido",
        "Manutencao periodo umido — roçada, formiga, adubação cobertura, invasoras/aceiro (preset sugerido)",
    ),
    ("personalizado", "Sequencia personalizada (defina grupos sequenciais/paralelos)"),
]


# ──────────────────────────────────────────────
# EMPRESA CONFIG (from xlsx / config.json)
# ──────────────────────────────────────────────


def _detectar_cidade_por_fazenda(nome_fazenda: str) -> str:
    """
    Detecta a cidade/territorio baseado no nome da fazenda.
    Retorna o codigo da cidade ou None se nao detectar.
    Usado apenas como metadado de exibicao — nao determina a atribuicao de equipes.
    """
    nome_norm = normalizar_chave(str(nome_fazenda))
    cidade_keywords = {
        "acailandia": ["acailandia", "acailand", "ailandia"],
        "dom_eliseu": ["dom eliseu", "eliseu", "dom_eliseu"],
        "cidelandia": ["cidelandia", "cideland", "cidelndia", "buritirana"],
    }
    for cidade, keywords in cidade_keywords.items():
        for kw in keywords:
            if kw in nome_norm:
                return cidade
    return None


def _distribuir_fazendas_por_territorio(fazendas: list) -> dict:
    """
    Distribui fazendas por territorio/cidade automaticamente.
    Retorna: (distribuicao_dict, nao_identificadas_list)
    """
    distribuicao = {"acailandia": [], "dom_eliseu": [], "cidelandia": []}
    nao_identificadas = []

    for faz in fazendas:
        cidade = _detectar_cidade_por_fazenda(faz)
        if cidade:
            distribuicao[cidade].append(faz)
        else:
            nao_identificadas.append(faz)

    return distribuicao, nao_identificadas


def _agrupar_fazendas_por_empresa(df_scope) -> dict:
    """
    Agrupa fazendas pelo valor da coluna 'equipe' no DataFrame.
    Retorna: {nome_empresa: [fazenda1, fazenda2, ...], ...}
    """
    if df_scope is None or "equipe" not in df_scope.columns:
        return {}
    grupos = {}
    for _, row in df_scope.iterrows():
        eq = str(row.get("equipe", "")).strip()
        faz = str(row.get("fazenda", "")).strip()
        if not eq or eq in ("nan", "None", "") or not faz:
            continue
    if eq not in grupos:
        grupos[eq] = []
    if faz not in grupos[eq]:
        grupos[eq].append(faz)
    return {k: sorted(v) for k, v in grupos.items()}


def _calcular_config_empresa(nome_empresa: str, cfg: dict) -> dict:
    """
    Calcula configuracao de equipes para uma empresa.
    Le de cfg["empresas"][nome_empresa] — se nao existir, usa defaults.
    """
    empresas_cfg = cfg.get("empresas") or {}
    info = empresas_cfg.get(nome_empresa, {})

    operarios_por_eq = info.get("operarios_por_equipe", 10)
    coordenadores_por_eq = info.get("coordenadores_por_equipe", 1)
    n_equipes = info.get("n_equipes", 1)
    jornada = info.get("jornada", 4.3)
    total_por_eq = operarios_por_eq + coordenadores_por_eq

    return {
        "empresa": nome_empresa,
        "nome_empresa": nome_empresa,
        "n_equipes": n_equipes,
        "operarios_por_equipe": operarios_por_eq,
        "coordenadores_por_equipe": coordenadores_por_eq,
        "total_por_equipe": total_por_eq,
        "total_operarios": n_equipes * operarios_por_eq,
        "total_coordenadores": n_equipes * coordenadores_por_eq,
        "total_geral": n_equipes * total_por_eq,
        "jornada": jornada,
    }


def _sugerir_config_empresa(fazendas_por_empresa: dict, cfg: dict) -> dict:
    """
    Sugere configuracao completa de equipes baseada na distribuicao por empresa.
    """
    sugestoes = []
    for nome_emp, fazs in fazendas_por_empresa.items():
        config = _calcular_config_empresa(nome_emp, cfg)
        config["fazendas"] = fazs
        config["n_fazendas"] = len(fazs)
        sugestoes.append(config)

    return {
        "sugestoes": sugestoes,
        "total_equipes": sum(s["n_equipes"] for s in sugestoes),
        "total_operarios": sum(s["total_operarios"] for s in sugestoes),
        "total_coordenadores": sum(s["total_coordenadores"] for s in sugestoes),
    }


# ──────────────────────────────────────────────
# CONFIG PERSISTENCE
# ──────────────────────────────────────────────


def _load_json_safe(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def carregar_config():
    """Load (or create) config.json, apply defaults, apply preco_final overrides if available."""
    if not os.path.exists(CFGP):
        with open(CFGP, "w", encoding="utf-8") as f:
            json.dump({"de_para": {}, "tarifas": {}, "atividades": {}}, f)
    try:
        cfg = _load_json_safe(CFGP)
    except json.JSONDecodeError:
        bak = CFGP + ".bak"
        if os.path.exists(bak):
            try:
                cfg = _load_json_safe(bak)
                shutil.copy2(bak, CFGP)
            except json.JSONDecodeError:
                cfg = {}
        else:
            cfg = {}
    for k in ("de_para", "tarifas", "atividades"):
        if k not in cfg:
            cfg[k] = {}
    if "orcamento_estrito" not in cfg:
        cfg["orcamento_estrito"] = True
    if "filtros_bloqueio_global" not in cfg:
        cfg["filtros_bloqueio_global"] = ["plantio", "irrig"]
    if "fazendas_ct" not in cfg:
        cfg["fazendas_ct"] = []
    if "sequencia" not in cfg or not isinstance(cfg.get("sequencia"), dict):
        cfg["sequencia"] = {}
    _merge_sequencia_defaults(cfg["sequencia"])
    if "preco_final_json_path" not in cfg:
        cfg["preco_final_json_path"] = ""
    if "comparativo" not in cfg or not isinstance(cfg.get("comparativo"), dict):
        cfg["comparativo"] = {}
    if "execucao_compacta" not in cfg["comparativo"]:
        cfg["comparativo"]["execucao_compacta"] = True
    if "empresas" not in cfg:
        cfg["empresas"] = {}
    if "modo_somente_hh" not in cfg:
        cfg["modo_somente_hh"] = MODO_SOMENTE_HH
    # NOTE: preco_final JSON loading depends on tarifas sub-system;
    # the caller (original monolith) handles this inline.
    # When full modularization is complete, this will be a hook.
    return cfg


def _normalize_for_json(obj):
    if isinstance(obj, set):
        return sorted(obj, key=str)
    if isinstance(obj, dict):
        return {k: _normalize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_for_json(i) for i in obj]
    return obj


def salvar_config(cfg):
    """Persist cfg to config.json. Creates .bak backup before overwriting. Uses atomic write."""
    cfg = _normalize_for_json(cfg)
    if os.path.exists(CFGP):
        try:
            shutil.copy2(CFGP, CFGP + ".bak")
        except OSError:
            pass
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(CFGP), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CFGP)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
