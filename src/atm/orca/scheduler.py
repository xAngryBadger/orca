"""Scheduler core — cascata phase logic, audit, HH adjustment, sequence selection."""

import calendar
import math
import time
from collections import OrderedDict
from collections import defaultdict

from rich.table import Table

from .config import _SEQUENCIAS_DISPONIVEIS, salvar_config
from .tarifas import resolver_chave_tarifa, resolver_rendimento_hh
from .text_utils import _norm_atv, atividades_por_filtro, normalizar_chave
from .ui import (
    BL,
    DM,
    RS,
    C,
    G,
    Y,
    aviso,
    confirmar,
    console,
    erro,
    ok,
    pedir_float,
    prompt,
    selecionar_paginado,
    sub,
    subcabecalho,
)


def _match_filtros_fase(nome_atv, filtros, exclusoes=None):
    """True se nome contem algum filtro (normalizar_chave) e nenhuma exclusao."""
    kn = normalizar_chave(nome_atv)
    for ex in exclusoes or []:
        exn = normalizar_chave(ex)
        if exn and exn in kn:
            return False
    for f in filtros or []:
        fn = normalizar_chave(f)
        if fn and fn in kn:
            return True
    return False


def eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
    """Limpeza quimica pos-plantio: todos filtros presentes e nenhuma exclusao."""
    kn = normalizar_chave(atv)
    filtros = seq_cfg.get("limpeza_quimica_filtros") or ["limpeza", "quim"]
    exclusoes = seq_cfg.get("limpeza_quimica_exclusoes") or []
    for f in filtros:
        fn = normalizar_chave(f)
        if not fn or fn not in kn:
            return False
    for ex in exclusoes:
        exn = normalizar_chave(ex)
        if exn and exn in kn:
            return False
    return True


def _fases_ordem_config(seq_cfg, modo):
    if modo == "personalizado" and seq_cfg.get("personalizado_ordem"):
        return seq_cfg["personalizado_ordem"]
    return seq_cfg.get("implantacao_fases") or []


def classificar_fase_cascata_valor(
    atv, seq_cfg, modo, atividades_plantio, atividades_irrig
):
    """
    Retorna indice numerico de fase para cascata global.
    O comportamento agora deriva inteiramente da configuração de sequência (presets ou personalizado).
    Modos sem plantio/irrigacao nas configurações (ex.: manutencao) não terão fases 6/7.
    """
    if eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
        return 8.0
    if atv in atividades_plantio or _match_filtros_fase(
        atv, seq_cfg.get("filtros_plantio") or [], None
    ):
        return 6.0
    if atv in atividades_irrig or _match_filtros_fase(
        atv, seq_cfg.get("filtros_irrigacao") or [], None
    ):
        return 7.0
    fases = _fases_ordem_config(seq_cfg, modo)
    for i, fase in enumerate(fases):
        if _match_filtros_fase(atv, fase.get("filtros") or [], fase.get("exclusoes")):
            return float(i)
    try:
        return float(seq_cfg.get("implantacao_outras_fase", 5.5))
    except (TypeError, ValueError):
        return 5.5


def _demanda_plantio_talhao(talhao, demanda_global, atividades_plantio):
    for p in atividades_plantio:
        if demanda_global.get((talhao, p), 0) > 0.01:
            return True
    return False


def limpeza_permitida_por_talhao(
    talhao,
    dia,
    seq_cfg,
    dia_termino_plantio,
    tem_plantio_previsto_no_talhao,
):
    """Se nao ha plantio no talhao, limpeza pos-plantio nao exige offset."""
    if not tem_plantio_previsto_no_talhao:
        return True
    d = dia_termino_plantio.get(talhao)
    if d is None:
        return False
    off = int(seq_cfg.get("offset_limpeza_quimica_dias", 30) or 30)
    return dia >= d + off


