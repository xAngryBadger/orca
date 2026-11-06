"""Tarifas — resolucao de rendimento, CT317 normalizer, de-para CRUD, precos."""

import datetime
import json
import os
from statistics import median

import pandas as pd

from .io import ExcelReader
from .config import (
    _PRECO_FINAL_JSON_CACHE,
    INPUT_DIR,
    PRECO_FINAL_JSON_DEFAULT,
    PRECO_FINAL_JSON_DOWNLOADS,
    STG_FILENAME,
    salvar_config,
)
from .constants import CT317_HARDCODE_HH_BASE
from .context import dashboard_header
from .text_utils import normalizar_chave, remover_acentos
from .ui import (
    BL,
    DM,
    RS,
    C,
    G,
    Y,
    aviso,
    confirmar,
    erro,
    esperar,
    ok,
    prompt,
    selecionar,
    selecionar_paginado,
    sub,
    subcabecalho,
)


def mediana_rendimento_hh(tarifas):
    """Mediana dos rendimento_hh > 0 em config.tarifas, ou None."""
    vals = []
    for v in (tarifas or {}).values():
        if not isinstance(v, dict):
            continue
        try:
            x = float(v.get("rendimento_hh", 0))
            if x > 0:
                vals.append(x)
        except (TypeError, ValueError):
            pass
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0
def resolver_rendimento_hh(
    cfg, tarifas, t_nome, strict=False, session_hh=None, atv_micro=None
):
    """
    HH/ha para a chave t_nome em tarifas.
    session_hh: dict opcional {nome_micro ou chave_tarifa: hh_ha} valido so na execucao atual (nao grava config).
    Modo strict: sem mediana/8 silenciosos — retorna None se invalido.
    Excecao: atividades mecanizadas (tipo Mecanizada ou HM>0) retornam 0.0 em strict.
    """
    if session_hh:
        try:
            if atv_micro and atv_micro in session_hh:
                return float(session_hh[atv_micro])
            if t_nome and t_nome in session_hh:
                return float(session_hh[t_nome])
        except (TypeError, ValueError):
            pass
    if t_nome in (tarifas or {}):
        row = tarifas[t_nome]
        r = row.get("rendimento_hh")
        try:
            rf = float(r)
            if rf >= 0:
                if strict and rf <= 0:
                    tipo = str(row.get("tipo", "")).lower()
                    hm = float(row.get("rendimento_hm", 0) or 0)
                    if "mecaniz" in tipo or hm > 0:
                        return 0.0
                    return None
                return rf
        except (TypeError, ValueError):
            if strict:
                return None
    if strict:
        return None
    ex = cfg.get("rendimento_hh_fallback")
    if ex is not None:
        try:
            e = float(ex)
            if e > 0:
                return e
        except (TypeError, ValueError):
            pass
    med = mediana_rendimento_hh(tarifas)
    if med is not None and med > 0:
        return med
    return 8.0

def resolver_rendimento_hm(cfg, tarifas, t_nome, strict=False):
    """
    HM/ha para a chave t_nome em tarifas.
    Em strict: ausencia/invalido retorna 0.0 (HM nao bloqueia fluxo humano).
    """
    if t_nome in (tarifas or {}):
        row = tarifas[t_nome]
        r = row.get("rendimento_hm", 0)
        try:
            rf = float(r)
            if rf >= 0:
                return rf
        except (TypeError, ValueError):
            pass
    if strict:
        return 0.0
    ex = cfg.get("rendimento_hm_fallback")
    if ex is not None:
        try:
            e = float(ex)
            if e > 0:
                return e
        except (TypeError, ValueError):
            pass
    return 0.0

def _mediana_campo(tarifas, campo):
    vals = []
    for v in (tarifas or {}).values():
        if not isinstance(v, dict):
            continue
        try:
            x = float(v.get(campo, 0))
            if x > 0:
                vals.append(x)
        except (TypeError, ValueError):
            pass
    return median(vals) if vals else None


def resolver_preco_ha(cfg, tarifas, t_nome, strict=False):
    # modo_somente_hh só afeta UI, não cálculo de preço — financeiro flui quando cfg["modo_somente_hh"]=False
    if t_nome in (tarifas or {}):
        p = tarifas[t_nome].get("preco_ha") or tarifas[t_nome].get("preco_unit")
        try:
            pf = float(p)
            if pf > 0:
                return pf
        except (TypeError, ValueError):
            pass
    if strict:
        return None
    fb = cfg.get("preco_ha_fallback")
    if fb:
        try:
            f = float(fb)
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    med = _mediana_campo(tarifas, "preco_ha") or _mediana_campo(tarifas, "preco_unit")
    return med if med and med > 0 else 0.0


def resolver_custo_hora(cfg, tarifas, t_nome, strict=False):
    # modo_somente_hh só afeta UI, não cálculo de custo — financeiro flui quando cfg["modo_somente_hh"]=False
    if t_nome in (tarifas or {}):
        c = tarifas[t_nome].get("custo_hora")
        try:
            cf = float(c)
            if cf > 0:
                return cf
        except (TypeError, ValueError):
            pass
    if strict:
        return None
    fb = cfg.get("custo_hora_tf")
    if fb:
        try:
            f = float(fb)
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    med = _mediana_campo(tarifas, "custo_hora")
    return med if med and med > 0 else 0.0


def _to_float_json(v, default=0.0):
    if v is None:
        return float(default)
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)
    s = str(v).strip()
    if not s:
        return float(default)
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (TypeError, ValueError):
        return float(default)

