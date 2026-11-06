"""Engine do scheduler — loop principal, cálculo de demandas e filas.

Extraido verbatim de scheduler_core.py (decomposição do god module).
As funções são IDÊNTICAS ao original; apenas mudaram de endereço.
scheduler_core importa daqui para preservar a API pública.

Não contém lógica nova: é mudança de endereço, não reescrita.
"""

from __future__ import annotations

import calendar
import datetime
import io
import math
import os
import traceback
from collections import defaultdict
from dataclasses import dataclass
from contextlib import redirect_stderr, redirect_stdout

import pandas as pd

from ..comparativo_config import _configurar_modo_comparativo
from ..comparativo_mec import (
    _atividades_com_mecanizado_disponivel,
    _cadastrar_recurso_mecanizado_externo,
    _clonar_cfg_comparativo_mecanizado,
    _formatar_substituicao_comparativo,
    _substituir_por_mecanizado,
    coletar_config_comparativo_multifator,
    simular_cenarios_multifator,
)
from ..config import (
    OUTPUT_DIR,
    _agrupar_fazendas_por_empresa,
    _detectar_cidade_por_fazenda,
    _distribuir_fazendas_por_territorio,
    _merge_sequencia_defaults,
    _sugerir_config_empresa,
    modo_somente_hh,
    salvar_config,
)
from ..constants import CT317_HARDCODE_HH_BASE
from ..context import contexto_sessao, dashboard_header
from ..cronograma import (
    construir_cronograma_humano_sem_mecanizadas,
    construir_cronograma_mecanizado,
    construir_cronograma_mecanizado_auto_hm_tarifa,
)
from ..datas import _calcular_data_fim_por_meses, _formatar_data_dia
from ..de_para import aplicar_depara_padrao_exame, auto_mapear_de_para
from ..domain.scope import (
    _menu_ajustar_escopo_atividades,
    _proximo_caminho_livre,
)
from ..domain.terrain import avaliar_terreno
from ..excel_export import (
    _aplicar_cores_ocupacao_excel,
    _carregar_perfil_equipe_menu,
    _checkpoint_editar_template,
    _df_crono_operacional,
    _exportar_excel_consolidado_lote,
    _gerar_aba_cascata_explicada,
    _gerar_aba_ocupacao_turmas,
    _imprimir_recomendacao_ep,
    _listar_perfis_equipe,
    _recomendar_equipes_padrao,
    _salvar_perfil_equipe,
)
from ..monitor import (
    _emitir_monitor_atual,
    _emitir_monitor_relatorio,
    _emitir_monitor_state,
    _monitor_build_rendimentos,
)
from ..text_utils import (
    _norm_atv,
    _slug_ficheiro_seguro,
    atividades_por_filtro,
    normalizar_chave,
    parse_intervalos_escolha,
)
from ..scheduler import (
    _demanda_global_touch,
    _ha_nao_bloqueado_version,
    _demanda_plantio_talhao,
    _distribuir_atividades_faltantes_turmas,
    _min_fase_cascata_por_talhao,
    _mostrar_painel_hh_hm_pre_scheduler,
    _selecionar_sequencia_padrao_sn,
    _somente_bloqueado_restante,
    auditar_cadeia_dados,
    classificar_fase_cascata_valor,
    diagnosticar_sequencia_atividades,
    dias_uteis_no_periodo,
    menu_ajustes_hh_apenas_sessao,
    pode_agendar_atividade_cascata,
    validar_e_completar_orcamento,
)
from ..tarifas import (
    aviso_politica_tarifas_planas,
    resolver_chave_tarifa,
    resolver_custo_hora,
    resolver_rendimento_hh,
    resolver_rendimento_hm,
)
from ..text_utils import (
    _norm_atv,
    _slug_ficheiro_seguro,
    atividades_por_filtro,
    normalizar_chave,
    parse_intervalos_escolha,
)
from ..turmas import (
    _cadastrar_recursos_mecanizados_sn,
    _catalogo_atividades_completo,
    menu_vincular_atividades_turma,
    resolver_conflitos_e_reatribuir,
    sequencia_manutencao_seco_placeholder,
    sequencia_manutencao_umido_placeholder,
    turmas_que_executam,
)
from ..ui import (
    BL,
    DM,
    RS,
    C,
    G,
    R,
    Table,
    Y,
    aviso,
    confirmar,
    console,
    erro,
    escolha,
    esperar,
    linha,
    ok,
    pedir_float,
    pedir_int,
    pedir_jornada,
    prompt,
    selecionar,
    selecionar_paginado,
    sub,
    subcabecalho,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # só anotação: scheduler_core importa engine no topo (import ao contrario daria ciclo)
    from ..scheduler_core import _SchedulerLoopConfig

_HH_EPSILON = 0.01
DIAS_UTEIS_POR_MES = 22.0
_JORNADA_DEFAULT_H = 4.6


def _validar_input(df_faz):
    _colunas_obrigatorias = ["fazenda", "atividade", "area_ha"]
    _faltando = [c for c in _colunas_obrigatorias if c not in df_faz.columns]
    if _faltando:
        erro(f"Colunas obrigatorias ausentes no micro: {', '.join(_faltando)}")
        return "colunas", None
    _areas_neg = df_faz[df_faz["area_ha"].astype(float) < 0]
    if not _areas_neg.empty:
        aviso(f"{len(_areas_neg)} talhao(oes) com area_ha negativa — serao zerados")
        df_faz.loc[_areas_neg.index, "area_ha"] = 0.0
    return None, df_faz


def _construir_demandas(talhoes_ordenados, df_faz, cfg, tarifas, strict, session_hh, modo_somente_hh, atividades_reais):
    demandas = {}
    total_hh = 0.0
    total_hm = 0.0
    total_custo = 0.0
    hm_only_atividades = set()
    fallback_hh_items = []

    for talhao in talhoes_ordenados:
        df_t = df_faz[df_faz["chave"] == talhao]
        tarefas = []
        for _, row in df_t.iterrows():
            atv = row["atividade"]
            try:
                area = float(row["area_ha"])
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Valor invalido para area_ha no talhao '{talhao}' "
                    f"atividade '{atv}': {row['area_ha']!r}"
                ) from exc
            try:
                pen = float(row["penalidade"])
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Valor invalido para penalidade no talhao '{talhao}' "
                    f"atividade '{atv}': {row['penalidade']!r}"
                ) from exc

            t_nome = resolver_chave_tarifa(cfg, tarifas, atv)
            rend_base = resolver_rendimento_hh(
                cfg,
                tarifas,
                t_nome,
                strict=strict,
                session_hh=session_hh,
                atv_micro=atv,
            )
            hm_base = resolver_rendimento_hm(cfg, tarifas, t_nome, strict=strict)
            if rend_base is None:
                if float(hm_base or 0) > 0.0:
                    rend_base = 0.0
                    fallback_hh_items.append((str(atv), str(t_nome), "HM-only => HH=0"))
                else:
                    rend_fb = resolver_rendimento_hh(
                        cfg,
                        tarifas,
                        t_nome,
                        strict=False,
                        session_hh=session_hh,
                        atv_micro=atv,
                    )
                    if rend_fb is None:
                        rend_fb = 0.0
                    rend_base = float(rend_fb)
                    fallback_hh_items.append(
                        (str(atv), str(t_nome), f"fallback HH={float(rend_base):.2f}")
                    )
            rend_hh_ha = float(rend_base) * pen
            hm_ha = float(hm_base) * pen
            in_tarifa = t_nome in tarifas

            horas = area * rend_hh_ha
            hm_horas = area * hm_ha
            custo_h = resolver_custo_hora(cfg, tarifas, t_nome) or 0.0
            custo_task = horas * custo_h
            total_hh += horas
            total_hm += hm_horas
            total_custo += custo_task

            tarifa_row = tarifas.get(t_nome, {})
            tipo_tarifa = str(tarifa_row.get("tipo", "")).lower()
            is_mec = "mecaniz" in tipo_tarifa or (hm_ha > 0 and rend_hh_ha <= 0)
            if is_mec and rend_hh_ha <= 0 and hm_ha > 0:
                hm_only_atividades.add(str(atv))

            if strict:
                origem_linha = "CT"
                rfonte = "CT"
            else:
                origem_linha = "tarifa" if in_tarifa else "fallback"
                rfonte = "CT" if in_tarifa else "estimado"
            tarefas.append(
                {
                    "atividade": atv,
                    "area": area,
                    "hh_total": horas,
                    "hm_ha": hm_ha,
                    "hm_total": hm_horas,
                    "custo_hora": custo_h,
                    "custo_total": custo_task,
                    "chave_tarifa": t_nome,
                    "origem": origem_linha,
                    "rendimento_fonte": rfonte,
                    "tipo": "Mecanizada" if is_mec else "Manual",
                }
            )
        demandas[talhao] = tarefas

    print(DM + f"\n  Total HH da fazenda (bruto): {total_hh:.1f} horas-homem" + RS)
    print(DM + f"  Total HM da fazenda (bruto): {total_hm:.1f} horas-maquina" + RS)
    if not modo_somente_hh(cfg):
        print(DM + f" Custo MO total (bruto): R$ {total_custo:,.2f}" + RS)
    if total_hm > _HH_EPSILON:
        print(
            DM
            + "  Regra de fluxo HM-only: atividades mecanizadas rodam em paralelo e a equipe humana"
            + " continua o fluxo sem esperar 100% da maquina."
            + RS
        )
    if fallback_hh_items:
        print(
            Y
            + f"  Fallback HH aplicado em {len(fallback_hh_items)} item(ns) do escopo."
            + RS
        )
        for atv_fb, t_fb, motivo_fb in fallback_hh_items[:5]:
            print(
                Y
                + f"    - {str(atv_fb)[:44]} | CT:{str(t_fb)[:30]} | {str(motivo_fb)[:24]}"
                + RS
            )
        if len(fallback_hh_items) > 5:
            print(Y + f"    ... +{len(fallback_hh_items) - 5}" + RS)

    auditar_cadeia_dados(cfg, demandas, atividades_reais, session_hh=session_hh)
    return {
        "demandas": demandas,
        "total_hh": total_hh,
        "total_hm": total_hm,
        "total_custo": total_custo,
        "hm_only_atividades": hm_only_atividades,
        "fallback_hh_items": fallback_hh_items,
    }