def _min_fase_cascata_por_talhao(
    demanda_global, seq_cfg, modo, usar_cascata, usar_bloqueio_global,
    atividades_bloqueadas, atividades_plantio, atividades_irrig,
    dia, dia_termino_plantio, tem_plantio_por_talhao,
):
    """Menor fase POR TALHAO entre demandas ainda > 0 e elegiveis neste dia.

    Retorna dict {talhao: min_fase_valor} — phase N+1 so comeca no talhao X
    quando phase N terminar naquele talhao especifico (nao espera todos).
    """
    if not usar_cascata:
        return {}
    bloqueadas = set(atividades_bloqueadas or [])
    por_talhao = defaultdict(list)
    for (talhao, atv), hh in sorted(demanda_global.items()):
        if hh <= 0.01:
            continue
        if usar_bloqueio_global and atv in bloqueadas:
            if _ha_trabalho_nao_bloqueado(demanda_global, bloqueadas):
                continue
        if eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
            if not limpeza_permitida_por_talhao(
                talhao, dia, seq_cfg,
                dia_termino_plantio, tem_plantio_por_talhao.get(talhao, False),
            ):
                continue
        fv = classificar_fase_cascata_valor(
            atv, seq_cfg, modo, atividades_plantio, atividades_irrig
        )
        por_talhao[talhao].append(fv)
    return {t: min(vs) for t, vs in por_talhao.items() if vs}


def pode_agendar_atividade_cascata(
    talhao, atv, demanda_global, seq_cfg, modo, usar_cascata,
    usar_bloqueio_global, atividades_bloqueadas, atividades_plantio,
    atividades_irrig, dia, dia_termino_plantio, tem_plantio_por_talhao,
    min_fase_dia,
):
    """Regras combinadas: cascata, bloqueio global, plantio antes de irrigacao, limpeza pos-plantio.

    min_fase_dia aceita dict {talhao: fase} (per-talhao) ou scalar (global backward compat).
    """
    hh = demanda_global.get((talhao, atv), 0)
    if hh <= 0.01:
        return False
    if usar_bloqueio_global and atv in atividades_bloqueadas:
        if _ha_trabalho_nao_bloqueado(demanda_global, atividades_bloqueadas):
            return False
    if eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
        if not limpeza_permitida_por_talhao(
            talhao, dia, seq_cfg,
            dia_termino_plantio, tem_plantio_por_talhao.get(talhao, False),
        ):
            return False
    if atv in atividades_irrig or _match_filtros_fase(
        atv, seq_cfg.get("filtros_irrigacao") or [], None
    ):
        if _demanda_plantio_talhao(talhao, demanda_global, atividades_plantio):
            return False
    if usar_cascata:
        fv = classificar_fase_cascata_valor(
            atv, seq_cfg, modo, atividades_plantio, atividades_irrig
        )
        mf = min_fase_dia.get(talhao)
        if mf is not None and abs(fv - mf) > 1e-6 and fv > mf + 1e-6:
            return False
    return True


def diagnosticar_sequencia_atividades(atividades_reais, seq_cfg, modo):
    """Avisos: atividades classificadas como 'outras' (fase intermediaria) e lista."""
    ap = set(
        atividades_por_filtro(
            atividades_reais, seq_cfg.get("filtros_plantio") or []
        )
    )
    ai = set(
        atividades_por_filtro(
            atividades_reais, seq_cfg.get("filtros_irrigacao") or []
        )
    )
    outras = []
    for atv in atividades_reais:
        if eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
            continue
        if atv in ap or atv in ai:
            continue
        fases = _fases_ordem_config(seq_cfg, modo)
        ok_fase = False
        for fase in fases:
            if _match_filtros_fase(
                atv, fase.get("filtros") or [], fase.get("exclusoes")
            ):
                ok_fase = True
                break
        if not ok_fase:
            outras.append(atv)
    if outras:
        print(
            DM
            + f"\n  Sequencia ({modo}): {len(outras)} atividade(s) em fase generica 'demais (antes plantio)'."
            + RS
        )
        print(
            DM
            + "  Executam antes de plantio, sem fase fixa na cascata. Para priorizar, adicione filtros em config.sequencia."
            + RS
        )
        for a in sorted(outras, key=str)[:15]:
            print(DM + f"    - {str(a)[:70]}" + RS)
        if len(outras) > 15:
            print(DM + f"    ... +{len(outras) - 15}" + RS)
    else:
        ok("Todas as atividades possuem fase explicita na sequencia.")


