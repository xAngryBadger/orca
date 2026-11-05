"""Registry de comandos do menu principal — extração sem mudança de comportamento de app.py."""

from __future__ import annotations

import pandas as pd
from typing import Callable, Dict, Any, Optional, Tuple, List

from .config import (
    STG_FILENAME,
    modo_somente_hh,
    salvar_config,
)
from .context import contexto_sessao, dashboard_header
from .io import (
    ExcelReader,
    _to_float_br,
    encontrar_coluna,
    selecionar_arquivo,
)
from .monitor import _emitir_monitor_atual
from .tarifas import (
    carregar_stg_tarifas,
    modulo_importar_custos_globais_brutos,
    modulo_importar_precos_contrato,
    normalizar_ct313,
    resolver_rendimento_hh,
)
from .territorio import modulo_validar_fazendas_ct
from .text_utils import normalizar_chave, parse_intervalos_escolha
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


# ──────────────────────────────────────────────
#  COMANDOS DO MENU PRINCIPAL
# ──────────────────────────────────────────────

def modulo_normalizar_ct(cfg: Dict[str, Any]) -> None:
    """Menu: selecionar CT bruta, gerar STG, integrar em config.tarifas."""
    dashboard_header()
    subcabecalho("NORMALIZAR CT (CT317 REAL) -> STG_TARIFAS")
    caminho = selecionar_arquivo("CT BRUTA/REAL (.xlsm ou .xlsx)")
    if not caminho:
        return

    print(DM + "  Processando... pode demorar alguns segundos." + RS)
    stg_path, n, custo_h = normalizar_ct313(caminho)
    if not stg_path:
        erro("Aba 'Preco Final' nao encontrada neste arquivo.")
        esperar()
        return

    if modo_somente_hh(cfg):
        ok(f"Gerado {STG_FILENAME}: {n} atividades (modo somente HH).")
    else:
        ok(f"Gerado {STG_FILENAME}: {n} atividades | custo/hora TF = R${custo_h:.2f}")

    if confirmar(
        "Integrar STG_TARIFAS em config.json (substitui tarifas existentes)?",
        default=True,
    ):
        tarifas = carregar_stg_tarifas(stg_path)
        cfg["tarifas"] = tarifas
        cfg["custo_hora_tf"] = round(custo_h, 4)
        salvar_config(cfg)
        ok(f"{len(tarifas)} tarifas integradas no config.")
    esperar("ENTER para voltar")