def _executar_scheduler_loop(config: _SchedulerLoopConfig):
    # Work on a copy to avoid mutating the input
    demanda_global = config.demanda_global.copy()

    cronograma = []
    dia = 0
    MAX_DIAS = 10000
    def _registrar_fim_plantio_talhao(th, dia_atual):
        if config.dia_termino_plantio.get(th) is not None:
            return
        if not _demanda_plantio_talhao(th, demanda_global, config.atividades_plantio):
            config.dia_termino_plantio[th] = dia_atual

    def _crono(dia, talhao, atv, turma, operarios, consumo, modo=None):
        custo = consumo * resolver_custo_hora(config.cfg, config.tarifas, resolver_chave_tarifa(config.cfg, config.tarifas, atv)) if not config.modo_somente_hh(config.cfg) else 0.0
        e = {
            "Dia": dia, "Fazenda": config.fazenda, "Talhao": talhao, "Atividade": atv,
            "Turma": turma, "Operarios": operarios, "HH": round(consumo, 2), "Custo_MO": custo,
        }
        if modo:
            e["Modo"] = modo
        cronograma.append(e)

    while dia < MAX_DIAS:
        tem_trabalho = any(v > _HH_EPSILON for v in demanda_global.values())
        if not tem_trabalho:
            break

        dia += 1
        restante = sum(1 for v in demanda_global.values() if v > _HH_EPSILON)
        if dia % 100 == 0 or dia == 1:
            print(DM + f"  dia {dia}/{MAX_DIAS} ({restante} demandas restantes)" + RS, end="\r")
        cache_gate_dia = {}

        def _pode_agendar_cacheado(talhao, atv):
            chave = (talhao, atv, _ha_nao_bloqueado_version[0])
            cached = cache_gate_dia.get(chave)
            if cached is not None:
                return cached
            resultado = pode_agendar_atividade_cascata(
                talhao, atv, demanda_global, config.seq_cfg, config.modo_seq,
                config.usar_cascata, config.usar_bloqueio_global,
                config.atividades_bloqueadas, config.atividades_plantio,
                config.atividades_irrig, dia, config.dia_termino_plantio,
                config.tem_plantio_por_talhao, min_fase_dia,
            )
            cache_gate_dia[chave] = resultado
            return resultado

        min_fase_dia_dict = _min_fase_cascata_por_talhao(
            demanda_global, config.seq_cfg, config.modo_seq, config.usar_cascata,
            config.usar_bloqueio_global, config.atividades_bloqueadas,
            config.atividades_plantio, config.atividades_irrig,
            dia, config.dia_termino_plantio, config.tem_plantio_por_talhao,
        )
        min_fase_dia = min_fase_dia_dict
        pool_only = (
            config.usar_bloqueio_global
            and config.usar_pool_pos_bloqueio
            and _somente_bloqueado_restante(demanda_global, config.atividades_bloqueadas)
        )
        if pool_only:
            cap_pool = float(config.executores) * float(config.jornada)
            while cap_pool > _HH_EPSILON:
                fez = False
                for talhao in config.talhoes_ordenados:
                    tlist = list(config.demandas.get(talhao, []))
                    tlist.sort(
                        key=lambda t: (
                            0
                            if t["atividade"] in config.atividades_plantio
                            else (1 if t["atividade"] in config.atividades_irrig else 2),
                            str(t["atividade"]),
                        )
                    )
                    for t in tlist:
                        atv = t["atividade"]
                        if atv not in config.atividades_bloqueadas:
                            continue
                        key = (talhao, atv)
                        rest = demanda_global.get(key, 0.0)
                        if rest <= _HH_EPSILON:
                            continue
                        if not _pode_agendar_cacheado(talhao, atv):
                            continue
                        consumo = min(rest, cap_pool)
                        demanda_global[key] -= consumo
                        _demanda_global_touch()
                        cap_pool -= consumo
                        fez = True
                        _registrar_fim_plantio_talhao(talhao, dia)
                        _crono(dia, talhao, atv, "Pelotao_Unificado", config.executores, consumo, modo="PoolPosBloqueio")
                        if cap_pool <= _HH_EPSILON:
                            break
                    if cap_pool <= _HH_EPSILON:
                        break
                if not fez:
                    break
            for turma in config.turmas:
                fila = config.turma_filas[turma["nome"]]
                while (
                    fila
                    and demanda_global.get((fila[0]["talhao"], fila[0]["atividade"]), 0)
                    < _HH_EPSILON
                ):
                    fila.pop(0)
            continue

        for turma in config.turmas:
            fila = config.turma_filas[turma["nome"]]
            n_ops = turma["operarios"]
            cap_dia = n_ops * config.jornada

            idx = 0
            while cap_dia > _HH_EPSILON and idx < len(fila):
                item = fila[idx]
                key = (item["talhao"], item["atividade"])
                rest = demanda_global.get(key, 0)

                if rest < _HH_EPSILON:
                    idx += 1
                    continue

                if not _pode_agendar_cacheado(item["talhao"], item["atividade"]):
                    idx += 1
                    continue

                consumo = min(rest, cap_dia)
                demanda_global[key] -= consumo
                _demanda_global_touch()
                cap_dia -= consumo
                _registrar_fim_plantio_talhao(item["talhao"], dia)

                _crono(dia, item["talhao"], item["atividade"], turma["nome"], n_ops, consumo)

                if demanda_global[key] < _HH_EPSILON:
                    idx += 1

            while (
                fila
                and demanda_global.get((fila[0]["talhao"], fila[0]["atividade"]), 0)
                < _HH_EPSILON
            ):
                fila.pop(0)

            if config.usar_reforco_automatico and cap_dia > _HH_EPSILON:
                for talhao in config.talhoes_ordenados:
                    if cap_dia <= _HH_EPSILON:
                        break
                    tarefas_t = list(config.demandas.get(talhao, []))
                    if config.usar_cascata:
                        tarefas_t.sort(
                            key=lambda t: (
                                classificar_fase_cascata_valor(
                                    t["atividade"],
                                    config.seq_cfg,
                                    config.modo_seq,
                                    config.atividades_plantio,
                                    config.atividades_irrig,
                                ),
                                str(t["atividade"]),
                            )
                        )
                    for t in tarefas_t:
                        atv = t["atividade"]
                        key_ref = (talhao, atv)
                        rest_ref = demanda_global.get(key_ref, 0.0)
                        if rest_ref <= _HH_EPSILON:
                            continue
                        if not _pode_agendar_cacheado(talhao, atv):
                            continue
                        consumo_ref = min(rest_ref, cap_dia)
                        if consumo_ref <= _HH_EPSILON:
                            continue
                        demanda_global[key_ref] -= consumo_ref
                        _demanda_global_touch()
                        cap_dia -= consumo_ref
                        _registrar_fim_plantio_talhao(talhao, dia)
                        _crono(dia, talhao, atv, turma["nome"], n_ops, consumo_ref, modo="Reforco")

    return cronograma, dia, demanda_global