# LRU+TTL cache configuration for blocking cache
_HA_NAO_BLOQUEADO_MAXSIZE = 100
_HA_NAO_BLOQUEADO_TTL = 3600  # seconds

# LRU cache: OrderedDict where key = frozenset(bloqueadas), value = (version, result, timestamp)
_ha_nao_bloqueado_cache = OrderedDict()
# Version counter - readable without consuming (list with single element)
_ha_nao_bloqueado_version = [0]


def configure_blocking_cache(maxsize: int = 100, ttl: int = 3600):
    """Configure the blocking cache LRU maxsize and TTL."""
    global _HA_NAO_BLOQUEADO_MAXSIZE, _HA_NAO_BLOQUEADO_TTL, _ha_nao_bloqueado_cache
    _HA_NAO_BLOQUEADO_MAXSIZE = maxsize
    _HA_NAO_BLOQUEADO_TTL = ttl
    # Trim cache if new maxsize is smaller
    while len(_ha_nao_bloqueado_cache) > _HA_NAO_BLOQUEADO_MAXSIZE:
        _ha_nao_bloqueado_cache.popitem(last=False)


def _demanda_global_touch():
    """Increment version for cache invalidation. No lock in hot path."""
    _ha_nao_bloqueado_version[0] += 1


def _cache_expired(ts: float) -> bool:
    """Check if cache entry has expired based on TTL."""
    return (time.time() - ts) > _HA_NAO_BLOQUEADO_TTL


def _ha_trabalho_nao_bloqueado(demanda_global, atividades_bloqueadas):
    """True se ainda existe demanda >0 para atividade fora do grupo bloqueado.

    Uses LRU+TTL cache with version-based invalidation. Zero locks in hot path.
    """
    bloqueadas = set(atividades_bloqueadas or [])
    bkey = frozenset(bloqueadas)
    current_version = _ha_nao_bloqueado_version[0]

    # Check cache - no lock
    cached = _ha_nao_bloqueado_cache.get(bkey)
    if cached is not None:
        ver, result, ts = cached
        if ver == current_version and not _cache_expired(ts):
            # LRU: move to end on hit
            _ha_nao_bloqueado_cache.move_to_end(bkey)
            return result
        # Expired or invalidated - remove
        _ha_nao_bloqueado_cache.pop(bkey, None)

    # Compute result
    for (_, atv), hh in demanda_global.items():
        if hh > 0.01 and atv not in bloqueadas:
            _ha_nao_bloqueado_cache[bkey] = (current_version, True, time.time())
            # Enforce maxsize - LRU eviction
            if len(_ha_nao_bloqueado_cache) > _HA_NAO_BLOQUEADO_MAXSIZE:
                _ha_nao_bloqueado_cache.popitem(last=False)
            return True

    _ha_nao_bloqueado_cache[bkey] = (current_version, False, time.time())
    if len(_ha_nao_bloqueado_cache) > _HA_NAO_BLOQUEADO_MAXSIZE:
        _ha_nao_bloqueado_cache.popitem(last=False)
    return False