def modulo_importar_tarifas(cfg: Dict[str, Any]) -> None:
    dashboard_header()
    subcabecalho("IMPORTAR TARIFAS ORCADAS (CT_313)")
    caminho = selecionar_arquivo("PLANILHA DE ORCAMENTO (CT_313 ou Tarifas)")
    if not caminho:
        return

    try:
        print(DM + "  Carregando arquivo..." + RS)
        xls = pd.ExcelFile(caminho)
        aba = selecionar("SELECIONE A ABA (ex: Preco Final)", xls.sheet_names)
        if aba is None:
            return

        print(DM + f"  Lendo aba '{aba}'..." + RS)
        df = ExcelReader.read(caminho, sheet_name=aba, nrows=1000)
        cols_ct = df.columns.tolist()

        # Tentar mapear automaticamente
        col_atv = encontrar_coluna(cols_ct, "atividade")
        sub()
        print(G + BL + "  MAPEAMENTO:" + RS)
        print(G + "  Atividade: " + C + f"{col_atv or '???'}" + RS)
        sub()

        if not col_atv or not confirmar("Usar este mapeamento?", default=True):
            idx = selecionar_paginado("COLUNA DA ATIVIDADE", cols_ct)
            col_atv = cols_ct[idx] if idx >= 0 else None
            if not col_atv:
                aviso("Atividade obrigatoria.")
                return

        # Para HH e Preco, perguntar diretamente
        print(G + "\n  Selecione as colunas adicionais (0 = ignorar):\n" + RS)
        idx = selecionar_paginado("COLUNA DE HH/HA", cols_ct)
        col_hh = cols_ct[idx] if idx >= 0 else None
        idx = selecionar_paginado("COLUNA DE PRECO UNITARIO", cols_ct)
        col_preco = cols_ct[idx] if idx >= 0 else None

        tarifas = cfg.get("tarifas", {})
        importadas = 0
        for _, row in df.iterrows():
            nome = str(row.get(col_atv, "")).strip()
            if not nome or nome.lower() == "nan":
                continue
            hh = 0 if not col_hh else row.get(col_hh, 0)
            preco = 0 if not col_preco else row.get(col_preco, 0)
        if pd.notna(hh) and str(hh).strip() != "":
            hh_val = _to_float_br(hh)
        else:
            hh_val = resolver_rendimento_hh(cfg, tarifas, nome)
            preco_val = _to_float_br(preco) if pd.notna(preco) else 0.0
            tarifas[nome] = {
                "rendimento_hh": hh_val,
                "preco_unit": preco_val,
                "recurso": "homem",
                "eficiencia": 1.0,
            }
            importadas += 1

        cfg["tarifas"] = tarifas
        salvar_config(cfg)
        ok(f"{importadas} tarifas integradas!")
        sem_hh = [
            k for k, v in tarifas.items() if float(v.get("rendimento_hh", 0) or 0) <= 0
        ]
        sem_preco = [
            k for k, v in tarifas.items() if float(v.get("preco_unit", 0) or 0) <= 0
        ]
        if sem_hh:
            print(Y + f"  Pos-import: {len(sem_hh)} tarifa(s) com HH zerado." + RS)
            for x in sem_hh[:5]:
                print(DM + f"    - {str(x)[:55]}" + RS)
        if sem_preco:
            print(
                Y + f"  Pos-import: {len(sem_preco)} tarifa(s) com preco zerado." + RS
            )
            for x in sem_preco[:5]:
                print(DM + f"    - {str(x)[:55]}" + RS)
    except Exception as e:
        erro(f"Erro ao importar: {e}")

    esperar("ENTER para voltar")


def _aplicar_filtro_regiao(df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[Dict[str, str]]]:
    """Filtro opcional por regiao (municipio/estado). Retorna (df_filtrado, regiao_info ou None)."""
    tem_mun = "municipio" in df.columns
    tem_est = "estado" in df.columns
    if not tem_mun and not tem_est:
        return df, None
    df_filt = df.copy()
    regiao_info = {}
    estados_disp = []
    municipios_disp = []
    if tem_est:
        estados_disp = sorted(
            {str(x).strip() for x in df["estado"].dropna().tolist() if str(x).strip()}
        )
    if tem_mun:
        municipios_disp = sorted(
            {str(x).strip() for x in df["municipio"].dropna().tolist() if str(x).strip()}
        )
    n_est = len(estados_disp)
    n_mun = len(municipios_disp)
    print(G + BL + "\n FILTRO POR REGIAO" + RS)
    print(DM + f" {n_est} estado(s), {n_mun} municipio(s) detectado(s) no micro." + RS)
    if not confirmar("Filtrar por regiao (municipio/estado)?", default=False):
        ok("Filtro de regiao ignorado — todos os dados incluidos.")
        return df_filt, None
    sel_estado = None
    sel_municipio = None
    if tem_est and estados_disp:
        if n_est == 1:
            sel_estado = estados_disp[0]
            ok(f"Unico estado: {sel_estado}")
        else:
            op_est = ["TODOS"] + estados_disp
            sel_estado = selecionar("ESTADO", op_est)
            if sel_estado == "TODOS":
                sel_estado = None
    if sel_estado and tem_mun:
        mun_filtrados = sorted(
            {
                str(x).strip()
                for x in df_filt[df_filt["estado"].astype(str).str.strip() == sel_estado]["municipio"].dropna().tolist()
                if str(x).strip()
            }
        )
    elif tem_mun:
        mun_filtrados = municipios_disp
    else:
        mun_filtrados = []
    if mun_filtrados:
        if len(mun_filtrados) == 1:
            sel_municipio = mun_filtrados[0]
            ok(f"Unico municipio: {sel_municipio}")
        else:
            op_mun = ["TODOS"] + mun_filtrados
            sel_municipio = selecionar("MUNICIPIO", op_mun)
            if sel_municipio == "TODOS":
                sel_municipio = None
    if sel_estado:
        df_filt = df_filt[df_filt["estado"].astype(str).str.strip() == sel_estado]
        regiao_info["estado"] = sel_estado
    if sel_municipio:
        df_filt = df_filt[df_filt["municipio"].astype(str).str.strip() == sel_municipio]
        regiao_info["municipio"] = sel_municipio
    if regiao_info:
        loc_str = " / ".join(filter(None, [regiao_info.get("municipio"), regiao_info.get("estado")]))
        ok(
            f"Filtrado por regiao: {loc_str} ({len(df_filt)} registros, "
            f"{df_filt['fazenda'].nunique()} fazenda(s))"
        )
    else:
        ok("Nenhum filtro de regiao aplicado — todos os dados incluidos.")
    return df_filt, regiao_info or None