def _verificar_atividades_sem_tarifa(demandas, cfg, tarifas, strict):
    sem_tarifa = []
    for talhao, tarefas in demandas.items():
        for t in tarefas:
            atv = t["atividade"]
            t_nome = resolver_chave_tarifa(cfg, tarifas, atv)
            if t_nome not in tarifas:
                sem_tarifa.append((str(atv)[:50], str(t_nome)[:50]))
    if not strict and sem_tarifa:
        est_fb = resolver_rendimento_hh(
            cfg, tarifas, "!__chave_inexistente__!", strict=False
        )
        print(
            Y
            + "\n  !  Chave de tarifa NAO encontrada no orcamento importado (desencontro de nome)."
            + RS
        )
        print(
            Y
            + f"     Rendimento estimado aplicado: ~{est_fb:.2f} h/ha (mediana/config; ver doc)."
            + RS
        )
        visto = set()
        for a, tn in sem_tarifa:
            key = (a, tn)
            if key in visto:
                continue
            visto.add(key)
            print(Y + f"    micro: {a}  ->  chave buscada: {tn}" + RS)
        print(
            DM
            + "    Correcao: menu [4] de_para ou importe tarifas [2] — no orcamento o homem/ha existe."
            + RS
        )


def _mostrar_tabela_semanal_lazy(cronograma_base, fazenda, executores):
    """Wrapper lazy: _mostrar_tabela_semanal vive em scheduler_core (import ao contrario daria ciclo)."""
    from ..scheduler_core import _mostrar_tabela_semanal
    return _mostrar_tabela_semanal(cronograma_base, fazenda, executores)