def auditar_cadeia_dados(cfg, demandas, atividades_reais, session_hh=None):
    """Auditoria unificada: micro → de_para → tarifa CT → HH/Preço/Custo_hora."""
    tarifas = cfg.get("tarifas", {})
    de_para = cfg.get("de_para", {})
    sem_depara = []
    sem_tarifa = []
    sem_hh = []
    sem_preco = []
    total = 0
    for talhao, lista in demandas.items():
        for t in lista:
            total += 1
            atv = t["atividade"]
            chave = resolver_chave_tarifa(cfg, tarifas, atv)
            if atv not in de_para and atv != chave:
                pass
            elif atv not in de_para and chave == atv and chave not in tarifas:
                sem_depara.append(str(atv)[:55])
            if chave not in tarifas:
                sem_tarifa.append(f"{str(atv)[:40]} → {str(chave)[:40]}")
            else:
                entry = tarifas[chave]
                rh_e = float(entry.get("rendimento_hh", 0) or 0)
                if session_hh and (atv in session_hh or chave in session_hh):
                    rh_e = max(rh_e, 1e-6)
                if rh_e <= 0:
                    sem_hh.append(f"{str(chave)[:55]}")
                if float(entry.get("preco_unit", 0) or 0) <= 0:
                    sem_preco.append(f"{str(chave)[:55]}")
    sub()
    print(G + BL + "  AUDITORIA CADEIA DE DADOS" + RS)
    print(
        G
        + f"  Demandas: {total} | Atividades unicas: {len(atividades_reais)} | de_para: {len(de_para)} | Tarifas CT: {len(tarifas)}"
        + RS
    )
    if session_hh:
        print(
            DM
            + f"  Overrides HH/ha nesta execucao: {len(session_hh)} chave(s) (nao gravados no config)."
            + RS
        )
    if sem_depara:
        u = sorted(set(sem_depara))
        print(Y + f"\n  Sem de_para ({len(u)}) — atividade micro nao mapeada:" + RS)
        for x in u[:10]:
            print(Y + f"    - {x}" + RS)
        if len(u) > 10:
            print(DM + f"    ... +{len(u) - 10}" + RS)
    if sem_tarifa:
        u = sorted(set(sem_tarifa))
        print(
            Y
            + f"\n  Sem tarifa CT ({len(u)}) — chave nao encontrada no orcamento importado:"
            + RS
        )
        for x in u[:10]:
            print(Y + f"    - {x}" + RS)
        if len(u) > 10:
            print(DM + f"    ... +{len(u) - 10}" + RS)
    if sem_hh:
        u = sorted(set(sem_hh))
        print(Y + f"\n  HH zerado ({len(u)}) — rendimento_hh = 0 na tarifa:" + RS)
        for x in u[:10]:
            print(Y + f"    - {x}" + RS)
        if len(u) > 10:
            print(DM + f"    ... +{len(u) - 10}" + RS)
    if sem_preco:
        u = sorted(set(sem_preco))
        print(Y + f"\n  Preco zerado ({len(u)}) — preco_unit = 0 na tarifa:" + RS)
        for x in u[:10]:
            print(Y + f"    - {x}" + RS)
        if len(u) > 10:
            print(DM + f"    ... +{len(u) - 10}" + RS)
    if not sem_depara and not sem_tarifa and not sem_hh and not sem_preco:
        ok("Cadeia de dados completa — nenhuma lacuna detectada.")
    else:
        total_lacunas = (
            len(set(sem_depara))
            + len(set(sem_tarifa))
            + len(set(sem_hh))
            + len(set(sem_preco))
        )
        aviso(
            f"Total de lacunas: {total_lacunas}. Corrija via menu [4] de_para ou [2] importar tarifas."
        )
    sub()




def _somente_bloqueado_restante(demanda_global, atividades_bloqueadas):
    """True se so resta demanda em atividades bloqueadas (ex. plantio/irrigacao)."""
    bloqueadas = set(atividades_bloqueadas or [])
    tem_nao_bloqueado = False
    tem_bloqueado = False
    for (_, atv), hh in demanda_global.items():
        if hh <= 0.01:
            continue
        if atv in bloqueadas:
            tem_bloqueado = True
        else:
            tem_nao_bloqueado = True
    return tem_bloqueado and not tem_nao_bloqueado