def _candidatos_preco_final_json(cfg=None):
    out = []
    if isinstance(cfg, dict):
        p_cfg = str(cfg.get("preco_final_json_path", "") or "").strip()
        if p_cfg:
            p_cfg = os.path.expanduser(p_cfg)
            if not os.path.isabs(p_cfg):
                p_cfg = os.path.join(INPUT_DIR, p_cfg)
            out.append(p_cfg)
        out.append(os.path.join(INPUT_DIR, PRECO_FINAL_JSON_DEFAULT))
    out.append(PRECO_FINAL_JSON_DOWNLOADS)
    uniq = []
    seen = set()
    for p in out:
        ap = os.path.abspath(os.path.expanduser(str(p)))
        if ap in seen:
            continue
        seen.add(ap)
        uniq.append(ap)
    return uniq

def _score_payload_preco(payload):
    hh = float(payload.get("rendimento_hh", 0) or 0)
    hm = float(payload.get("rendimento_hm", 0) or 0)
    pr = float(payload.get("preco_ha", 0) or payload.get("preco_unit", 0) or 0)
    return (1 if hh > 0 else 0, hh, 1 if pr > 0 else 0, pr, hm)

_PRECO_FINAL_JSON_TTL_PADRAO = 3600.0


def invalidate_preco_final_cache():
    global _PRECO_FINAL_JSON_CACHE
    _PRECO_FINAL_JSON_CACHE = {"path": "", "mtime": None, "mapa": {}}


def _preco_final_json_ttl(cfg=None):
    ttl = _PRECO_FINAL_JSON_TTL_PADRAO
    if isinstance(cfg, dict):
        bruto = cfg.get("preco_final_json_ttl", ttl)
        try:
            convertido = float(bruto)
        except (TypeError, ValueError):
            return _PRECO_FINAL_JSON_TTL_PADRAO
        if convertido > 0:
            return convertido
        return 0.0
    return _PRECO_FINAL_JSON_TTL_PADRAO