def _merge_cronograma_base_e_metricas(hm_only_atividades, demandas, cronograma, fazenda, jornada, cfg, tarifas, dia, mes_ref, ano_ref, prazo_meses, total_hh, executores):
    hm_only_list = sorted(hm_only_atividades, key=str)
    cronograma_mec_base = []
    if hm_only_list:
        cronograma_mec_base, _ = construir_cronograma_mecanizado_auto_hm_tarifa(
            demandas, fazenda, jornada, cfg, tarifas, atividades_alvo=hm_only_list,
        )
        if cronograma_mec_base:
            ok(f"Cronograma base incluiu {len(cronograma_mec_base)} linha(s) mecanizadas (HM do orcamento).")

    cronograma_base = sorted(
        cronograma + cronograma_mec_base,
        key=lambda r: (int(r.get("Dia", 0)), str(r.get("Turma", ""))),
    )

    dias_simulado_hum = dia
    if dia > 1:
        print()
    d_mec_base = max([int(x.get("Dia", 0)) for x in cronograma_mec_base], default=0)
    dias_simulado = max(dias_simulado_hum, d_mec_base)

    dias_meta = dias_uteis_no_periodo(mes_ref, ano_ref, prazo_meses)
    meses_simulado = dias_simulado / DIAS_UTEIS_POR_MES if dias_simulado > 0 else 0

    _mostrar_tabela_semanal_lazy(cronograma_base, fazenda, executores)

    hh_por_turma = defaultdict(float)
    for c in cronograma:
        hh_por_turma[c["Turma"]] += float(c["HH"])

    n_demandas = sum(1 for tarefas in demandas.values() for t in tarefas)
    n_fb = sum(1 for tarefas in demandas.values() for t in tarefas if t.get("origem") == "fallback")
    pct_fallback = (100.0 * n_fb / n_demandas) if n_demandas > 0 else 0.0

    return cronograma_base, dias_simulado_hum, dias_simulado, dias_meta, \
        meses_simulado, hh_por_turma, n_demandas, n_fb, pct_fallback, \
        hm_only_list, cronograma_mec_base