def _mostrar_painel_hh_hm_pre_scheduler(demandas, fazenda, detalhado=False, limite=120):
    """
    Painel rapido pre-simulacao com HH/HM por atividade.
    detalhado=False: consolidado por atividade na fazenda.
    detalhado=True: detalhado por talhao + atividade.
    """
    linhas = []
    for talhao, tarefas in (demandas or {}).items():
        for t in tarefas or []:
            area = float(t.get("area", 0) or 0)
            hh_t = float(t.get("hh_total", 0) or 0)
            hm_t = float(t.get("hm_total", 0) or 0)
            atv = str(t.get("atividade", ""))
            tipo = str(t.get("tipo", ""))
            if area <= 0.0001 and hh_t <= 0.0001 and hm_t <= 0.0001:
                continue
            linhas.append(
                {
                    "talhao": str(talhao),
                    "atividade": atv,
                    "area": area,
                    "hh_total": hh_t,
                    "hm_total": hm_t,
                    "tipo": tipo,
                }
            )

    if not linhas:
        return

    if detalhado:
        table = Table(title=f"Pre-voo HH/HM por Talhao - {fazenda}")
        table.add_column("Talhao", style="cyan")
        table.add_column("Atividade", style="green")
        table.add_column("Area(ha)", justify="right")
        table.add_column("HH/ha", justify="right")
        table.add_column("HM/ha", justify="right")
        table.add_column("HH total", justify="right")
        table.add_column("HM total", justify="right")
        table.add_column("Tipo", justify="center")
        rows = sorted(linhas, key=lambda r: (str(r["talhao"]), str(r["atividade"])))
        total = len(rows)
        for i, r in enumerate(rows):
            if i >= limite:
                break
            area = float(r["area"])
            hh_total = float(r["hh_total"])
            hm_total = float(r["hm_total"])
            hh_ha = (hh_total / area) if area > 0.0001 else 0.0
            hm_ha = (hm_total / area) if area > 0.0001 else 0.0
            table.add_row(
                str(r["talhao"]),
                str(r["atividade"])[:38],
                f"{area:.2f}",
                f"{hh_ha:.2f}",
                f"{hm_ha:.2f}",
                f"{hh_total:.2f}",
                f"{hm_total:.2f}",
                str(r["tipo"] or "-"),
            )
        console.print(table)
        if total > limite:
            print(DM + f"  ... +{total - limite} linha(s) detalhadas no total." + RS)
        return

    agg = defaultdict(
        lambda: {
            "area": 0.0,
            "hh_total": 0.0,
            "hm_total": 0.0,
            "tipo": "",
        }
    )
    for r in linhas:
        k = str(r["atividade"])
        agg[k]["area"] += float(r["area"])
        agg[k]["hh_total"] += float(r["hh_total"])
        agg[k]["hm_total"] += float(r["hm_total"])
        if not agg[k]["tipo"]:
            agg[k]["tipo"] = str(r.get("tipo", ""))

    table = Table(title=f"Pre-voo HH/HM por Atividade - {fazenda}")
    table.add_column("Atividade", style="green")
    table.add_column("Area(ha)", justify="right")
    table.add_column("HH/ha", justify="right")
    table.add_column("HM/ha", justify="right")
    table.add_column("HH total", justify="right")
    table.add_column("HM total", justify="right")
    table.add_column("Tipo", justify="center")

    rows = sorted(agg.items(), key=lambda kv: str(kv[0]))
    total = len(rows)
    for i, (atv, dados) in enumerate(rows):
        if i >= limite:
            break
        area = float(dados["area"])
        hh_total = float(dados["hh_total"])
        hm_total = float(dados["hm_total"])
        hh_ha = (hh_total / area) if area > 0.0001 else 0.0
        hm_ha = (hm_total / area) if area > 0.0001 else 0.0
        table.add_row(
            str(atv)[:42],
            f"{area:.2f}",
            f"{hh_ha:.2f}",
            f"{hm_ha:.2f}",
            f"{hh_total:.2f}",
            f"{hm_total:.2f}",
            str(dados.get("tipo", "") or "-"),
        )
    console.print(table)
    if total > limite:
        print(DM + f"  ... +{total - limite} atividade(s) no total." + RS)