def _aplicar_filtro_empresa_e_escopo(df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[str]]:
    """Filtro por EQUIPE (empresa) e escopo (uma fazenda / todas). Retorna (df_filtrado, empresa ou None)."""
    tem_equipe = "equipe" in df.columns
    df_filt = df.copy()
    empresa_filtro = None
    if tem_equipe:
        raw_eq = [
            str(x).strip() for x in df["equipe"].dropna().tolist() if str(x).strip()
        ]
        norm_to_raw = {}
        for e in raw_eq:
            nk = normalizar_chave(e)
            if nk and nk not in norm_to_raw:
                norm_to_raw[nk] = e
        equipes = sorted(norm_to_raw.values(), key=str)
        if equipes:
            print(G + BL + "\n FILTRO POR EMPRESA (EQUIPE)" + RS)
            print(DM + f" {len(equipes)} empresa(s) encontrada(s) no micro." + RS)
            if not confirmar("Filtrar por empresa?", default=False):
                ok("Filtro de empresa ignorado — todos os dados incluidos.")
                contexto_sessao.atualizar_equipe(None)
                _emitir_monitor_atual()
                return df_filt, None
            if len(equipes) == 1:
                empresa_filtro = equipes[0]
                ok(f"Unica empresa: {empresa_filtro}")
            else:
                eq = selecionar("EMPRESA / EQUIPE", equipes)
                if eq:
                    empresa_filtro = eq
            if empresa_filtro:
                nk_sel = normalizar_chave(empresa_filtro)
                sem_eq = df_filt["equipe"].isna() | (
                    df_filt["equipe"].astype(str).str.strip() == ""
                )
                n_sem = int(sem_eq.sum())
                if n_sem:
                    print(
                        DM
                        + f" Excluindo {n_sem} linha(s) sem EQUIPE preenchida (nao entram no filtro por empresa)."
                        + RS
                    )
                    df_filt = df_filt[~sem_eq]
                df_filt = df_filt[
                    df_filt["equipe"]
                    .astype(str)
                    .apply(lambda x: normalizar_chave(x.strip()) == nk_sel)
                ]
                ok(
                    f"Filtrado por equipe: {empresa_filtro} ({len(df_filt)} registros, "
                    f"{df_filt['atividade'].nunique()} atividade(s), {df_filt['fazenda'].nunique()} fazenda(s))"
                )
    if empresa_filtro:
        contexto_sessao.atualizar_equipe(empresa_filtro)
    else:
        contexto_sessao.atualizar_equipe(None)
    _emitir_monitor_atual()
    return df_filt, empresa_filtro