def _construir_filas_e_demanda_global(turmas, talhoes_ordenados, demandas, reatribuicao, paralelo, primaria, atividades_reais, seq_cfg, modo_seq, usar_cascata):
    turma_filas = {}
    for turma in turmas:
        fila = []
        for talhao in talhoes_ordenados:
            for tarefa in demandas.get(talhao, []):
                atv = tarefa["atividade"]
                if tarefa["hh_total"] > _HH_EPSILON and turma["nome"] in turmas_que_executam(
                    atv, turmas, reatribuicao, paralelo, primaria
                ):
                    fila.append(
                        {
                            "talhao": talhao,
                            "atividade": atv,
                            "hh_rest": tarefa["hh_total"],
                        }
                    )
        turma_filas[turma["nome"]] = fila

    demanda_global = {}
    for talhao, tarefas in demandas.items():
        for t in tarefas:
            demanda_global[(talhao, t["atividade"])] = t["hh_total"]

    atividades_plantio = set(
        atividades_por_filtro(
            atividades_reais, seq_cfg.get("filtros_plantio") or ["plantio"]
        )
    )
    atividades_irrig = set(
        atividades_por_filtro(
            atividades_reais, seq_cfg.get("filtros_irrigacao") or ["irrig"]
        )
    )
    tem_plantio_por_talhao = {}
    for th in talhoes_ordenados:
        tem_plantio_por_talhao[th] = any(
            t["atividade"] in atividades_plantio and t["hh_total"] > _HH_EPSILON
            for t in demandas.get(th, [])
        )

    if usar_cascata:
        for _tn, fila in turma_filas.items():
            fila.sort(
                key=lambda x: (
                    classificar_fase_cascata_valor(
                        x["atividade"],
                        seq_cfg,
                        modo_seq,
                        atividades_plantio,
                        atividades_irrig,
                    ),
                    str(x["talhao"]),
                    str(x["atividade"]),
                )
            )

    return turma_filas, demanda_global, atividades_plantio, atividades_irrig, tem_plantio_por_talhao