def menu_ajustes_hh_apenas_sessao(atividades_reais, cfg, session_hh):
    """Edita HH/ha por atividade apenas na memoria (nao salva config.json)."""
    if session_hh is None:
        return
    tarifas = cfg.get("tarifas", {})
    strict = cfg.get("orcamento_estrito", True)
    sub()
    print(G + BL + "  AJUSTE DE HH/ha — APENAS ESTA EXECUCAO" + RS)
    print(DM + "  Nao grava em config. ENTER = manter valor atual." + RS + "\n")
    n = 0
    n_skip_mec_hm = 0
    for atv in sorted(set(atividades_reais), key=str):
        t_nome = resolver_chave_tarifa(cfg, tarifas, atv)
        row_tarifa = tarifas.get(t_nome, {})
        if not isinstance(row_tarifa, dict):
            row_tarifa = {}
        tipo = str(row_tarifa.get("tipo", "")).lower()
        try:
            hm = float(row_tarifa.get("rendimento_hm", 0) or 0)
        except (TypeError, ValueError):
            hm = 0.0
        if "mecaniz" in tipo or hm > 0:
            n_skip_mec_hm += 1
            continue
        cur = resolver_rendimento_hh(
            cfg, tarifas, t_nome, strict=strict, session_hh=session_hh, atv_micro=atv
        )
        if cur is None:
            cur = 0.0
        v = prompt(f"  [{str(atv)[:46]}]  CT:{str(t_nome)[:36]}  HH/ha [{cur}]", "")
        vs = str(v).strip()
        if not vs:
            continue
        try:
            nv = float(vs.replace(",", "."))
            session_hh[atv] = nv
            session_hh[t_nome] = nv
            n += 1
        except (TypeError, ValueError):
            aviso("Valor invalido, ignorado.")
    if n:
        ok(f"{n} override(s) HH/ha nesta sessao.")
    else:
        print(DM + "  Nenhum override informado." + RS)
    if n_skip_mec_hm:
        print(
            DM
            + f"  {n_skip_mec_hm} atividade(s) HM-only/mecanizadas foram ocultadas deste ajuste de HH."
            + RS
        )


def validar_e_completar_orcamento(cfg, atividades_reais, session_hh=None):
    """
    Modo orcamento_estrito: toda atividade do micro precisa de chave em tarifas com dados CT.
    Lacunas: escolher tarifa na lista ou informar HH/preco/custo manualmente.
    session_hh: dict opcional; HH informado para linha zerada pode ir apenas para a sessao (nao grava tarifas).
    Retorna False se usuario abortar.
    """
    if not cfg.get("orcamento_estrito", True):
        return True
    tarifas = cfg.setdefault("tarifas", {})
    de_para = cfg.setdefault("de_para", {})
    nomes_tarifa = sorted(tarifas.keys(), key=str)
    if not nomes_tarifa:
        erro("Nenhuma tarifa em config. Normalize a CT [3] ou importe [2].")
        return False

    for atv in sorted(set(atividades_reais), key=str):
        t_nome = resolver_chave_tarifa(cfg, tarifas, atv)
        if t_nome not in tarifas:
            sub()
            print(Y + "  [ESTRITO] Sem tarifa CT para atividade do micro:" + RS)
            print(Y + f"    {str(atv)[:70]}" + RS)
            print(DM + f"    Chave atual: {t_nome}" + RS)
            if confirmar(
                "  Escolher uma linha existente em tarifas (recomendado)?", default=True
            ):
                idx = selecionar_paginado(
                    "TARIFA CT (orcamento)", nomes_tarifa, page_size=8
                )
                if idx < 0:
                    return False
                de_para[atv] = nomes_tarifa[idx]
                salvar_config(cfg)
            else:
                hh_m = pedir_float("  HH/ha (manual)", 8.0)
                pr_m = pedir_float("  Preco R$/ha (manual)", 0.0, allow_zero=True)
                ch_m = pedir_float(
                    "  Custo R$/h (manual)",
                    float(cfg.get("custo_hora_tf") or 50),
                    allow_zero=True,
                )
                chave = prompt(
                    "  Nome da chave a gravar em tarifas (ex.: alias)", t_nome[:48]
                )
                if not chave:
                    chave = t_nome
                tarifas[chave] = {
                    "rendimento_hh": hh_m,
                    "preco_ha": pr_m,
                    "preco_unit": pr_m,
                    "custo_hora": ch_m,
                    "custo_ha": hh_m * ch_m if ch_m > 0 else 0,
                    "tipo": "Manual",
                    "recurso": "homem",
                    "eficiencia": 1.0,
                }
                de_para[atv] = chave
                salvar_config(cfg)
        t_nome = resolver_chave_tarifa(cfg, tarifas, atv)
        row = tarifas.get(t_nome, {})
        try:
            rh = float(row.get("rendimento_hh", 0))
        except (TypeError, ValueError):
            rh = 0.0
        tipo = str(row.get("tipo", "")).lower()
        hm = float(row.get("rendimento_hm", 0) or 0)
        is_mec = "mecaniz" in tipo or hm > 0
        if rh <= 0.01 and not is_mec:
            sub()
            print(
                Y
                + f"  [ESTRITO] rendimento_hh zero ou invalido na tarifa '{str(t_nome)[:50]}'"
                + RS
            )
            hh_m = pedir_float(
                "  Informe HH/ha para esta linha (ou 0 se so maquina)",
                0.0,
                allow_zero=True,
            )
            if session_hh is not None and confirmar(
                "  Aplicar SO nesta execucao (nao gravar em config.json)?", default=True
            ):
                session_hh[atv] = float(hh_m)
                session_hh[t_nome] = float(hh_m)
            else:
                tarifas[t_nome]["rendimento_hh"] = float(hh_m)
                salvar_config(cfg)
    return True