def _carregar_mapa_preco_final_json(cfg=None):
    global _PRECO_FINAL_JSON_CACHE

    caminho = ""
    for c in _candidatos_preco_final_json(cfg):
        if os.path.isfile(c):
            caminho = c
            break
    if not caminho:
        invalidate_preco_final_cache()
        return {}

    try:
        mtime = os.path.getmtime(caminho)
    except OSError:
        return {}

    ttl = _preco_final_json_ttl(cfg)
    agora = datetime.datetime.now().timestamp()

    cache = _PRECO_FINAL_JSON_CACHE or {}
    expira_em = cache.get("expira_em", 0.0)
    if (
        cache.get("path") == caminho
        and cache.get("mtime") == mtime
        and isinstance(cache.get("mapa"), dict)
        and (ttl <= 0 or agora < float(expira_em))
    ):
        return dict(cache.get("mapa") or {})

    try:
        with open(caminho, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    rows = []
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        for k in ("data", "rows", "tarifas", "atividades", "preco_final"):
            if isinstance(raw.get(k), list):
                rows = raw.get(k)
                break
        if not rows:
            # Aceita formato dict "nome" -> payload.
            if raw and all(isinstance(v, dict) for v in raw.values()):
                rows = []
                for k, v in raw.items():
                    item = dict(v)
                    item.setdefault("operacao", k)
                    rows.append(item)

    mapa = {}
    idx_norm = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        nome = str(
            item.get("operacao")
            or item.get("atividade")
            or item.get("nome")
            or item.get("descricao")
            or ""
        ).strip()
        if not nome:
            continue

        hh = _to_float_json(item.get("rendimento_hh_ha", item.get("rendimento_hh")), 0.0)
        hm = _to_float_json(
            item.get("rendimento_maquina_ha", item.get("rendimento_hm")), 0.0
        )
        preco = _to_float_json(
            item.get(
                "preco_rs",
                item.get("preco_ha", item.get("preco_unit", item.get("preco"))),
            ),
            0.0,
        )
        if hh > 0:
            hm = 0.0
        tipo = str(item.get("tipo") or "").strip()
        if not tipo:
            tipo = "Mecanizada" if hm > 0 and hh <= 0 else "Manual"

        payload = {
            "rendimento_hh": float(hh or 0.0),
            "rendimento_hm": float(hm or 0.0),
            "preco_ha": float(preco or 0.0),
            "preco_unit": float(preco or 0.0),
            "tipo": tipo,
        }
        if (
            payload["rendimento_hh"] <= 0
            and payload["rendimento_hm"] <= 0
            and payload["preco_ha"] <= 0
        ):
            continue

        nk = normalizar_chave(nome)
        if not nk:
            continue
        prev_nome = idx_norm.get(nk)
        if prev_nome is None:
            mapa[nome] = payload
            idx_norm[nk] = nome
        else:
            prev_payload = mapa.get(prev_nome, {})
            if _score_payload_preco(payload) >= _score_payload_preco(prev_payload):
                if prev_nome != nome:
                    mapa.pop(prev_nome, None)
                mapa[nome] = payload
                idx_norm[nk] = nome

    _PRECO_FINAL_JSON_CACHE = {
        "path": caminho,
        "mtime": mtime,
        "mapa": mapa,
        "expira_em": agora + ttl,
    }
    return dict(mapa)


def _aplicar_mapa_preco_final_em_rows_by_name(rows_by_name, mapa_json, fonte_tag):
    if not isinstance(rows_by_name, dict) or not mapa_json:
        return 0
    alterados = 0
    idx_norm = {
        normalizar_chave(k): k
        for k in rows_by_name.keys()
        if isinstance(k, str) and normalizar_chave(k)
    }

    for nome, base in mapa_json.items():
        hh = float(base.get("rendimento_hh", 0) or 0)
        hm = float(base.get("rendimento_hm", 0) or 0)
        preco = float(base.get("preco_ha", 0) or base.get("preco_unit", 0) or 0)
        tipo = str(base.get("tipo") or "").strip()
        if hh > 0:
            hm = 0.0
        if not tipo:
            tipo = "Mecanizada" if hm > 0 and hh <= 0 else "Manual"

        nk = normalizar_chave(nome)
        key = nome if nome in rows_by_name else idx_norm.get(nk)
        if key is None:
            rows_by_name[nome] = {
                "atividade": nome,
                "tipo": tipo,
                "rendimento_hh": hh,
                "rendimento_hm": hm,
                "preco_ha": preco,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "fonte_aba": fonte_tag,
            }
            if nk:
                idx_norm[nk] = nome
            alterados += 1
            continue

        row = rows_by_name.get(key)
        if not isinstance(row, dict):
            row = {}
            rows_by_name[key] = row

        mudou = False
        if str(row.get("atividade") or "").strip() != key:
            row["atividade"] = key
            mudou = True

        if hh > 0:
            if float(row.get("rendimento_hh", 0) or 0) != hh:
                row["rendimento_hh"] = hh
                mudou = True
            if float(row.get("rendimento_hm", 0) or 0) != 0.0:
                row["rendimento_hm"] = 0.0
                mudou = True
            if str(row.get("tipo") or "").strip() != (tipo or "Manual"):
                row["tipo"] = tipo or "Manual"
                mudou = True
        elif hm > 0 and float(row.get("rendimento_hh", 0) or 0) <= 0:
            if float(row.get("rendimento_hm", 0) or 0) != hm:
                row["rendimento_hm"] = hm
                mudou = True
            if tipo and str(row.get("tipo") or "").strip() != tipo:
                row["tipo"] = tipo
                mudou = True

        if preco > 0 and float(row.get("preco_ha", 0) or 0) != preco:
            row["preco_ha"] = preco
            mudou = True

        if float(row.get("rendimento_hh", 0) or 0) > 0 and float(
            row.get("rendimento_hm", 0) or 0
        ) > 0:
            row["rendimento_hm"] = 0.0
            mudou = True

        if mudou:
            row["fonte_aba"] = fonte_tag
            alterados += 1
    return alterados

def _find_preco_final_sheet(xls):
    for s in xls.sheet_names:
        ns = remover_acentos(s).replace(" ", "").replace("_", "").replace("-", "")
        if "precofinal" in ns:
            return s
    return None

def _ler_ct_preco_final(caminho_ct, pf):
    """Le a sheet de preco final achando o cabecalho REAL (2 linhas).

    Layouts vistos: cabecalho na linha 0 (planilha antiga), ou 3+ linhas de
    titulo + linha com 'N | OPERACOES | ... | PREÇO R$ | Custo Hora' + sub-linha
    'hh/ha, hm/ha' (CT317 real). Mergeia a sub-linha no nome da coluna para o
    parser por tokens achar Rendimento hh/ha vs hm/ha. Sem cabecalho detectado,
    devolve header=0 (o parser legado por indice assume).
    """
    try:
        df0 = ExcelReader.read(caminho_ct, sheet_name=pf, header=None, nrows=15)
    except Exception:
        return ExcelReader.read(caminho_ct, sheet_name=pf, header=0)

    hdr = None
    for i in range(len(df0)):
        row_txt = " ".join(remover_acentos(str(x)).lower() for x in df0.iloc[i].tolist())
        if "operac" in row_txt and ("preco" in row_txt or "valor" in row_txt):
            hdr = i
            break
    if hdr is None:
        return ExcelReader.read(caminho_ct, sheet_name=pf, header=0)

    sub = None
    if hdr + 1 < len(df0):
        sub = [str(x).strip() if pd.notna(x) else "" for x in df0.iloc[hdr + 1].tolist()]
    hdr_cells = [str(x).strip() if pd.notna(x) else "" for x in df0.iloc[hdr].tolist()]

    names = []
    for idx, base in enumerate(hdr_cells):
        sub_txt = sub[idx] if (sub and idx < len(sub)) else ""
        if base:
            nome = f"{base} {sub_txt}".strip() if sub_txt else base
        else:
            nome = sub_txt if sub_txt else f"col_{idx}"
        names.append(nome)

    dfh = ExcelReader.read(caminho_ct, sheet_name=pf, header=None)
    dfh.columns = names[: len(dfh.columns)] + [
        f"col_{i}" for i in range(len(names), len(dfh.columns))
    ]
    return dfh.iloc[hdr + 2 :].reset_index(drop=True)


def normalizar_ct313(caminho_ct):
    """
    Le CT_313 bruta e gera CT_313_NORMALIZADA.xlsx com aba STG_TARIFAS.
    Retorna (caminho_stg, n_linhas, custo_hora_tf).
    """
    xls = pd.ExcelFile(caminho_ct)
    pf = _find_preco_final_sheet(xls)
    if not pf:
        return None, 0, 0.0

    # Layout antigo (indices fixos) e layout CT317 real (2 linhas de cabecalho:
    # linha com N/OPERACOES/PREÇO + sub-linha hh/ha,hm/ha) coexistem. Aqui
    # detectamos o cabecalho real e mergeamos a sub-linha; se falhar, caimos
    # para o parser legado por indice.
    dfh = _ler_ct_preco_final(caminho_ct, pf)

    custo_hora_tf = 0.0
    rows_by_name = {}

    def col_by_tokens(df, token_sets, prefer_numeric=False):
        """Primeira coluna que casa os tokens. Sets mais específicos primeiro
        (para cada set, varre todas as colunas — evita que um set solto tipo
        ['r','h'] capture 'Rendimento hh/ha'). prefer_numeric: entre as
        candidatas do set, escolhe a que tem valores numéricos."""
        cols = list(df.columns)
        for toks in token_sets:
            found = []
            for c in cols:
                nc = normalizar_chave(c)
                if all(t in nc for t in toks):
                    if not prefer_numeric:
                        return c
                    found.append(c)
            if not found:
                continue
            for c in found:
                amostra = [v for v in df[c].head(20).tolist() if v is not None and str(v).strip() not in ("", "nan")]
                if any(_to_float_any(v) for v in amostra):
                    return c
            return found[0]
        return None

    col_nome = col_by_tokens(
        dfh,
        [["operac"], ["atividade"], ["descricao"], ["servico"]],
    )
    col_tipo = col_by_tokens(dfh, [["tipo"]])
    col_hh = col_by_tokens(
        dfh,
        [["rendimento", "hh"], ["homem", "hora"], ["hh", "ha"]],
    )
    col_hm = col_by_tokens(
        dfh,
        [["rendimento", "maq"], ["rendimento", "maquina"], ["hm"], ["maquina", "ha"]],
    )
    col_preco = col_by_tokens(dfh, [["preco"], ["tarifa"], ["valor"]])
    col_custo_h = col_by_tokens(dfh, [["custo", "hora"], ["r", "h"]], prefer_numeric=True)

    # Parser moderno (CT317 real)
    if col_nome and (col_hh or col_hm):
        for _, r in dfh.iterrows():
            nome = str(r.get(col_nome, "")).strip()
            if not nome or nome.lower() in {"nan", "none"}:
                continue
            if normalizar_chave(nome) in {"operacoes", "operacao", "atividade"}:
                continue
            hh = _to_float_any(r.get(col_hh)) if col_hh else 0.0
            hm = _to_float_any(r.get(col_hm)) if col_hm else 0.0
            preco = _to_float_any(r.get(col_preco)) if col_preco else 0.0
            tipo = str(r.get(col_tipo, "")).strip() if col_tipo else ""
            custo_h = _to_float_any(r.get(col_custo_h)) if col_custo_h else 0.0
            hh = float(hh or 0.0)
            hm = float(hm or 0.0)
            preco = float(preco or 0.0)
            custo_h = float(custo_h or 0.0)
            if hh <= 0 and hm <= 0 and preco <= 0:
                continue
            prev = rows_by_name.get(nome)
            payload = {
                "atividade": nome,
                "tipo": tipo or ("Mecanizada" if hm > 0 else "Manual"),
                "rendimento_hh": hh,
                "rendimento_hm": hm,
                "preco_ha": preco,
                "custo_hora": custo_h,
                "custo_ha": (hh * custo_h) if custo_h > 0 else 0.0,
                "fonte_aba": pf,
            }
            if prev is None:
                rows_by_name[nome] = payload
            else:
                # Mantem a linha mais informativa (HH/HM/preco/custo maiores).
                prev_score = (
                    float(prev.get("rendimento_hh", 0) or 0)
                    + float(prev.get("rendimento_hm", 0) or 0)
                    + float(prev.get("preco_ha", 0) or 0)
                    + float(prev.get("custo_hora", 0) or 0)
                )
                cur_score = hh + hm + preco + custo_h
                if cur_score >= prev_score:
                    rows_by_name[nome] = payload

    # Fallback legado (layout por indice fixo)
    if len(rows_by_name) < 20:
        df = ExcelReader.read(caminho_ct, sheet_name=pf, header=None)
        for i in range(5, len(df)):
            r = df.iloc[i]
            nome = str(r[2]).strip() if pd.notna(r[2]) else ""
            if not nome or nome == "0":
                continue
            tipo = str(r[4]).strip() if pd.notna(r[4]) else ""
            try:
                hh = float(r[5]) if pd.notna(r[5]) else 0.0
            except (TypeError, ValueError):
                hh = 0.0
            try:
                hm = float(r[6]) if pd.notna(r[6]) else 0.0
            except (TypeError, ValueError):
                hm = 0.0
            try:
                preco = float(r[7]) if pd.notna(r[7]) else 0.0
            except (TypeError, ValueError):
                preco = 0.0
            if hh <= 0 and hm <= 0 and preco <= 0:
                continue
            rows_by_name[nome] = {
                "atividade": nome,
                "tipo": tipo or ("Mecanizada" if hm > 0 else "Manual"),
                "rendimento_hh": hh,
                "rendimento_hm": hm,
                "preco_ha": preco,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "fonte_aba": pf,
            }

    # Fonte oficial adicional: preco_final.json (projeto/Downloads) com HH/HM/preco.
    # Regra de negocio: quando HH existir, HM e zerado.
    mapa_json = _carregar_mapa_preco_final_json()
    if mapa_json:
        _aplicar_mapa_preco_final_em_rows_by_name(
            rows_by_name, mapa_json, f"{pf}|preco_final_json"
        )

    # Fallback hardcoded de HH para operacao basica quando o parser nao conseguir
    # popular uma tarifa essencial do fluxo ATM.
    for nome, base in CT317_HARDCODE_HH_BASE.items():
        cur = rows_by_name.get(nome)
        if cur is None:
            cur = {
                "atividade": nome,
                "tipo": base.get("tipo", "Manual"),
                "rendimento_hh": float(base.get("rendimento_hh", 0) or 0),
                "rendimento_hm": float(base.get("rendimento_hm", 0) or 0),
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "fonte_aba": f"{pf}|hardcoded_hh",
            }
            rows_by_name[nome] = cur
            continue
        hh_cur = float(cur.get("rendimento_hh", 0) or 0)
        hm_cur = float(cur.get("rendimento_hm", 0) or 0)
        hh_base = float(base.get("rendimento_hh", 0) or 0)
        hm_base = float(base.get("rendimento_hm", 0) or 0)
        if hh_base > 0 and hh_cur <= 0:
            cur["rendimento_hh"] = hh_base
            cur["rendimento_hm"] = 0.0
            cur["tipo"] = base.get("tipo", "Manual")
            cur["fonte_aba"] = f"{pf}|hardcoded_hh"
        elif hh_cur <= 0 and hm_cur <= 0:
            cur["rendimento_hh"] = hh_base
            cur["rendimento_hm"] = hm_base
            cur["tipo"] = cur.get("tipo") or base.get("tipo", "Manual")
            cur["fonte_aba"] = f"{pf}|hardcoded_hh"
        if float(cur.get("rendimento_hh", 0) or 0) > 0 and float(
            cur.get("rendimento_hm", 0) or 0
        ) > 0:
            cur["rendimento_hm"] = 0.0

    rows = list(rows_by_name.values())

    # Custo hora base: mediana dos custos hora lidos da planilha.
    custos_h_validos = [float(r.get("custo_hora", 0) or 0) for r in rows if float(r.get("custo_hora", 0) or 0) > 0]
    if custos_h_validos:
        custo_hora_tf = float(median(custos_h_validos))

    # Se algum item de HH nao tiver custo_hora, aplica custo_hora_tf para manter custo_ha coerente.
    for r in rows:
        hh = float(r.get("rendimento_hh", 0) or 0)
        ch = float(r.get("custo_hora", 0) or 0)
        if hh > 0 and ch <= 0 and custo_hora_tf > 0:
            ch = custo_hora_tf
            r["custo_hora"] = ch
        r["custo_ha"] = (hh * ch) if ch > 0 else 0.0

    df_stg = pd.DataFrame(rows)
    meta = pd.DataFrame(
        [
            {
                "gerado_em": datetime.datetime.now().isoformat(),
                "arquivo_origem": os.path.basename(caminho_ct),
                "linhas_validas": len(rows),
                "custo_hora_tf": round(custo_hora_tf, 4),
            }
        ]
    )

    stg_path = os.path.join(INPUT_DIR, STG_FILENAME)
    with pd.ExcelWriter(stg_path, engine="openpyxl") as w:
        df_stg.to_excel(w, sheet_name="STG_TARIFAS", index=False)
        meta.to_excel(w, sheet_name="STG_METADATA", index=False)

    return stg_path, len(rows), custo_hora_tf

def carregar_stg_tarifas(stg_path):
    """Le STG_TARIFAS e retorna dict {atividade: {rendimento_hh, preco_ha, custo_hora, custo_ha, tipo}}."""
    df = ExcelReader.read(stg_path, sheet_name="STG_TARIFAS")
    t = {}
    for _, r in df.iterrows():
        nome = str(r.get("atividade", "")).strip()
        if not nome:
            continue
        hh = float(r.get("rendimento_hh") or 0)
        hm = float(r.get("rendimento_hm") or 0)
        t[nome] = {
            "rendimento_hh": hh,
            "rendimento_hm": hm,
            "preco_ha": float(r.get("preco_ha") or 0),
            "custo_hora": float(r.get("custo_hora") or 0),
            "custo_ha": float(r.get("custo_ha") or 0),
            "tipo": str(r.get("tipo") or ""),
            "preco_unit": float(r.get("preco_ha") or 0),
            "recurso": "homem" if hh > 0 else "maquina",
            "eficiencia": 1.0,
        }
    return t


def _guess_sheet(xls, keys):
    for s in xls.sheet_names:
        ns = normalizar_chave(s)
        if all(k in ns for k in keys):
            return s
    return None


def _pick_col(df, required_tokens_sets):
    cols = list(df.columns)
    for c in cols:
        nc = normalizar_chave(c)
        for toks in required_tokens_sets:
            if all(t in nc for t in toks):
                return c
    return None


def _last_non_zero(nums):
    for n in reversed(nums):
        if n is not None and abs(float(n)) > 1e-9:
            return float(n)
    for n in reversed(nums):
        if n is not None:
            return float(n)
    return 0.0


def _is_raw_cost_row_label(lbl):
    n = normalizar_chave(lbl)
    if not n:
        return False
    bad = {
        "indireto",
        "custo indireto pessoal",
        "custo indireto",
        "custo direto",
        "bdi",
        "soma",
    }
    if n in bad:
        return False
    if n in {"d", "premio"}:
        return False
    if n.startswith("previsao "):
        return False
    if n.startswith("resultado "):
        return False
    if n.startswith("desconto "):
        return False
    return True


def _extrair_custos_globais_brutos(caminho, sheet_cd, sheet_ci):
    def parse_sheet(sheet_name):
        df = ExcelReader.read(caminho, sheet_name=sheet_name, header=None)
        itens = []
        total_linha = None
        for _, r in df.iterrows():
            label = str(r.iloc[0] if len(r) > 0 else "").strip()
            if not label:
                continue
            nums = []
            for v in list(r.iloc[1:]):
                fv = _to_float_any(v)
                if fv is not None:
                    nums.append(fv)
            nlabel = normalizar_chave(label)
            if nlabel in {"custo direto", "custo indireto"}:
                total_linha = _last_non_zero(nums)
                continue
            if _is_raw_cost_row_label(label):
                val = _last_non_zero(nums)
                if abs(val) > 1e-9:
                    itens.append({"item": label, "valor": round(float(val), 6)})
        total = (
            float(total_linha)
            if total_linha is not None
            else float(sum(x["valor"] for x in itens))
        )
        return total, itens

    total_cd, itens_cd = parse_sheet(sheet_cd)
    total_ci, itens_ci = parse_sheet(sheet_ci)
    return {
        "valor_direto_total": round(float(total_cd), 6),
        "valor_indireto_total": round(float(total_ci), 6),
        "itens_direto": itens_cd,
        "itens_indireto": itens_ci,
    }


def modulo_importar_custos_globais_brutos(cfg):
    from .io import selecionar_arquivo

    dashboard_header()
    subcabecalho("IMPORTAR CUSTOS GLOBAIS (BRUTO)")
    caminho = selecionar_arquivo(
        "PLANILHA BRUTA DE CUSTOS (CUSTO_DIRETO/CUSTO_INDIRETO)"
    )
    if not caminho:
        return
    try:
        xls = pd.ExcelFile(caminho)
        cd = _guess_sheet(xls, ["custo", "direto"])
        ci = _guess_sheet(xls, ["custo", "indireto"])
        sub()
        print(G + " CUSTO_DIRETO : " + C + f"{cd or '??'}" + RS)
        print(G + " CUSTO_INDIRETO : " + C + f"{ci or '??'}" + RS)
        if not (cd and ci) or not confirmar(
            "Usar mapeamento automatico de abas?", default=True
        ):
            cd = selecionar("ABA CUSTO_DIRETO", xls.sheet_names)
            if cd is None:
                return
            ci = selecionar("ABA CUSTO_INDIRETO", xls.sheet_names)
            if ci is None:
                return

        ext = _extrair_custos_globais_brutos(caminho, cd, ci)
        cfg["custos_globais"] = {
            "arquivo": os.path.basename(caminho),
            "sheet_custo_direto": cd,
            "sheet_custo_indireto": ci,
            "valor_direto_total": ext["valor_direto_total"],
            "valor_indireto_total": ext["valor_indireto_total"],
            "criterio": "ultimo_valor_na_linha",
            "itens_direto": ext["itens_direto"],
            "itens_indireto": ext["itens_indireto"],
        }
        salvar_config(cfg)
        ok(
            "Custos globais importados: "
            f"Direto R$ {ext['valor_direto_total']:,.2f} | "
            f"Indireto R$ {ext['valor_indireto_total']:,.2f}"
        )
        print(
            DM
            + f" Itens lidos: direto={len(ext['itens_direto'])} | indireto={len(ext['itens_indireto'])}"
            + RS
        )
    except Exception as ex:
        erro(f"Falha ao importar custos globais brutos: {ex}")
        esperar(DM + "\n [ENTER para voltar] " + RS)


def modulo_importar_precos_contrato(cfg):
    from .io import _find_default_ct_path, selecionar_arquivo

    dashboard_header()
    subcabecalho("IMPORTAR PLANILHA DE PRECO (CONTRATO)")
    caminho = selecionar_arquivo(
        "PLANILHA DE PRECO (3 abas: PRECO_FINAL/CUSTO_DIRETO/CUSTO_INDIRETO)"
    )
    if not caminho:
        return
    try:
        tarifas_ct_ref = {}
        ct_path = _find_default_ct_path()
        if ct_path:
            try:
                stg_path, n_ct, _ = normalizar_ct313(ct_path)
                if stg_path and n_ct > 0:
                    tarifas_ct_ref = carregar_stg_tarifas(stg_path)
            except (OSError, ValueError):
                tarifas_ct_ref = {}
        if not tarifas_ct_ref:
            tarifas_ct_ref = dict(cfg.get("tarifas", {}) or {})
        tarifas_ct_idx = {normalizar_chave(k): v for k, v in tarifas_ct_ref.items()}
        de_para_cfg = cfg.get("de_para", {}) or {}

        xls = pd.ExcelFile(caminho)
        pf = _guess_sheet(xls, ["preco", "final"])
        cd = _guess_sheet(xls, ["custo", "direto"])
        ci = _guess_sheet(xls, ["custo", "indireto"])
        sub()
        print(G + " PRECO_FINAL : " + C + f"{pf or '??'}" + RS)
        print(G + " CUSTO_DIRETO : " + C + f"{cd or '??'}" + RS)
        print(G + " CUSTO_INDIRETO : " + C + f"{ci or '??'}" + RS)
        if not (pf and cd and ci) or not confirmar(
            "Usar mapeamento automatico de abas?", default=True
        ):
            pf = selecionar("ABA PRECO_FINAL", xls.sheet_names)
            if pf is None:
                return
            cd = selecionar("ABA CUSTO_DIRETO", xls.sheet_names)
            if cd is None:
                return
            ci = selecionar("ABA CUSTO_INDIRETO", xls.sheet_names)
            if ci is None:
                return

        df_pf = ExcelReader.read(caminho, sheet_name=pf)
        df_cd = ExcelReader.read(caminho, sheet_name=cd)
        df_ci = ExcelReader.read(caminho, sheet_name=ci)

        col_atv_pf = _pick_col(df_pf, [["atividade"], ["servico"], ["descricao"]])
        col_preco = _pick_col(df_pf, [["preco", "final"], ["preco"], ["valor"]])
        col_hh = _pick_col(df_pf, [["hh"], ["homem", "hora"], ["rendimento", "hh"]])
        col_hm = _pick_col(df_pf, [["hm"], ["hora", "maquina"], ["rendimento", "hm"]])
        col_tipo = _pick_col(df_pf, [["tipo"]])

        col_atv_cd = _pick_col(df_cd, [["atividade"], ["servico"], ["descricao"]])
        col_cd = _pick_col(df_cd, [["custo", "direto"], ["direto"], ["valor"]])
        col_atv_ci = _pick_col(df_ci, [["atividade"], ["servico"], ["descricao"]])
        col_ci = _pick_col(df_ci, [["custo", "indireto"], ["indireto"], ["valor"]])

        if not col_atv_pf or not col_preco:
            erro(
                "Nao foi possivel identificar colunas minimas de PRECO_FINAL (atividade/preco)."
            )
            esperar(DM + "\n [ENTER] " + RS)
            return

        custo_direto = {}
        if col_atv_cd and col_cd:
            for _, r in df_cd.iterrows():
                atv = str(r.get(col_atv_cd, "")).strip()
                if not atv:
                    continue
                try:
                    custo_direto[normalizar_chave(atv)] = float(
                        str(r.get(col_cd, 0)).replace(",", ".")
                    )
                except (TypeError, ValueError):
                    pass
        custo_indireto = {}
        if col_atv_ci and col_ci:
            for _, r in df_ci.iterrows():
                atv = str(r.get(col_atv_ci, "")).strip()
                if not atv:
                    continue
                try:
                    custo_indireto[normalizar_chave(atv)] = float(
                        str(r.get(col_ci, 0)).replace(",", ".")
                    )
                except (TypeError, ValueError):
                    pass

        tarifas = {}
        for _, r in df_pf.iterrows():
            atv = str(r.get(col_atv_pf, "")).strip()
            if not atv:
                continue
        try:
            preco = float(str(r.get(col_preco, 0)).replace(",", "."))
        except (TypeError, ValueError):
            preco = 0.0
        try:
            hh_pf = (
                float(str(r.get(col_hh, 0)).replace(",", ".")) if col_hh else 0.0
            )
        except (TypeError, ValueError):
            hh_pf = 0.0
        try:
            hm = float(str(r.get(col_hm, 0)).replace(",", ".")) if col_hm else 0.0
        except (TypeError, ValueError):
            hm = 0.0
            nk = normalizar_chave(atv)
            chave_ct = str(de_para_cfg.get(atv, atv) or atv).strip()
            nk_ct = normalizar_chave(chave_ct)
            row_ct = tarifas_ct_idx.get(nk_ct, tarifas_ct_idx.get(nk, {}))
        try:
            hh_ct = float(row_ct.get("rendimento_hh", 0) or 0.0)
        except (TypeError, ValueError):
            hh_ct = 0.0
        try:
            hm_ct = float(row_ct.get("rendimento_hm", 0) or 0.0)
        except (TypeError, ValueError):
            hm_ct = 0.0
            hh = hh_ct if hh_ct > 0 else hh_pf
            hm = max(hm, hm_ct)
            tipo = (
                str(r.get(col_tipo, "")).strip()
                if col_tipo and str(r.get(col_tipo, "")).strip()
                else str(row_ct.get("tipo", "")).strip()
            )
            if not tipo:
                tipo = "Mecanizada" if hm > 0 else "Manual"
            cd_v = float(custo_direto.get(nk, 0.0))
            ci_v = float(custo_indireto.get(nk, 0.0))
        try:
            c_h = float(row_ct.get("custo_hora", 0) or 0.0)
        except (TypeError, ValueError):
            c_h = 0.0
            if c_h <= 0:
                c_h = float(cfg.get("custo_hora_tf") or 0.0)
            if hh <= 0.01 and hm > 0:
                c_h = 0.0
            payload = {
                "rendimento_hh": hh,
                "rendimento_hm": hm,
                "preco_ha": preco,
                "preco_unit": preco,
                "custo_hora": c_h,
                "custo_ha": (hh * c_h) if c_h > 0 else 0.0,
                "tipo": tipo,
                "recurso": "maquina" if hm > 0 and hh <= 0.01 else "homem",
                "eficiencia": 1.0,
                "custo_direto": cd_v,
                "custo_indireto": ci_v,
            }
            tarifas[atv] = payload
            if nk_ct and nk_ct != nk:
                tarifas[chave_ct] = dict(payload)

        if not tarifas:
            erro("Nenhuma atividade valida encontrada na planilha de preco.")
            esperar(DM + "\n [ENTER] " + RS)
            return

        cfg["tarifas"] = tarifas
        cfg["precos_contrato"] = {
            "arquivo": os.path.basename(caminho),
            "sheet_preco_final": pf,
            "sheet_custo_direto": cd,
            "sheet_custo_indireto": ci,
        }
        salvar_config(cfg)
        ok(f"{len(tarifas)} tarifas importadas da planilha de contrato.")
        sem_hh = [
            k
            for k, v in tarifas.items()
            if float(v.get("rendimento_hh", 0) or 0) <= 0
            and float(v.get("rendimento_hm", 0) or 0) <= 0
        ]
        sem_preco = [
            k for k, v in tarifas.items() if float(v.get("preco_unit", 0) or 0) <= 0
        ]
        if sem_hh:
            print(
                Y
                + f"\n Pos-import: {len(sem_hh)} tarifa(s) sem rendimento (HH e HM zerados):"
                + RS
            )
            for x in sem_hh[:5]:
                print(DM + f" - {str(x)[:55]}" + RS)
            if len(sem_hh) > 5:
                print(DM + f" ... +{len(sem_hh) - 5}" + RS)
        if sem_preco:
            print(
                Y + f"\n Pos-import: {len(sem_preco)} tarifa(s) com preco zerado:" + RS
            )
            for x in sem_preco[:5]:
                print(DM + f" - {str(x)[:55]}" + RS)
            if len(sem_preco) > 5:
                print(DM + f" ... +{len(sem_preco) - 5}" + RS)
        if not sem_hh and not sem_preco:
            ok("Pos-import: todas as tarifas possuem HH e preco validos.")
        esperar(DM + "\n [ENTER para voltar] " + RS)
    except Exception as ex:
        erro(f"Falha ao importar planilha de preco: {ex}")
        esperar(DM + "\n [ENTER] " + RS)


def _to_float_any(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        # Ex.: 1.234,56 -> 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def resolver_chave_tarifa(cfg, tarifas, atv):
    """
    Resolve a chave de tarifa para uma atividade do micro.
    Prioridade:
    1) de_para[atividade] quando existir e estiver em tarifas;
    2) nome original da atividade quando existir em tarifas;
    3) fallback para a chave mapeada (mesmo ausente) para manter diagnostico claro.
    """
    de_para = cfg.get("de_para", {}) or {}
    tarifas = tarifas or {}

    def _find_key_norm(target, keys):
        nt = normalizar_chave(target)
        if not nt:
            return None
        for k in keys:
            if normalizar_chave(k) == nt:
                return k
        for k in keys:
            nk = normalizar_chave(k)
            if nt in nk or nk in nt:
                return k
        return None

    # 1) de_para exato
    t_map = de_para.get(atv)
    # 1b) de_para por chave normalizada (evita mismatch de acento/espacos/caixa)
    if not t_map:
        natv = normalizar_chave(atv)
        for km, vm in de_para.items():
            if normalizar_chave(km) == natv:
                t_map = vm
                break
    t_map = str(t_map or atv)

    # 2) busca exata em tarifas
    if t_map in tarifas:
        return t_map
    if atv in tarifas:
        return atv

    # 3) busca normalizada nas tarifas
    k_norm = _find_key_norm(t_map, tarifas.keys())
    if k_norm:
        return k_norm
    a_norm = _find_key_norm(atv, tarifas.keys())
    if a_norm:
        return a_norm

    # 4) fallback diagnostico
    return t_map

def modulo_mapeamentos_de_para(cfg, df_micro=None):
    """CRUD de_para: nome no microplanejamento -> nome da tarifa em config.tarifas."""
    tarifas = cfg.get("tarifas", {})
    nomes_tarifa = sorted(tarifas.keys(), key=lambda x: str(x))
    atividades_micro = []
    if (
        df_micro is not None
        and getattr(df_micro, "columns", None) is not None
        and "atividade" in df_micro.columns
    ):
        atividades_micro = sorted(
            df_micro["atividade"].dropna().unique().tolist(), key=str
        )

    while True:
        dashboard_header()
        subcabecalho("MAPEAMENTOS de_para (micro -> tarifa)")
        d = cfg.get("de_para", {})
        pairs = [(k, v) for k, v in d.items() if not str(k).startswith("_")]
        if not pairs:
            print(
                DM
                + "  Nenhum par (o sistema usa nome micro = nome na tarifa, ou default 8 h/ha)."
                + RS
            )
        else:
            for k, v in sorted(pairs, key=lambda x: str(x[0]))[:35]:
                print(G + f"  {str(k)[:36]:36} -> " + C + f"{str(v)[:36]}" + RS)
            if len(pairs) > 35:
                print(DM + f"  ... +{len(pairs) - 35} pares no arquivo" + RS)
        sub()
        print(DM + "  [1] Incluir ou alterar par" + RS)
        print(DM + "  [2] Remover par" + RS)
        print(DM + "  [3] Listar catalogo de TARIFAS (nomes em config)" + RS)
        print(DM + "  [0] Voltar" + RS)
        op = prompt("Opcao").strip()
        if op == "0":
            return
        if op == "1":
            chave_micro = ""
            if atividades_micro and confirmar(
                "Escolher atividade da planilha carregada?", default=True
            ):
                idx = selecionar_paginado(
                    "ATIVIDADE no micro", atividades_micro, page_size=8
                )
                if idx >= 0:
                    chave_micro = atividades_micro[idx]
            if not chave_micro:
                chave_micro = prompt("Nome EXATO da atividade no microplanejamento", "")
            if not chave_micro:
                aviso("Nome vazio.")
                continue
            val_tarifa = ""
            if nomes_tarifa and confirmar(
                "Escolher tarifa na lista importada?", default=True
            ):
                idx = selecionar_paginado(
                    "TARIFA (orcamento)", nomes_tarifa, page_size=8
                )
                if idx >= 0:
                    val_tarifa = nomes_tarifa[idx]
            if not val_tarifa:
                val_tarifa = prompt("Nome da TARIFA (chave em tarifas)", "")
            if not val_tarifa:
                aviso("Tarifa vazio.")
                continue
            if val_tarifa not in tarifas:
                if not confirmar(
                    f"  '{str(val_tarifa)[:42]}' nao esta em tarifas. Gravar mesmo assim?",
                    default=False,
                ):
                    continue
            cfg.setdefault("de_para", {})
            cfg["de_para"][chave_micro] = val_tarifa
            salvar_config(cfg)
            ok("Mapeamento salvo em config.json.")
        elif op == "2":
            keys = sorted([k for k in d.keys() if not str(k).startswith("_")], key=str)
            if not keys:
                aviso("Nada para remover.")
                continue
            idx = selecionar_paginado("REMOVER mapeamento", [str(k) for k in keys])
            if idx >= 0:
                del cfg["de_para"][keys[idx]]
                salvar_config(cfg)
                ok("Removido.")
        elif op == "3":
            if not nomes_tarifa:
                aviso("Nenhuma tarifa em config. Use menu [2] Importar.")
            else:
                for i, n in enumerate(nomes_tarifa[:60], 1):
                    print(DM + f"  {i:3}. {str(n)[:58]}" + RS)
                if len(nomes_tarifa) > 60:
                    print(DM + f"  ... +{len(nomes_tarifa) - 60}" + RS)
            esperar()
        else:
            aviso("Opcao invalida.")

def aviso_politica_tarifas_planas():
    """Politica comercial-executiva: base CT sempre 'plana' (Classe I) onde o micro nao discrimina."""
    sub()
    print(Y + BL + "  POLITICA DE DECLIVIDADE E ROÇADA MANUAL (CT)" + RS)
    print(
        DM
        + "  Na CT, ROÇADA MANUAL CLASSE I = terreno mais plano (menos HH/ha, menor R$/ha); "
        "CLASSE V = declive maximo (mais HH, mais R$/ha — obra mais cara e precos mais altos)."
        + RS
    )
    print(
        Y
        + "  Padrao deste app: o exame nao informa a classe por talhao — usamos sempre as linhas "
        "EQUIVALENTES AO CENARIO MAIS PLANO (ex.: ROÇADA MANUAL CLASSE I) no de_para fixo."
        + RS
    )
    print(
        DM
        + "  Interpretacao: simulacao conservadora em LUCRO — como se nao houvesse premio de "
        "declividade na mixagem; em campo inclinado real, revise o menu [4] de_para para "
        "Classes II–V conforme a CT." + RS
    )
    sub()