def _verificar_atividades_sem_executor(demandas, turmas, reatribuicao, paralelo, primaria, _batch, cfg):
    sem_executor = []
    for talhao, tarefas in demandas.items():
        for t in tarefas:
            if t["hh_total"] < _HH_EPSILON:
                continue
            atv = t["atividade"]
            if not turmas_que_executam(atv, turmas, reatribuicao, paralelo, primaria):
                sem_executor.append(atv)
    if sem_executor:
        print(R + "\n  X  Atividades com demanda mas SEM turma executora:" + RS)
        for a in sorted(set(str(x) for x in sem_executor))[:15]:
            print(R + f"    - {a[:58]}" + RS)
        if len(set(sem_executor)) > 15:
            print(DM + f"    ... +{len(set(sem_executor)) - 15}" + RS)
        continuar_sem_executor = True
        if _batch:
            aviso("Modo batch: HH sem turma executora serao zeradas automaticamente.")
        else:
            continuar_sem_executor = confirmar(
                "  Continuar mesmo assim (essas HH nao serao agendadas)?", default=False
            )
        if not continuar_sem_executor:
            return None
        for talhao, tarefas in demandas.items():
            for t in tarefas:
                atv = t["atividade"]
                if t["hh_total"] > _HH_EPSILON and not turmas_que_executam(
                    atv, turmas, reatribuicao, paralelo, primaria
                ):
                    t["hh_total"] = 0.0
                    t["custo_total"] = 0.0
        total_hh = sum(t["hh_total"] for tarefas in demandas.values() for t in tarefas)
        total_custo = sum(t["custo_total"] for tarefas in demandas.values() for t in tarefas)
        total_hm = sum(t.get("hm_total", 0) for tarefas in demandas.values() for t in tarefas)
        aviso("HH sem executora foram zeradas no cronograma.")
        print(DM + f"  Total HH agendavel: {total_hh:.1f} horas-homem" + RS)
        if not modo_somente_hh(cfg):
            print(DM + f" Custo MO agendavel: R$ {total_custo:,.2f}" + RS)
        return total_hh, total_custo, total_hm
    total_hh = sum(t["hh_total"] for tarefas in demandas.values() for t in tarefas)
    total_custo = sum(t["custo_total"] for tarefas in demandas.values() for t in tarefas)
    total_hm = sum(t.get("hm_total", 0) for tarefas in demandas.values() for t in tarefas)
    return total_hh, total_custo, total_hm