# ──────────────────────────────────────────────
#  SMART SCHEDULER v2:
#  Filas por TURMA, sequenciais por talhao.
#  Atividades podem ser paralelas (varias turmas) ou exclusivas (uma turma).
#  Reatribuicao: qualquer atividade pode ser executada por qualquer turma.
# ──────────────────────────────────────────────
def dias_uteis_no_periodo(mes_ini, ano_ini, meses):
    dias = 0
    m, a = mes_ini, ano_ini
    for _ in range(int(math.ceil(meses))):
        for sem in calendar.monthcalendar(a, m):
            for i, d in enumerate(sem):
                if d != 0 and i < 5:
                    dias += 1
        m += 1
        if m > 12:
            m = 1
            a += 1
    return dias

def _configurar_sequencia_personalizada(atividades_reais, seq_cfg):
    """Interactive personalizado sequence builder.

    User defines ordered groups (cascade phases):
    - Activities in the SAME group run in parallel (no cascade constraint between them)
    - Groups run sequentially (group N+1 only starts after group N finishes per-talhao)
    Uses existing 1,3,5 input style for activity selection.
    """
    subcabecalho("SEQUENCIA PERSONALIZADA")
    if not atividades_reais:
        aviso("Nenhuma atividade disponivel para configurar sequencia.")
        return

    atv_list = sorted(atividades_reais, key=str)
    print(G + BL + "\n Atividades disponiveis no micro:" + RS)
    for i, a in enumerate(atv_list, 1):
        print(C + f"  {i:3d}. {str(a)[:60]}" + RS)

    print(DM + "\n Defina grupos sequenciais (fases da cascata):" + RS)
    print(DM + " - Atividades no MESMO grupo rodam em paralelo" + RS)
    print(DM + " - Grupos rodam em sequencia (grupo N+1 so inicia quando N terminar)" + RS)
    print(DM + " - Use formato 1,3,5 ou intervalos 1-5 para selecionar" + RS)

    grupos = []
    num_grupo = 1
    ids_usados = set()

    while True:
        restantes = [a for i, a in enumerate(atv_list, 1) if i not in ids_usados]
        if not restantes:
            ok("Todas as atividades foram alocadas!")
            break

        print(G + f"\n Grupo {num_grupo}:" + RS)
        if ids_usados:
            print(DM + f" Restantes: {len(restantes)} atividade(s)" + RS)
            for i, a in enumerate(atv_list, 1):
                if i not in ids_usados:
                    print(C + f"  {i:3d}. {str(a)[:60]}" + RS)

        resp = prompt(
            f"Atividades do grupo {num_grupo} (1,3,5 ou 1-5, ENTER=finalizar)",
            "",
        )
        if not resp.strip():
            if num_grupo == 1:
                aviso("Pelo menos um grupo deve ser definido.")
                continue
            break

        indices = _parse_indices_usuario(resp, len(atv_list))
        if not indices:
            aviso("Nenhum indice valido. Use formato 1,3,5 ou 1-5.")
            continue

        novos = [i for i in indices if i not in ids_usados]
        if not novos:
            aviso("Todos os indices selecionados ja foram alocados.")
            continue

        filtros_grupo = []
        nomes_grupo = []
        for idx in novos:
            atv = atv_list[idx - 1]
            filtros_grupo.append(str(atv))
            nomes_grupo.append(str(atv)[:30])
            ids_usados.add(idx)

        grupo_id = f"grupo_{num_grupo}"
        grupos.append({
            "id": grupo_id,
            "filtros": filtros_grupo,
            "exclusoes": [],
        })

        print(G + f" Grupo {num_grupo}: {', '.join(nomes_grupo)}" + RS)
        num_grupo += 1

    if not grupos:
        return

    seq_cfg["personalizado_ordem"] = grupos
    seq_cfg["modo"] = "personalizado"

    print(G + BL + "\n Ordem definida:" + RS)
    for i, g in enumerate(grupos, 1):
        nomes = [f[:35] for f in g["filtros"]]
        print(G + f" Fase {i}: " + C + ", ".join(nomes) + RS)

    if len(grupos) == 1:
        print(DM + " Apenas 1 grupo — sem restricao de cascata (tudo paralelo)." + RS)