def _selecionar_talhoes_fazenda(df_faz: pd.DataFrame, fazenda: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Permite recorte por metodologia e talhao dentro da fazenda selecionada."""
    if df_faz is None or df_faz.empty:
        contexto_sessao.definir_escopo_talhoes([], [])
        return df_faz, {
            "fazenda": fazenda,
            "modo_metodologia": "vazio",
            "metodologias": [],
            "modo_talhao": "vazio",
            "talhoes": [],
        }
    if "chave" not in df_faz.columns:
        contexto_sessao.definir_escopo_talhoes([], [])
        return df_faz, {
            "fazenda": fazenda,
            "modo_metodologia": "sem_coluna",
            "metodologias": [],
            "modo_talhao": "sem_coluna",
            "talhoes": [],
        }

    df_work = df_faz.copy()
    meta = {
        "fazenda": fazenda,
        "modo_metodologia": "sem_coluna",
        "metodologias": [],
    }

    if "metodologia" in df_work.columns:
        metodologias = sorted(
            {
                str(x).strip()
                for x in df_work["metodologia"].dropna().tolist()
                if str(x).strip()
            },
            key=str,
        )
        print(G + BL + "\n  ESCOPO POR METODOLOGIA" + RS)
        print(DM + f"  Fazenda: {fazenda}" + RS)
        if metodologias:
            print(DM + f"  Metodologias presentes ({len(metodologias)}):" + RS)
            for i, m in enumerate(metodologias, 1):
                print(G + f"  [{i:2}] " + C + str(m) + RS)
        else:
            print(DM + "  Nenhuma metodologia preenchida no escopo atual." + RS)
        if not metodologias:
            meta["modo_metodologia"] = "sem_valores"
            meta["metodologias"] = []
        elif len(metodologias) == 1:
            meta["modo_metodologia"] = "unica"
            meta["metodologias"] = metodologias[:]
            ok(f"Metodologia unica no escopo: {metodologias[0]}")
        else:
            op_met = selecionar(
                "ESCOPO DAS METODOLOGIAS",
                [
                    "TODAS AS METODOLOGIAS",
                    "SELECIONAR METODOLOGIAS POR LISTA",
                    "SELECIONAR METODOLOGIAS POR NOME",
                    "FILTRAR METODOLOGIAS POR TEXTO",
                ],
            )

            selecionadas_met = []
            if not op_met or op_met == "TODAS AS METODOLOGIAS":
                meta["modo_metodologia"] = "todas"
                meta["metodologias"] = metodologias[:]
            elif op_met == "SELECIONAR METODOLOGIAS POR LISTA":
                print(
                    DM
                    + "  Digite indices separados por virgula (ex.: 1,2,4) ou intervalo (ex.: 1-3)."
                    + RS
                )
                for i, m in enumerate(metodologias, 1):
                    print(G + f"  [{i:2}] " + C + str(m) + RS)
                raw = prompt("Metodologias", "")
                idxs = parse_intervalos_escolha(raw, len(metodologias))
                selecionadas_met = [metodologias[i] for i in idxs]
            elif op_met == "SELECIONAR METODOLOGIAS POR NOME":
                raw = prompt(
                    "Nomes das metodologias (separados por virgula)",
                    "",
                )
                partes = [
                    normalizar_chave(p)
                    for p in str(raw).replace(";", ",").split(",")
                    if normalizar_chave(p)
                ]
                if partes:
                    for m in metodologias:
                        nm = normalizar_chave(m)
                        if any(p == nm or p in nm for p in partes):
                            selecionadas_met.append(m)
            else:
                filtro = normalizar_chave(prompt("Texto para filtrar metodologia", ""))
                if filtro:
                    selecionadas_met = [
                        m for m in metodologias if filtro in normalizar_chave(m)
                    ]

            if op_met and op_met != "TODAS AS METODOLOGIAS":
                selecionadas_met = sorted(set(selecionadas_met), key=str)
                if not selecionadas_met:
                    aviso(
                        "Nenhuma metodologia selecionada; mantendo TODAS as metodologias da fazenda."
                    )
                    meta["modo_metodologia"] = "fallback_todas"
                    meta["metodologias"] = metodologias[:]
                else:
                    sel_norm = {normalizar_chave(x) for x in selecionadas_met}
                    df_filtrado = df_work[
                        df_work["metodologia"].astype(str).apply(
                            lambda x: normalizar_chave(str(x).strip()) in sel_norm
                        )
                    ].copy()
                    if df_filtrado.empty:
                        aviso(
                            "Filtro de metodologia nao retornou linhas; mantendo TODAS as metodologias da fazenda."
                        )
                        meta["modo_metodologia"] = "fallback_todas"
                        meta["metodologias"] = metodologias[:]
                    else:
                        df_work = df_filtrado
                        meta["modo_metodologia"] = "parcial"
                        meta["metodologias"] = selecionadas_met
                        ok(
                            f"Escopo por metodologia aplicado: {len(selecionadas_met)} selecionada(s), "
                            f"{len(df_work)} linha(s) no micro."
                        )

    talhoes = sorted(
        {
            str(x).strip()
            for x in df_work["chave"].dropna().tolist()
            if str(x).strip()
        },
        key=str,
    )
    if not talhoes:
        contexto_sessao.definir_escopo_talhoes([], [])
        out_meta = dict(meta)
        out_meta.update({"modo_talhao": "sem_talhoes", "talhoes": []})
        _emitir_monitor_atual()
        return df_work, out_meta
    if len(talhoes) == 1:
        ok(f"Talhao unico na fazenda: {talhoes[0]}")
        contexto_sessao.definir_escopo_talhoes(talhoes[:], talhoes[:])
        out_meta = dict(meta)
        out_meta.update({"modo_talhao": "unico", "talhoes": talhoes[:]})
        _emitir_monitor_atual()
        return df_work, out_meta

    print(G + BL + "\n  ESCOPO POR TALHAO" + RS)
    print(DM + f"  Fazenda: {fazenda}" + RS)
    print(DM + f"  {len(talhoes)} talhao(oes) disponivel(is)." + RS)
    op = selecionar(
        "ESCOPO DOS TALHOES",
        [
            "TODOS OS TALHOES",
            "SELECIONAR TALHOES POR LISTA",
            "FILTRAR TALHOES POR TEXTO",
        ],
    )
    if not op or op == "TODOS OS TALHOES":
        contexto_sessao.definir_escopo_talhoes(talhoes[:], talhoes[:])
        out_meta = dict(meta)
        out_meta.update({"modo_talhao": "todos", "talhoes": talhoes[:]})
        _emitir_monitor_atual()
        return df_work, out_meta

    selecionados = []
    if op == "SELECIONAR TALHOES POR LISTA":
        print(
            DM
            + "  Digite numeros separados por virgula (ex.: 1,3,7) ou intervalo (ex.: 1-4)."
            + RS
        )
        for i, t in enumerate(talhoes, 1):
            print(G + f"  [{i:2}] " + C + str(t) + RS)
        raw = prompt("Talhoes", "")
        idxs = parse_intervalos_escolha(raw, len(talhoes))
        selecionados = [talhoes[i] for i in idxs]
    else:
        filtro = normalizar_chave(prompt("Texto para filtrar talhoes", ""))
        if filtro:
            selecionados = [t for t in talhoes if filtro in normalizar_chave(t)]

    if not selecionados:
        aviso("Nenhum talhao selecionado; mantendo TODOS os talhoes da fazenda.")
        contexto_sessao.definir_escopo_talhoes(talhoes[:], talhoes[:])
        out_meta = dict(meta)
        out_meta.update({"modo_talhao": "fallback_todos", "talhoes": talhoes[:]})
        _emitir_monitor_atual()
        return df_work, out_meta

    df_sel = df_work[df_work["chave"].astype(str).isin(set(selecionados))].copy()
    ok(
        f"Escopo por talhao aplicado: {len(selecionados)} selecionado(s), {len(df_sel)} linha(s) no micro."
    )
    contexto_sessao.definir_escopo_talhoes(selecionados, talhoes[:])
    out_meta = dict(meta)
    out_meta.update({"modo_talhao": "parcial", "talhoes": selecionados})
    _emitir_monitor_atual()
    return df_sel, out_meta


def _metodologias_presentes(df_faz: pd.DataFrame) -> List[str]:
    if df_faz is None or df_faz.empty or "metodologia" not in df_faz.columns:
        return []
    return sorted(
        {
            str(x).strip()
            for x in df_faz["metodologia"].dropna().tolist()
            if str(x).strip()
        },
        key=str,
    )


def _prompt_proximas_metodologias(
    df_faz_base: pd.DataFrame,
    meta_escopo: Dict[str, Any],
    metodologias_executadas: set,
) -> bool:
    """
    Mostra prompt para continuar com metodologias restantes na mesma fazenda.
    Retorna True quando o usuario deseja seguir para as proximas metodologias.
    """
    todas = _metodologias_presentes(df_faz_base)
    if not todas:
        return False

    meta_escopo = meta_escopo or {}
    usadas = list(meta_escopo.get("metodologias") or [])
    for m in usadas:
        nm = normalizar_chave(m)
        if nm:
            metodologias_executadas.add(nm)

    restantes = [m for m in todas if normalizar_chave(m) not in metodologias_executadas]
    if not restantes:
        return False

    sub()
    print(C + BL + "  PROXIMAS METODOLOGIAS DISPONIVEIS" + RS)
    print(DM + f"  Restantes: {len(restantes)}" + RS)
    for i, m in enumerate(restantes[:12], 1):
        print(G + f"  [{i:2}] " + C + str(m) + RS)
    if len(restantes) > 12:
        print(DM + f"  ... +{len(restantes) - 12} metodologia(s)" + RS)
    return confirmar(
        "Executar outra metodologia desta fazenda agora?",
        default=True,
    )


def _executar_scheduler_fazenda_interativo(
    cfg: Dict[str, Any],
    df_scope: pd.DataFrame,
    faz: str,
    catalogo_scope: List[str],
) -> None:
    from .scheduler_core import calcular_cronograma_inteligente
    metodologias_executadas = set()
    while True:
        df_faz_base = df_scope[df_scope["fazenda"] == faz].copy()
        if df_faz_base.empty:
            aviso("Sem linhas para a fazenda selecionada neste escopo.")
            return

        contexto_sessao.atualizar_fazenda(faz, df_faz_base)
        df_faz, meta_escopo = _selecionar_talhoes_fazenda(df_faz_base, faz)
        resultado = calcular_cronograma_inteligente(
            cfg,
            df_faz,
            faz,
            escopo_meta=meta_escopo,
            atividades_catalogo=catalogo_scope,
        )
        if isinstance(resultado, dict) and resultado.get("acao") == "retroceder_escopo":
            aviso("Checkpoint retroativo: reselecione fazenda/escopo.")
            continue

        if _prompt_proximas_metodologias(
            df_faz_base,
            meta_escopo,
            metodologias_executadas,
        ):
            aviso("Abrindo selecao para as proximas metodologias desta fazenda.")
            continue
        break


# ──────────────────────────────────────────────
#  REGISTRY DE COMANDOS
# ──────────────────────────────────────────────

COMANDOS: Dict[str, Callable] = {
    "modulo_normalizar_ct": modulo_normalizar_ct,
    "modulo_importar_tarifas": modulo_importar_tarifas,
    "_aplicar_filtro_regiao": _aplicar_filtro_regiao,
    "_aplicar_filtro_empresa_e_escopo": _aplicar_filtro_empresa_e_escopo,
    "_selecionar_talhoes_fazenda": _selecionar_talhoes_fazenda,
    "_executar_scheduler_fazenda_interativo": _executar_scheduler_fazenda_interativo,
    "_metodologias_presentes": _metodologias_presentes,
    "_prompt_proximas_metodologias": _prompt_proximas_metodologias,
}


def montar_comandos() -> None:
    """Inicialização do registry de comandos (no-op, registry já é construído em import-time)."""
    # O registry COMANDOS já é populado no import do módulo.
    # Esta função existe para compatibilidade com entry.py que a chama no loop do menu.
    pass


def executar_comando(codigo: str, cfg: Dict[str, Any], df=None) -> None:
    """Executa comando do menu principal pelo código numérico da opção.

    Mapeamento:
        "2" -> modulo_importar_tarifas
        "3" -> modulo_normalizar_ct
        "6" -> modulo_validar_fazendas_ct
        "8" -> modulo_importar_precos_contrato
        "9" -> modulo_importar_custos_globais_brutos
    """
    if codigo == "2":
        modulo_importar_tarifas(cfg)
    elif codigo == "3":
        modulo_normalizar_ct(cfg)
    elif codigo == "6":
        if df is not None:
            modulo_validar_fazendas_ct(cfg, df)
    elif codigo == "8":
        modulo_importar_precos_contrato(cfg)
    elif codigo == "9":
        modulo_importar_custos_globais_brutos(cfg)