def _parse_indices_usuario(texto, max_idx):
    """Parse '1,3,5' or '1-5' style input into list of 1-based indices."""
    resultado = set()
    try:
        for parte in texto.replace(" ", "").split(","):
            parte = parte.strip()
            if not parte:
                continue
            if "-" in parte:
                limits = parte.split("-", 1)
                a, b = int(limits[0]), int(limits[1])
                for i in range(min(a, b), max(a, b) + 1):
                    if 1 <= i <= max_idx:
                        resultado.add(i)
            else:
                i = int(parte)
                if 1 <= i <= max_idx:
                    resultado.add(i)
    except (ValueError, IndexError):
        return []
    return sorted(resultado)


def _selecionar_sequencia_padrao_sn(cfg, seq_cfg, atividades_reais=None):
    sub()
    print(G + BL + "  SELECIONAR SEQUENCIA PADRAO:" + RS)
    print(DM + "  Responda S para a sequencia desejada (apenas UMA):" + RS + "\n")
    escolhido = None
    for modo_id, descr in _SEQUENCIAS_DISPONIVEIS:
        resp = confirmar(
            f"  {modo_id}: {descr}",
            default=(modo_id == seq_cfg.get("modo", "implantacao")),
        )
        if resp:
            escolhido = modo_id
            break
    if not escolhido:
        aviso("Nenhuma sequencia selecionada. Repetindo...")
        return _selecionar_sequencia_padrao_sn(cfg, seq_cfg, atividades_reais)
    seq_cfg["modo"] = escolhido
    ok(f"Sequencia: {escolhido}")
    if escolhido == "personalizado" and atividades_reais:
        _configurar_sequencia_personalizada(atividades_reais, seq_cfg)
    if confirmar(" Salvar como padrao para proximas execucoes?", default=True):
        cfg["sequencia"] = seq_cfg
        salvar_config(cfg)
    return escolhido



def _distribuir_atividades_faltantes_turmas(turmas, atividades_reais, fazenda):
    """
    Atribui à turma mais numerosa as atividades da fazenda que não entraram no template
    (ex.: equipe só irrigação em micro sem irrigação — evita cronograma vazio).
    """
    if not turmas or not atividades_reais:
        return
    cobertura = set()
    for t in turmas:
        for a in t.get("atividades") or []:
            na = _norm_atv(a)
            if na:
                cobertura.add(na)
    farm_set = set(atividades_reais)
    orfas = [a for a in atividades_reais if a not in cobertura]
    if not orfas:
        return
    tpl_extra = sorted(cobertura - farm_set, key=str)
    if tpl_extra:
        print(
            DM
            + f"  Modelo de turmas: {len(tpl_extra)} atividade(s) sem demanda nesta fazenda "
            + f"('{str(fazenda)[:42]}') — ignoradas no micro atual."
            + RS
        )
        for x in tpl_extra[:5]:
            print(DM + f"    ~ {str(x)[:58]}" + RS)
        if len(tpl_extra) > 5:
            print(DM + f"    ... +{len(tpl_extra) - 5}" + RS)
    alvo = max(turmas, key=lambda t: int(t.get("operarios", 0) or 0))
    cur = {_norm_atv(x) for x in alvo.get("atividades", []) if _norm_atv(x)}
    cur |= set(orfas)
    alvo["atividades"] = sorted(cur, key=str)
    ok(
        f"{len(orfas)} atividade(s) desta fazenda sem turma no modelo foram atribuidas a '{alvo['nome']}' "
        f"(evita cronograma vazio quando o template nao cruza o micro)."
    )

