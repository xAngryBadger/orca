"""Core scheduler logic — the main scheduling algorithm, batch and multi-team executors."""

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

_HH_EPSILON = 0.01
DIAS_UTEIS_POR_MES = 22.0
_JORNADA_DEFAULT_H = 4.6

from .domain.scope import (
    _menu_ajustar_escopo_atividades,
    _proximo_caminho_livre,
)
from .domain.terrain import avaliar_terreno
from .engine_pkg import (
    _construir_demandas,
    _construir_filas_e_demanda_global,
    _executar_scheduler_loop,
    _merge_cronograma_base_e_metricas,
    _validar_input,
    _verificar_atividades_sem_executor,
    _verificar_atividades_sem_tarifa,
)
from .comparativo_config import _configurar_modo_comparativo
from .comparativo_mec import (
    _atividades_com_mecanizado_disponivel,
    _cadastrar_recurso_mecanizado_externo,
    _clonar_cfg_comparativo_mecanizado,
    _formatar_substituicao_comparativo,
    _substituir_por_mecanizado,
    coletar_config_comparativo_multifator,
    simular_cenarios_multifator,
)
from .config import (
    OUTPUT_DIR,
    _agrupar_fazendas_por_empresa,
    _detectar_cidade_por_fazenda,
    _distribuir_fazendas_por_territorio,
    _merge_sequencia_defaults,
    _sugerir_config_empresa,
    modo_somente_hh,
    salvar_config,
)
from .constants import CT317_HARDCODE_HH_BASE
from .context import contexto_sessao, dashboard_header
from .cronograma import (
    construir_cronograma_humano_sem_mecanizadas,
    construir_cronograma_mecanizado,
    construir_cronograma_mecanizado_auto_hm_tarifa,
)
from .datas import _calcular_data_fim_por_meses, _formatar_data_dia
from .de_para import aplicar_depara_padrao_exame, auto_mapear_de_para
from .excel_export import (
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
from .monitor import _emitir_monitor_atual, _emitir_monitor_relatorio, _emitir_monitor_state, _monitor_build_rendimentos
from .scheduler import (
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
from .tarifas import (
    aviso_politica_tarifas_planas,
    resolver_chave_tarifa,
    resolver_custo_hora,
    resolver_rendimento_hh,
    resolver_rendimento_hm,
)
from .text_utils import (
    _norm_atv,
    _slug_ficheiro_seguro,
    atividades_por_filtro,
    normalizar_chave,
    parse_intervalos_escolha,
)
from .turmas import (
    _cadastrar_recursos_mecanizados_sn,
    _catalogo_atividades_completo,
    menu_vincular_atividades_turma,
    resolver_conflitos_e_reatribuir,
    sequencia_manutencao_seco_placeholder,
    sequencia_manutencao_umido_placeholder,
    turmas_que_executam,
)
from .ui import (
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


def _configurar_projeto_interativo(cfg):
    print(G + BL + "\n  CONFIGURACAO DO PROJETO" + RS + "\n")

    prazo_meses = pedir_float("Prazo META para conclusao (meses)", 6.0)
    hoje = datetime.datetime.now()
    print(
        DM
        + "  Referencia do calendario para DIAS UTEIS da meta (meses corridos a partir de): "
        + RS
    )
    mes_ref = pedir_int("Mes inicial (1-12)", hoje.month)
    mes_ref = max(1, min(12, int(mes_ref)))
    ano_ref = pedir_int("Ano inicial", hoje.year)
    dia_max = calendar.monthrange(ano_ref, mes_ref)[1]
    dia_ref = pedir_int(f"Dia inicial (1-{dia_max})", min(hoje.day, dia_max))
    dia_ref = max(1, min(dia_max, int(dia_ref)))

    data_inicio_txt = _formatar_data_dia(dia_ref, mes_ref, ano_ref)
    data_fim_txt = None
    if confirmar("Informar dia final manualmente?", default=False):
        mes_fim = pedir_int("Mes final (1-12)", mes_ref)
        mes_fim = max(1, min(12, int(mes_fim)))
        ano_fim = pedir_int("Ano final", ano_ref)
        dia_max_fim = calendar.monthrange(ano_fim, mes_fim)[1]
        dia_fim = pedir_int(
            f"Dia final (1-{dia_max_fim})", min(dia_ref, dia_max_fim)
        )
        dia_fim = max(1, min(dia_max_fim, int(dia_fim)))
        data_fim_txt = _formatar_data_dia(dia_fim, mes_fim, ano_fim)
    else:
        fim_calc = _calcular_data_fim_por_meses(
            dia_ref, mes_ref, ano_ref, prazo_meses
        )
        if fim_calc:
            data_fim_txt = _formatar_data_dia(fim_calc[0], fim_calc[1], fim_calc[2])

    contexto_sessao.definir_datas(data_inicio_txt, data_fim_txt)
    # Não chamar dashboard_header() aqui para evitar flickering

    j_def = float(cfg.get("jornada_horas") or _JORNADA_DEFAULT_H)
    if j_def <= 0:
        j_def = _JORNADA_DEFAULT_H
    executores = pedir_int(
        "Operarios totais (quem realmente trabalha)",
        9,
    )
    jornada = pedir_jornada(
        "Jornada efetiva diaria (ex: 6.5 ou 6:30 = 6h30)", round(j_def, 2)
    )
    cfg["jornada_horas"] = jornada
    salvar_config(cfg)

    if executores <= 0:
        erro("Precisa de pelo menos 1 executor.")
        return None
    print(
        G + f"\n Equipe Operacional: {executores} operarios @ {jornada}h/dia" + RS
    )
    if confirmar(
        "Configurar COMPARATIVO MULTI-FATOR agora (para exportar no Excel)?",
        default=False,
    ):
        comparativo_cfg = coletar_config_comparativo_multifator(executores, jornada)
    else:
        comparativo_cfg = None

    sub()
    print(G + BL + "  ETAPA 1: CRIAR TURMAS / FUNCOES" + RS)
    print(
        DM + "  Defina grupos de trabalho (ex: Rocadores, Adubadores, Geral)." + RS
    )
    print(
        DM + "  Depois voce vinculara quais atividades cada turma executa.\n" + RS
    )

    turmas = []
    restantes = executores

    while restantes > 0:
        print(G + f"  Operarios disponiveis: {restantes}" + RS)
        nome_turma = prompt(
            "Nome da turma (ex: Rocadores)", f"Turma {len(turmas) + 1}"
        )
        def_pad = min(restantes, max(1, restantes // 2 or restantes))
        qtd = pedir_int(f"  Quantos operarios na turma '{nome_turma}'", def_pad)
        if qtd > restantes:
            aviso(f"Maximo disponivel: {restantes}. Ajustando.")
            qtd = restantes
        turmas.append({"nome": nome_turma, "operarios": qtd, "atividades": []})
        restantes -= qtd
        if restantes > 0:
            if not confirmar(
                f"Criar outra turma? ({restantes} restantes)", default=True
            ):
                turmas.append(
                    {"nome": "Geral", "operarios": restantes, "atividades": []}
                )
                restantes = 0

    sub()
    print(G + BL + "  TURMAS CRIADAS:" + RS)
    for t in turmas:
        print(G + f"  - {t['nome']}: " + C + f"{t['operarios']} operarios" + RS)
    sub()

    return {
        "prazo_meses": prazo_meses,
        "mes_ref": mes_ref,
        "ano_ref": ano_ref,
        "dia_ref": dia_ref,
        "data_inicio_txt": data_inicio_txt,
        "data_fim_txt": data_fim_txt,
        "jornada": jornada,
        "executores": executores,
        "comparativo_cfg": comparativo_cfg,
        "turmas": turmas,
    }


def _vincular_atividades_turmas(
    turmas, atividades_reais, _batch, ctx, atividade_remap,
    atividades_reais_set, fazenda, modo_seq, catalogo_global,
):
    for turma in turmas:
        if not _batch:
            menu_vincular_atividades_turma(
                turma,
                atividades_reais,
                atividades_catalogo=catalogo_global,
            )
        else:
            existing = {
                _norm_atv(a) for a in (turma.get("atividades") or []) if _norm_atv(a)
            }
            remapeadas = set(existing)
            for atv in list(existing):
                alvo = atividade_remap.get(atv)
                if alvo:
                    remapeadas.add(alvo)
            matched = remapeadas & atividades_reais_set
            turma["atividades"] = sorted(matched, key=str)

    def _cobertura_atual_turmas():
        s = set()
        for t in turmas:
            for a in t.get("atividades") or []:
                na = _norm_atv(a)
                if na:
                    s.add(na)
        return s

    cob_pre = _cobertura_atual_turmas()
    orfas_pre = [a for a in atividades_reais if a not in cob_pre]
    preencher_orfas = False
    if orfas_pre:
        if _batch:
            preencher_orfas = bool(ctx.get("preencher_orfas_template", False))
        elif modo_seq == "personalizado":
            preencher_orfas = confirmar(
                "Esta fazenda tem demandas sem turma no modelo. Preencher na turma com mais operarios? "
                "(N = equipe especializada; HH dessas atividades nao entram no cronograma)",
                default=False,
            )
    if preencher_orfas:
        _distribuir_atividades_faltantes_turmas(turmas, atividades_reais, fazenda)

    for turma in turmas:
        if not turma["atividades"]:
            aviso(f"Turma '{turma['nome']}' ficou sem atividades!")

    def coletar_vinculadas():
        s = set()
        for t in turmas:
            s.update(t["atividades"])
        return s

    atividades_vinculadas = coletar_vinculadas()
    orfas = [a for a in atividades_reais if a not in atividades_vinculadas]
    if orfas:
        print(Y + f"\n  ATENCAO: {len(orfas)} atividades sem turma vinculada:" + RS)
        for o in orfas:
            print(Y + f"    - {str(o)[:55]}" + RS)
        vincular_orfas = False
        turma_alvo = None
        if _batch:
            vincular_orfas = bool(ctx.get("preencher_orfas_template", False))
            if vincular_orfas and turmas:
                turma_alvo = max(
                    turmas, key=lambda t: int(t.get("operarios", 0) or 0)
                ).get("nome")
        else:
            vincular_orfas = confirmar(
                "Vincular todas as orfas a uma turma existente?", default=True
            )
            if vincular_orfas:
                nomes = [t["nome"] for t in turmas]
                turma_alvo = selecionar("TURMA PARA ORFAS", nomes)

        if vincular_orfas and turma_alvo:
            for t in turmas:
                if t["nome"] == turma_alvo:
                    t["atividades"] = sorted(
                        set(t["atividades"]) | set(orfas), key=lambda x: str(x)
                    )
                    ok(f"{len(orfas)} atividades vinculadas a '{turma_alvo}'.")
                    break
        elif _batch and vincular_orfas:
            aviso("Modo batch: sem turma destino valida para atividades orfas.")

    atividades_vinculadas = coletar_vinculadas()
    return atividades_vinculadas


def _configurar_conflitos_reatribuicao(
    _batch, ctx, atividade_remap, atividades_reais_set, turmas, atividades_reais,
):
    print(G + BL + "\n  ETAPA 3: CONFLITOS E REATRIBUICAO" + RS)
    if _batch:
        reatribuicao_tpl = dict((ctx.get("reatribuicao_template") if ctx else {}) or {})
        paralelo_tpl = dict((ctx.get("paralelo_template") if ctx else {}) or {})
        primaria_tpl = dict((ctx.get("primaria_template") if ctx else {}) or {})

        reatribuicao = {}
        paralelo = {}
        primaria = {}
        for atv, turma_nome in reatribuicao_tpl.items():
            atv_n = _norm_atv(atv)
            atv_n = atividade_remap.get(atv_n, atv_n)
            if atv_n in atividades_reais_set and turma_nome:
                reatribuicao[atv_n] = turma_nome
        for atv, em_paralelo in paralelo_tpl.items():
            atv_n = _norm_atv(atv)
            atv_n = atividade_remap.get(atv_n, atv_n)
            if atv_n in atividades_reais_set:
                paralelo[atv_n] = bool(em_paralelo)
        for atv, turma_nome in primaria_tpl.items():
            atv_n = _norm_atv(atv)
            atv_n = atividade_remap.get(atv_n, atv_n)
            if atv_n in atividades_reais_set and turma_nome:
                primaria[atv_n] = turma_nome
    else:
        reatribuicao, paralelo, primaria = resolver_conflitos_e_reatribuir(
            turmas, atividades_reais
        )

    return reatribuicao, paralelo, primaria


def _auditar_escopo_cronograma(
    df_faz, cronograma_com_mec, cronograma_base, demandas, atividades_mec_set, recursos_mec,
):
    atividades_escopo = sorted(
        {
            str(a).strip()
            for a in df_faz["atividade"].dropna().tolist()
            if str(a).strip()
        },
        key=str,
    )
    escopo_set = set(atividades_escopo)
    ag_hum_set = set()
    ag_mec_set = set()
    cronograma_ref = cronograma_com_mec if cronograma_com_mec else cronograma_base
    for item in cronograma_ref or []:
        atividade_item = str(item.get("Atividade", "") or "").strip()
        if not atividade_item:
            continue
        hh_item = float(item.get("HH", 0) or 0)
        hm_item = float(item.get("HM", 0) or 0)
        turma_item = str(item.get("Turma", "") or "")
        if turma_item.startswith("MEC_") or (hm_item > 0 and hh_item <= 0):
            ag_mec_set.add(atividade_item)
        else:
            ag_hum_set.add(atividade_item)
    faltantes_set = escopo_set - (ag_hum_set | ag_mec_set)

    hh_por_atividade = defaultdict(float)
    for tarefas in demandas.values():
        for t in tarefas:
            atividade_t = str(t.get("atividade", "") or "").strip()
            if not atividade_t:
                continue
            hh_por_atividade[atividade_t] += float(t.get("hh_total", 0) or 0)

    rows_audit = []
    for a in atividades_escopo:
        if a in ag_hum_set:
            status = "agendada_humana"
        elif a in ag_mec_set:
            status = "agendada_mecanizada"
        else:
            status = "nao_agendada"

        motivo = ""
        if status == "nao_agendada":
            if a in atividades_mec_set and not recursos_mec:
                motivo = "atividade mecanizada sem recurso cadastrado"
            else:
                motivo = "sem alocacao no cronograma"

        rows_audit.append(
            {
                "Atividade": a,
                "HH_Escopo": round(float(hh_por_atividade.get(a, 0) or 0), 2),
                "Status": status,
                "Motivo": motivo,
            }
        )
    df_audit = pd.DataFrame(rows_audit)
    sub()
    print(G + BL + "  AUDITORIA DO ESCOPO (ANTES DA EXPORTACAO)" + RS)
    print(DM + f"  Atividades no escopo: {len(atividades_escopo)}" + RS)
    print(DM + f"  Agendadas no humano: {len(ag_hum_set & escopo_set)}" + RS)
    print(DM + f"  Agendadas no mecanizado: {len(ag_mec_set & escopo_set)}" + RS)
    print(DM + f"  Nao agendadas: {len(faltantes_set)}" + RS)
    rocadas_escopo = [a for a in atividades_escopo if "rocada" in normalizar_chave(a)]
    if rocadas_escopo:
        for rcv in rocadas_escopo:
            if rcv in ag_hum_set:
                st = "agendada_humana"
            elif rcv in ag_mec_set:
                st = "agendada_mecanizada"
            else:
                st = "nao_agendada"
            print(DM + f"    rocada: {rcv[:56]} -> {st}" + RS)

    return {
        "atividades_escopo": atividades_escopo,
        "escopo_set": escopo_set,
        "ag_hum_set": ag_hum_set,
        "ag_mec_set": ag_mec_set,
        "faltantes_set": faltantes_set,
        "df_audit": df_audit,
    }


def _diagnostico_prazo(
    prazo_meses, dias_meta, mes_ref, ano_ref,
    dias_simulado, meses_simulado,
    executores, jornada, total_hh,
    recursos_mec, cronograma_com_mec,
):
    linha()
    print(G + BL + "  DIAGNOSTICO DE PRAZO" + RS)
    sub()
    print(
        G
        + f"  Meta informada             : {prazo_meses} meses ({dias_meta} dias uteis a partir de {mes_ref:02d}/{ano_ref})"
        + RS
    )
    print(
        G
        + f"  Duracao simulada           : {dias_simulado} dias ({meses_simulado:.1f} meses)"
        + RS
    )
    if recursos_mec and cronograma_com_mec:
        d_mc = max([int(x.get("Dia", 0)) for x in cronograma_com_mec], default=0)
        m_mc = d_mc / DIAS_UTEIS_POR_MES if d_mc > 0 else 0.0
        print(C + f"  Duracao cenario mecanizado : {d_mc} dias ({m_mc:.1f} meses)" + RS)
        print(
            C
            + f"  Ganho operacional estimado : {int(dias_simulado) - int(d_mc):+d} dias"
            + RS
        )
    sub()

    if meses_simulado <= prazo_meses:
        print(G + BL + "  STATUS: DENTRO DO PRAZO" + RS)
        print(G + f"  Equipe de {executores} executores conclui antes da meta." + RS)
    else:
        print(Y + BL + "  STATUS: PRAZO EXCEDIDO" + RS)
        print(
            Y
            + f"  Equipe atual levara {meses_simulado:.1f} meses (meta: {prazo_meses})."
            + RS
        )
        exec_teoricos = (
            math.ceil(total_hh / (dias_meta * jornada)) if (dias_meta * jornada) > 0 else 1
        )
        print(
            C
            + f"  [SUGESTAO] ~{exec_teoricos} executores @ {jornada}h/dia cumpririam a meta."
            + RS
        )
        if dias_meta > 0 and total_hh > _HH_EPSILON:
            ex5 = math.ceil(total_hh / (dias_meta * 5.0))
            ex6 = math.ceil(total_hh / (dias_meta * 6.0))
            print(
                DM
                + f"  [DICA] Com a mesma jornada na meta, ~{ex5} executores @ 5h/dia ou ~{ex6} @ 6h/dia "
                f"(aprox.: HH total / {dias_meta} dias uteis / jornada)." + RS
            )

    linha()


def _build_resultado_final(
    esperar_enter, fazenda, dias_simulado, meses_simulado,
    prazo_meses, dias_meta, total_hh, total_custo, total_hm,
    cronograma_base, turmas, resultado_mecanizado,
    resultado_mecanizado_valido, substituicoes_comparativo,
    recursos_mec, cronograma_com_mec, demandas,
):
    if esperar_enter:
        esperar("ENTER para voltar ao menu")
    d_mc = (
        max([int(x.get("Dia", 0)) for x in cronograma_com_mec], default=0)
        if (recursos_mec and cronograma_com_mec)
        else None
    )
    ganho_mc = (int(dias_simulado) - int(d_mc)) if d_mc is not None else 0
    rendimentos_feed = []
    if callable(_monitor_build_rendimentos):
        try:
            rendimentos_feed = _monitor_build_rendimentos(demandas)
        except Exception:
            rendimentos_feed = []
    _emitir_monitor_state(
        {
            "operacao": {
                "fazenda_atual": str(fazenda),
                "status_geral": "concluido",
                "mensagem_curta": f"{dias_simulado} dia(s) simulados | HH {total_hh:.1f}",
            },
            "lote": {
                "dias_meta": int(dias_meta),
                "dias_consumidos": int(dias_simulado),
                "saldo_dias": int(max(0, int(dias_meta) - int(dias_simulado))),
                "status_meta_continuo": "OK"
                if meses_simulado <= prazo_meses
                else "EXCEDIDO",
                "prazo_absoluto": True,
            },
            "rendimentos_sessao": rendimentos_feed,
        }
    )
    resumo_monitor = [
        f"Fazenda: {fazenda}",
        f"Dias simulados: {int(dias_simulado)}",
        f"HH total: {float(total_hh):.1f}",
    ]
    _emitir_monitor_relatorio(f"Resumo {fazenda}", "\n".join(resumo_monitor))

    resultado_final = {
        "fazenda": fazenda,
        "dias_simulado": int(dias_simulado),
        "meses_simulado": float(meses_simulado),
        "dias_mecanizado": d_mc,
        "ganho_mecanizado_dias": int(ganho_mc),
        "total_hh": float(total_hh),
        "total_custo": float(total_custo),
        "total_hm": float(total_hm),
        "cronograma": cronograma_base,
        "turmas_snapshot": [
            {"nome": t["nome"], "operarios": t["operarios"]} for t in turmas
        ],
    }

    if resultado_mecanizado_valido:
        resultado_final["comparativo_mecanizado"] = {
            "dias_simulado": resultado_mecanizado.get("dias_simulado"),
            "total_hh": resultado_mecanizado.get("total_hh"),
            "total_hm": resultado_mecanizado.get("total_hm"),
            "total_custo": resultado_mecanizado.get("total_custo", 0),
            "substituicoes_aplicadas": [
                {
                    "manual": manual,
                    "mecanizado": _formatar_substituicao_comparativo(mec),
                }
                for manual, mec in (substituicoes_comparativo or {}).items()
            ],
        }

    return resultado_final


@dataclass
class _ComparativoUIConfig:
    modo_comparativo: any
    substituicoes_comparativo: any
    session_hh: any


@dataclass
class _ComparativoExecutionConfig:
    cfg: any
    df_faz: any
    fazenda: any
    modo_seq: any
    usar_bloqueio_global: any
    usar_reforco_automatico: any
    usar_pool_pos_bloqueio: any
    prazo_meses: any
    mes_ref: any
    ano_ref: any
    data_inicio_txt: any
    data_fim_txt: any
    jornada: any
    executores: any
    turmas: any
    preencher_orfas: any
    reatribuicao: any
    paralelo: any
    primaria: any
    escopo_meta: any
    atividades_catalogo: any


@dataclass
class _ComparativoResult:
    total_hh: any
    total_hm: any
    dias_simulado: any


@dataclass
class _SchedulerLoopConfig:
    turmas: any
    turma_filas: any
    demanda_global: any
    demandas: any
    talhoes_ordenados: any
    jornada: any
    executores: any
    seq_cfg: any
    modo_seq: any
    usar_cascata: any
    usar_bloqueio_global: any
    atividades_bloqueadas: any
    usar_reforco_automatico: any
    usar_pool_pos_bloqueio: any
    atividades_plantio: any
    atividades_irrig: any
    fazenda: any
    cfg: any
    tarifas: any
    modo_somente_hh: any
    dia_termino_plantio: any
    tem_plantio_por_talhao: any


def _exibir_comparativo_resultado(ui_config: _ComparativoUIConfig, exec_config: _ComparativoExecutionConfig, result: _ComparativoResult, resultado_mecanizado: dict):
    """Exibe o resultado do comparativo mecanizado vs manual."""
    d_manual = float(result.dias_simulado)
    d_mec = float(resultado_mecanizado.get("dias_simulado") or 0)
    hh_manual = float(result.total_hh)
    hh_mec = float(resultado_mecanizado.get("total_hh") or 0)
    hm_manual = float(result.total_hm)
    hm_mec = float(resultado_mecanizado.get("total_hm") or 0)

    economia_dias = int(d_manual - d_mec)
    economia_hh = hh_manual - hh_mec
    economia_hm = hm_mec - hm_manual
    cap_hh_dia = float(exec_config.executores) * float(exec_config.jornada)
    dias_eq_hh_manual = (hh_manual / cap_hh_dia) if cap_hh_dia > _HH_EPSILON else 0.0
    dias_eq_hh_mec = (hh_mec / cap_hh_dia) if cap_hh_dia > _HH_EPSILON else 0.0
    delta_dias_eq_hh = dias_eq_hh_manual - dias_eq_hh_mec
    cronograma_mec_ref = resultado_mecanizado.get("cronograma") or []
    turmas_mec_comp = sorted(
        {
            str(x.get("Turma", ""))
            for x in cronograma_mec_ref
            if str(x.get("Turma", "")).startswith("MEC_")
        },
        key=str,
    )

    sub()
    print(G + BL + "══════════════════════════════════════════════════════════════════" + RS)
    print(G + BL + "       COMPARATIVO: MANUAL vs MECANIZADO" + RS)
    print(G + BL + "══════════════════════════════════════════════════════════════════" + RS)
    print()

    print(f"  {C}Métrica{RS}                    {C}Manual{RS}          {C}Mecanizado{RS}      {C}Diferença{RS}")
    print(f"  {DM}{'─' * 70}{RS}")
    print(f"  {'Dias necessários':<25} {d_manual:>10.0f}      {d_mec:>10.0f}      {Y}{economia_dias:>+10.0f}{RS}")
    print(f"  {'HH totais':<25} {hh_manual:>10.1f}      {hh_mec:>10.1f}      {Y}{economia_hh:>+10.1f}{RS}")
    print(f"  {'HM totais':<25} {hm_manual:>10.1f}      {hm_mec:>10.1f}      {Y}{economia_hm:>+10.1f}{RS}")
    print(f"  {'Dias eq. via HH/cap':<25} {dias_eq_hh_manual:>10.2f}      {dias_eq_hh_mec:>10.2f}      {Y}{delta_dias_eq_hh:>+10.2f}{RS}")
    print()
    if turmas_mec_comp:
        print(G + BL + "  TURMAS MECANIZADAS NO CENARIO:" + RS)
        for nm_turma in turmas_mec_comp:
            print(DM + f"    - {nm_turma}" + RS)
        print()
    if ui_config.substituicoes_comparativo:
        print(G + BL + "  SUBSTITUICOES APLICADAS:" + RS)
        for manual, mec in ui_config.substituicoes_comparativo.items():
            print(f"  • {manual[:50]} → {C}{_formatar_substituicao_comparativo(mec)}{RS}")
        print()

    print(G + BL + "  DESTAQUES:" + RS)
    if economia_dias > 0:
        print(f"  {G}✓{RS} Redução de {G}{economia_dias}{RS} dias com mecanização")
    if economia_hh > 0:
        print(f"  {G}✓{RS} Economia de {G}{economia_hh:.1f}{RS} HH (mão de obra humana)")
    if economia_dias <= 0 and economia_hh > 0 and cap_hh_dia > _HH_EPSILON:
        print(
            DM
            + f"  Nota: a reducao de HH equivale a ~{delta_dias_eq_hh:.2f} dia(s), "
            + "mas o cronograma fecha por dias inteiros e caminho critico; por isso pode manter o mesmo total de dias."
            + RS
        )
    print()
    print(G + BL + "══════════════════════════════════════════════════════════════════" + RS)
    sub()


def _executar_modo_comparativo(ui_config: _ComparativoUIConfig, exec_config: _ComparativoExecutionConfig, result: _ComparativoResult):
    resultado_mecanizado = None
    resultado_mecanizado_valido = False
    if ui_config.modo_comparativo and ui_config.substituicoes_comparativo:
        comparativo_cfg = exec_config.cfg.get("comparativo", {}) if isinstance(exec_config.cfg, dict) else {}
        execucao_compacta = bool(comparativo_cfg.get("execucao_compacta", True))

        df_mec = _substituir_por_mecanizado(exec_config.df_faz, ui_config.substituicoes_comparativo)
        cfg_mec = _clonar_cfg_comparativo_mecanizado(exec_config.cfg, ui_config.substituicoes_comparativo)

        n_substituicoes = 0
        for manual, mec in ui_config.substituicoes_comparativo.items():
            if (exec_config.df_faz["atividade"] == manual).any():
                n_substituicoes += (exec_config.df_faz["atividade"] == manual).sum()

        ctx_mec = {
            "modo_seq": exec_config.modo_seq,
            "usar_bloqueio_global": exec_config.usar_bloqueio_global,
            "usar_reforco_automatico": exec_config.usar_reforco_automatico,
            "usar_pool_pos_bloqueio": exec_config.usar_pool_pos_bloqueio,
            "prazo_meses": exec_config.prazo_meses,
            "mes_ref": exec_config.mes_ref,
            "ano_ref": exec_config.ano_ref,
            "data_inicio_txt": exec_config.data_inicio_txt,
            "data_fim_txt": exec_config.data_fim_txt,
            "jornada": exec_config.jornada,
            "executores": exec_config.executores,
            "turmas": exec_config.turmas,
            "preencher_orfas_template": exec_config.preencher_orfas,
            "substituicoes_template": ui_config.substituicoes_comparativo,
            "reatribuicao_template": exec_config.reatribuicao,
            "paralelo_template": exec_config.paralelo,
            "primaria_template": exec_config.primaria,
            "session_hh": ui_config.session_hh,
        }

        if execucao_compacta:
            _buf_cmp = io.StringIO()
            try:
                with redirect_stdout(_buf_cmp), redirect_stderr(_buf_cmp):
                    resultado_mecanizado = calcular_cronograma_inteligente(
                        cfg_mec,
                        df_mec,
                        exec_config.fazenda + " (MECANIZADO)",
                        esperar_enter=False,
                        ctx=ctx_mec,
                        escopo_meta=exec_config.escopo_meta,
                        atividades_catalogo=exec_config.atividades_catalogo,
                        modo_comparativo=False,
                        substituicoes_comparativo=None,
                    )
            except Exception as e:
                resultado_mecanizado = None
        else:
            resultado_mecanizado = calcular_cronograma_inteligente(
                cfg_mec,
                df_mec,
                exec_config.fazenda + " (MECANIZADO)",
                esperar_enter=False,
                ctx=ctx_mec,
                escopo_meta=exec_config.escopo_meta,
                atividades_catalogo=exec_config.atividades_catalogo,
                modo_comparativo=False,
                substituicoes_comparativo=None,
            )

        if isinstance(resultado_mecanizado, dict) and resultado_mecanizado.get("acao") == "retroceder_escopo":
            resultado_mecanizado = None
        elif isinstance(resultado_mecanizado, dict) and resultado_mecanizado.get("acao"):
            resultado_mecanizado = None
        elif not isinstance(resultado_mecanizado, dict):
            resultado_mecanizado = None
        else:
            chaves_obrigatorias = (
                "dias_simulado",
                "total_hh",
            )
            faltantes = [k for k in chaves_obrigatorias if k not in resultado_mecanizado]
            if faltantes:
                resultado_mecanizado = None
            else:
                resultado_mecanizado_valido = True

    return resultado_mecanizado, resultado_mecanizado_valido


def _executar_checkpoint_retroativo(
    _batch, turmas, atividades_reais, catalogo_global,
    executores, jornada, cfg, session_hh,
    reatribuicao, paralelo, primaria, df_faz,
    recalcular_callback,
):
    if not _batch:
        if confirmar(
            "Ajustar HH/ha por atividade APENAS nesta execucao (nao grava config)?",
            default=False,
        ):
            menu_ajustes_hh_apenas_sessao(atividades_reais, cfg, session_hh)

    while True:
        if _batch:
            break
        
        sub()
        print(G + BL + " CHECKPOINT RETROATIVO" + RS)
        op_cp = selecionar(
            "O QUE DESEJA REVISAR?",
            [
                "Editar atividades de uma turma",
                "Reprocessar conflitos/reatribuicao",
                "Ajustar HH/ha desta sessao",
                "Ajustar escopo de atividades desta execucao",
                "Revisar jornada/equipe",
                "Voltar ao seletor de fazenda/escopo",
                "Continuar para simulacao",
            ],
        )

        if not op_cp or op_cp == "Continuar para simulacao":
            break

        if op_cp == "Voltar ao seletor de fazenda/escopo":
            return {"acao": "retroceder_escopo"}

        if op_cp == "Revisar jornada/equipe":
            print(DM + f"\n Atual: {executores} operarios @ {jornada}h/dia" + RS)
            alterou = False
            if confirmar("Alterar jornada?", default=False):
                jornada = pedir_jornada(
                    "Nova jornada (ex: 6.5 ou 6:30 = 6h30)", round(jornada, 2)
                )
                cfg["jornada_horas"] = jornada
                salvar_config(cfg)
                ok(f"Jornada atualizada: {jornada}h/dia")
                alterou = True
            if confirmar("Alterar operarios?", default=False):
                executores = pedir_int("Operarios totais", executores)
                print(
                    G + f" Equipe: {executores} operarios @ {jornada}h/dia = {executores * jornada:.1f} HH/dia" + RS
                )
                alterou = True
            if not alterou:
                ok("Jornada/equipe mantidos sem alteracao.")
            continue

        if op_cp == "Editar atividades de uma turma":
            nomes_t = [t["nome"] for t in turmas]
            nm = selecionar("TURMA", nomes_t)
            if nm:
                for t in turmas:
                    if t["nome"] == nm:
                        menu_vincular_atividades_turma(
                            t,
                            atividades_reais,
                            atividades_catalogo=catalogo_global,
                        )
                        ok(f"Turma '{nm}' — edicao concluida.")
                        break
            else:
                ok("Nenhuma turma selecionada.")
            continue

        if op_cp == "Reprocessar conflitos/reatribuicao":
            reatribuicao, paralelo, primaria = resolver_conflitos_e_reatribuir(
                turmas, atividades_reais
            )
            if not paralelo and not reatribuicao:
                ok("Nenhum conflito multi-turma encontrado.")
            continue

        if op_cp == "Ajustar HH/ha desta sessao":
            menu_ajustes_hh_apenas_sessao(atividades_reais, cfg, session_hh)
            continue

        if op_cp == "Ajustar escopo de atividades desta execucao":
            df_faz = _menu_ajustar_escopo_atividades(
                df_faz,
                cfg=cfg,
                atividades_catalogo=catalogo_global,
            )
            atividades_reais, talhoes_ordenados, catalogo_global = recalcular_callback()
            reatribuicao, paralelo, primaria = resolver_conflitos_e_reatribuir(
                turmas, atividades_reais
            )
            continue

    return {
        "jornada": jornada,
        "executores": executores,
        "reatribuicao": reatribuicao,
        "paralelo": paralelo,
        "primaria": primaria,
        "df_faz": df_faz,
    }


def _mostrar_tabela_semanal(cronograma_base, fazenda, executores):
    table = Table(title=f"Cronograma - {fazenda} ({executores} Exec.)")
    table.add_column("Semana", justify="center", style="cyan")
    table.add_column("Dias", justify="center")
    table.add_column("Talhoes / Atividades", style="green")

    semanas = defaultdict(lambda: {"dias": set(), "acoes": set()})
    for c in cronograma_base:
        sem = math.ceil(c["Dia"] / 5)
        semanas[sem]["dias"].add(c["Dia"])
        semanas[sem]["acoes"].add(f"[{c['Talhao']}] {c['Atividade'][:18]}")

    for sem in sorted(semanas.keys())[:8]:
        d = semanas[sem]
        dias_str = f"Dia {min(d['dias'])} a {max(d['dias'])}"
        acoes = ", ".join(list(d["acoes"])[:3])
        if len(d["acoes"]) > 3:
            acoes += " (+)"
        table.add_row(f"Sem {sem}", dias_str, acoes)

    console.print(table)
    if len(semanas) > 8:
        print(DM + f"  ... e mais {len(semanas) - 8} semanas no Excel." + RS)


def _exportar_dossier_excel(
    cronograma_base, escopo_meta, fazenda, executores, jornada,
    prazo_meses, dias_meta, dias_simulado, meses_simulado,
    total_hh, total_custo, pct_fallback, n_fb,
    atividades_escopo, ag_hum_set, escopo_set, ag_mec_set, faltantes_set,
    recursos_mec, cronograma, turmas, dias_simulado_hum,
    cronograma_mec, cronograma_com_mec, cronograma_mec_base,
    df_audit, cenarios_rows, mes_ref, ano_ref, dia_ref, cfg,
):
    if not cronograma_base:
        return

    def _slug_nome(v):
        return str(v).replace("/", "_").replace(" ", "_")

    try:
        scope_tag = "__FAZENDA_TODOS"
        if isinstance(escopo_meta, dict):
            modo_th = str(escopo_meta.get("modo_talhao") or "")
            ths = [
                str(x) for x in (escopo_meta.get("talhoes") or []) if str(x).strip()
            ]
            if modo_th in ("unico", "parcial") and len(ths) == 1:
                scope_tag = f"__TH_{_slug_nome(ths[0])}"
            elif modo_th == "parcial" and len(ths) > 1:
                scope_tag = f"__TH_MULTI_{len(ths)}"
            elif modo_th in ("todos", "fallback_todos"):
                scope_tag = "__FAZENDA_TODOS"

        nome_base = f"Dossier_{_slug_nome(fazenda)}{scope_tag}"
        nome_op = f"{nome_base}_OPERACIONAL.xlsx"
        pasta_dossier = OUTPUT_DIR
        os.makedirs(pasta_dossier, exist_ok=True)
        nome_op, caminho_op = _proximo_caminho_livre(pasta_dossier, nome_op)

        df_crono = pd.DataFrame(cronograma_base)
        if "Dia" in df_crono.columns:
            df_crono["Semana"] = df_crono["Dia"].apply(
                lambda d: int(math.ceil(float(d) / 5.0)) if pd.notna(d) else ""
            )

        rows_op = [
            {"Metrica": "Fazenda", "Valor": fazenda},
            {"Metrica": "Arquivo operacional", "Valor": nome_op},
            {"Metrica": "Executores", "Valor": executores},
            {"Metrica": "Jornada (h/dia)", "Valor": jornada},
            {"Metrica": "Prazo Meta (meses)", "Valor": prazo_meses},
            {"Metrica": "Dias Uteis Meta", "Valor": dias_meta},
            {"Metrica": "Duracao Simulada (dias uteis)", "Valor": dias_simulado},
            {"Metrica": "Duracao Simulada (meses)", "Valor": f"{meses_simulado:.1f}"},
            {"Metrica": "HH Total Simulado", "Valor": f"{total_hh:,.1f}"},
            {
                "Metrica": "Custo MO Total",
                "Valor": f"R$ {total_custo:,.2f}" if not modo_somente_hh(cfg) else "N/A",
            },
            {
                "Metrica": "Fonte dos dados",
                "Valor": "100% CT"
                if pct_fallback < _HH_EPSILON
                else f"{100 - pct_fallback:.0f}% CT ({n_fb} fallbacks)",
            },
            {"Metrica": "", "Valor": ""},
            {"Metrica": "Atividades no escopo", "Valor": len(atividades_escopo)},
            {"Metrica": "Agendadas (humano)", "Valor": len(ag_hum_set & escopo_set)},
            {"Metrica": "Agendadas (mecanizado)", "Valor": len(ag_mec_set & escopo_set)},
            {"Metrica": "Nao agendadas", "Valor": len(faltantes_set)},
        ]
        if isinstance(escopo_meta, dict):
            rows_op.append(
                {
                    "Metrica": "Escopo talhoes",
                    "Valor": ", ".join(
                        str(x) for x in (escopo_meta.get("talhoes") or [])
                    )
                    or "todos",
                }
            )
        if recursos_mec:
            rows_op += [{"Metrica": "", "Valor": ""}]
            for rec in recursos_mec:
                rows_op.append(
                    {
                        "Metrica": f"Mecanizado: {rec['nome']}",
                        "Valor": f"{rec['prod_ha_h']} ha/h",
                    }
                )
                rows_op.append(
                    {
                        "Metrica": f"  Atividades ({rec['nome']})",
                        "Valor": str(len(rec.get("atividades", set()))),
                    }
                )
        resumo_op = pd.DataFrame(rows_op)

        df_cascata = _gerar_aba_cascata_explicada(
            cronograma_base, jornada, dia_ref, mes_ref, ano_ref
        )
        df_ocupacao = _gerar_aba_ocupacao_turmas(
            cronograma, turmas, jornada, dias_simulado_hum, dia_ref, mes_ref, ano_ref
        )
        df_crono_op = _df_crono_operacional(df_crono, dia_ref, mes_ref, ano_ref)

        with pd.ExcelWriter(caminho_op, engine="openpyxl") as writer_op:
            resumo_op.to_excel(writer_op, sheet_name="RESUMO_OPERACIONAL", index=False)
            df_crono_op.to_excel(writer_op, sheet_name="CRONOGRAMA_DETALHADO", index=False)
            if not df_cascata.empty:
                df_cascata.to_excel(writer_op, sheet_name="CASCATA_EXPLICADA", index=False)
            if not df_ocupacao.empty:
                df_ocupacao.to_excel(writer_op, sheet_name="OCUPACAO_TURMAS_DIA", index=False)
            if recursos_mec and cronograma_mec:
                df_mec_crono = _df_crono_operacional(pd.DataFrame(cronograma_mec))
                df_mec_crono.to_excel(writer_op, sheet_name="CRONOGRAMA_MECANIZADO", index=False)
                df_combinado = _df_crono_operacional(pd.DataFrame(cronograma_com_mec))
                df_combinado.to_excel(writer_op, sheet_name="CRONOGRAMA_COMBINADO", index=False)
            if cronograma_mec_base:
                df_mec_base = _df_crono_operacional(pd.DataFrame(cronograma_mec_base))
                df_mec_base.to_excel(writer_op, sheet_name="CRONOGRAMA_MEC_BASE", index=False)
            if not df_audit.empty:
                df_audit.to_excel(writer_op, sheet_name="AUDITORIA_ESCOPO", index=False)
            wb_op = writer_op.book
            _aplicar_cores_ocupacao_excel(wb_op, "OCUPACAO_TURMAS_DIA")
            try:
                from src.utils.orca_excel_format import (
                    aplicar_formatacao_operacional as _fmt_operacional,
                )

                _fmt_operacional(wb_op, dias_simulado, cronograma_base)
            except Exception as _fmt_err:
                aviso(f"Formatacao operacional falhou (formatador externo): {_fmt_err}")

        ok(f"Dossier operacional exportado: {nome_op}")

        if cenarios_rows:
            nome_xlsx_cmp = f"Dossier_{fazenda.replace('/', '_').replace(' ', '_')}_COMPARATIVO_CENARIOS.xlsx"
            nome_xlsx_cmp, caminho_xlsx_cmp = _proximo_caminho_livre(
                pasta_dossier, nome_xlsx_cmp
            )
            with pd.ExcelWriter(caminho_xlsx_cmp, engine="openpyxl") as writer3:
                pd.DataFrame(cenarios_rows).to_excel(
                    writer3, sheet_name="COMPARATIVO_CENARIOS", index=False
                )
            ok(f"Dossier comparativo de cenarios exportado: {nome_xlsx_cmp}")

        if recursos_mec and cronograma_com_mec:
            nome_mec_op = f"{nome_base}_COM_MECANIZADO_OPERACIONAL.xlsx"
            nome_mec_op, caminho_mec_op = _proximo_caminho_livre(
                pasta_dossier, nome_mec_op
            )
            df_mec_full = pd.DataFrame(cronograma_com_mec)
            if "Dia" in df_mec_full.columns:
                df_mec_full["Semana"] = df_mec_full["Dia"].apply(
                    lambda d: int(math.ceil(float(d) / 5.0)) if pd.notna(d) else ""
                )
            d_comb = max(
                [int(x.get("Dia", 0)) for x in cronograma_com_mec], default=0
            )
            rows_mec_op = [
                {"Metrica": "Fazenda", "Valor": fazenda},
                {"Metrica": "Arquivo operacional", "Valor": nome_mec_op},
                {"Metrica": "Cenario", "Valor": "Humano + Mecanizado"},
                {"Metrica": "Dias baseline (humano)", "Valor": dias_simulado},
                {"Metrica": "Dias cenario combinado", "Valor": d_comb},
                {
                    "Metrica": "Ganho de prazo (dias)",
                    "Valor": int(dias_simulado) - int(d_comb),
                },
                {
                    "Metrica": "Custo MO Total",
                    "Valor": f"R$ {total_custo:,.2f}" if not modo_somente_hh(cfg) else "N/A",
                },
            ]
            for rec in recursos_mec:
                rows_mec_op.append(
                    {
                        "Metrica": f"Recurso: {rec['nome']}",
                        "Valor": f"{rec['prod_ha_h']} ha/h",
                    }
                )

            df_cascata_mec = _gerar_aba_cascata_explicada(
                cronograma_com_mec, jornada, dia_ref, mes_ref, ano_ref
            )
            df_mec_op = _df_crono_operacional(
                df_mec_full, dia_ref, mes_ref, ano_ref
            )

            with pd.ExcelWriter(caminho_mec_op, engine="openpyxl") as writer_mo:
                pd.DataFrame(rows_mec_op).to_excel(
                    writer_mo, sheet_name="RESUMO_OPERACIONAL", index=False
                )
                df_mec_op.to_excel(
                    writer_mo, sheet_name="CRONOGRAMA_DETALHADO", index=False
                )
                if not df_cascata_mec.empty:
                    df_cascata_mec.to_excel(
                        writer_mo, sheet_name="CASCATA_EXPLICADA", index=False
                    )
                wb_mo = writer_mo.book
                try:
                    from src.utils.orca_excel_format import (
                        aplicar_formatacao_operacional as _fmt_operacional,
                    )

                    _fmt_operacional(wb_mo, d_comb, cronograma_com_mec)
                except Exception as _fmt_err:
                    aviso(f"Formatacao mecanizado falhou (formatador externo): {_fmt_err}")

            ok(f"Dossier cenario mecanizado (operacional): {nome_mec_op}")
    except Exception as ex:
        aviso(f"Nao foi possivel salvar Dossier: {ex}")


def _configurar_sequencia_bloqueio(cfg, seq_cfg, atividades_reais, ctx, _batch):
    if _batch:
        modo_seq = ctx["modo_seq"]
    else:
        modo_seq = _selecionar_sequencia_padrao_sn(cfg, seq_cfg, atividades_reais)

    modo_ctx = f"seq:{modo_seq}"
    modo_existente = contexto_sessao.modo_atual
    if modo_existente:
        if modo_ctx not in str(modo_existente):
            contexto_sessao.atualizar_modo(f"{modo_existente} | {modo_ctx}")
    else:
        contexto_sessao.atualizar_modo(modo_ctx)

    if modo_seq == "manutencao_seco":
        sequencia_manutencao_seco_placeholder(cfg)
    elif modo_seq == "manutencao_umido":
        sequencia_manutencao_umido_placeholder(cfg)
    usar_cascata = modo_seq in ("implantacao", "personalizado")
    diagnosticar_sequencia_atividades(atividades_reais, seq_cfg, modo_seq)

    if _batch:
        usar_bloqueio_global = ctx.get("usar_bloqueio_global", False)
        atividades_bloqueadas = set()
        if usar_bloqueio_global:
            filtros_bloqueio = cfg.get("filtros_bloqueio_global", ["plantio", "irrig"])
            atividades_bloqueadas = set(
                atividades_por_filtro(atividades_reais, filtros_bloqueio)
            )
        usar_reforco_automatico = ctx.get("usar_reforco_automatico", True)
        usar_pool_pos_bloqueio = ctx.get("usar_pool_pos_bloqueio", False)
    else:
        filtros_bloqueio = cfg.get("filtros_bloqueio_global", ["plantio", "irrig"])
        candidatas_bloqueio = atividades_por_filtro(atividades_reais, filtros_bloqueio)
        usar_bloqueio_global = False
        atividades_bloqueadas = set()
        if modo_seq == "personalizado":
            print(
                DM
                + "  Modo PERSONALIZADO: bloqueio global plantio/irrigacao DESLIGADO."
                + RS
            )
        elif candidatas_bloqueio:
            usar_bloqueio_global = confirmar(
                "Aplicar BLOQUEIO GLOBAL (plantio/irrigacao so iniciam quando TODO o resto zerar na fazenda)?",
                default=True,
            )
            if usar_bloqueio_global:
                atividades_bloqueadas = set(candidatas_bloqueio)
                print(
                    Y
                    + f"\n  BLOQUEADAS ATE LIBERACAO GLOBAL ({len(atividades_bloqueadas)}):"
                    + RS
                )
                for a in sorted(atividades_bloqueadas, key=lambda x: str(x))[:20]:
                    print(Y + f"    - {str(a)[:58]}" + RS)
                if len(atividades_bloqueadas) > 20:
                    print(DM + f"    ... +{len(atividades_bloqueadas) - 20}" + RS)
                if confirmar(
                    "Salvar estes filtros de bloqueio no config para proximas execucoes?",
                    default=True,
                ):
                    cfg["filtros_bloqueio_global"] = filtros_bloqueio
                    salvar_config(cfg)
        usar_reforco_automatico = confirmar(
            "Ativar REFORCO AUTOMATICO (turma ociosa ajuda outras atividades nao bloqueadas)?",
            default=True,
        )
        usar_pool_pos_bloqueio = False
        if usar_bloqueio_global:
            usar_pool_pos_bloqueio = confirmar(
                "Usar PELOTAO UNIFICADO (todos os executores) so em plantio/irrigacao apos liberacao global?",
                default=True,
            )
    return modo_seq, usar_cascata, usar_bloqueio_global, atividades_bloqueadas, usar_reforco_automatico, usar_pool_pos_bloqueio


def _mostrar_tabela_ocupacao(turmas, dias_simulado_hum, jornada, hh_por_turma, cronograma, executores, usar_pool_pos_bloqueio, usar_bloqueio_global, n_fb, pct_fallback, n_demandas):
    sub()
    print(G + BL + "  OCUPACAO POR TURMA" + RS)
    t_occ = Table()
    t_occ.add_column("Turma", style="cyan")
    t_occ.add_column("HH", justify="right")
    t_occ.add_column("Cap. max", justify="right")
    t_occ.add_column("Uso %", justify="right")
    crit_nm, crit_pct = "", 0.0
    for turma in turmas:
        nm = turma["nome"]
        cap = float(dias_simulado_hum) * float(turma["operarios"]) * float(jornada)
        us = hh_por_turma.get(nm, 0.0)
        pct = (100.0 * us / cap) if cap > _HH_EPSILON else 0.0
        if pct > crit_pct:
            crit_pct, crit_nm = pct, nm
        t_occ.add_row(nm, f"{us:.1f}", f"{cap:.1f}", f"{pct:.0f}%")
    if hh_por_turma.get("Pelotao_Unificado", 0) > _HH_EPSILON:
        d_pool = len(set(c["Dia"] for c in cronograma if c.get("Turma") == "Pelotao_Unificado"))
        pu = hh_por_turma["Pelotao_Unificado"]
        cap_p = float(d_pool) * float(executores) * float(jornada)
        pct_p = (100.0 * pu / cap_p) if cap_p > _HH_EPSILON else 0.0
        t_occ.add_row("Pelotao_Unificado", f"{pu:.1f}", f"{cap_p:.1f}", f"{pct_p:.0f}%")
    console.print(t_occ)
    print(DM + "  Uso % = HH no cronograma com o nome da turma / (dias simulados x operarios x jornada)." + RS)
    print(DM + "  Reforco nao aumenta n_ops; bloqueio global impede reforco em plantio/irrigacao ate liberar tudo." + RS)
    if usar_pool_pos_bloqueio and usar_bloqueio_global:
        print(DM + "  Pelotao_Unificado: plantio/irrigacao apos liberacao usam todos os executores num so pelotao." + RS)
    if crit_nm:
        print(DM + f"  Heuristica caminho critico (maior Uso %): turma '{crit_nm}' (~{crit_pct:.0f}%)." + RS)
    if n_fb > 0:
        print(DM + f"  Cobertura CT no escopo: {100 - pct_fallback:.0f}% (fallback em {n_fb}/{n_demandas} item(ns))." + RS)


def _executar_modo_mecanizado_opcional(
    _batch, modo_comparativo, substituicoes_comparativo,
    atividades_reais, cfg, hm_only_list, catalogo_global,
    demandas, fazenda, jornada, cronograma, turmas, executores,
    cronograma_base, cronograma_mec_base, dias_simulado,
):
    recursos_mec = []
    cronograma_mec = []
    cronograma_com_mec = []
    atividades_mec_set = set()
    if _batch:
        sub()
        print(
            DM
            + "  Modo batch: pulando 'modo mecanizado opcional' (sem prompts interativos)."
            + RS
        )
    elif modo_comparativo and substituicoes_comparativo:
        sub()
        print(
            DM
            + "  Comparativo MANUAL vs MECANIZADO ativo: pulando 'modo mecanizado opcional' para evitar duplicidade de cenarios."
            + RS
        )
    else:
        sub()
        print(C + BL + "  ATIVAR MODO MECANIZADO" + RS)
        print(
            DM
            + "  Cenario opcional: cadastrar recurso extra para adicionar/substituir atividades."
            + RS
        )
        if cronograma_mec_base:
            print(
                DM
                + "  As atividades HM do orcamento ja foram contabilizadas automaticamente no cronograma base."
                + RS
            )
            for a in hm_only_list[:5]:
                print(DM + f"    - {str(a)[:58]}" + RS)
            if len(hm_only_list) > 5:
                print(DM + f"    ... +{len(hm_only_list) - 5}" + RS)
        if hm_only_list:
            print(
                DM
                + f"  HM-only (HH=0) detectadas: {len(hm_only_list)} atividade(s)."
                + RS
            )
        if confirmar("  Ativar modo mecanizado opcional?", default=False):
            recursos_mec = _cadastrar_recursos_mecanizados_sn(
                atividades_reais, cfg, atividades_catalogo=catalogo_global,
            )
            for rec in recursos_mec:
                atividades_mec_set.update(rec.get("atividades", set()))
            if recursos_mec and atividades_mec_set:
                cronograma_mec = construir_cronograma_mecanizado(
                    demandas, fazenda, jornada, recursos_mec
                )

            if cronograma_mec and atividades_mec_set:
                regra_implantacao_mec = "substituir_total"
                if confirmar(
                    "Regra de implantacao mecanizado: manter humano em PARALELO nas atividades mecanizadas?",
                    default=False,
                ):
                    regra_implantacao_mec = "paralelo"
                if regra_implantacao_mec == "paralelo":
                    crono_hum_sem_mec = [dict(x) for x in cronograma_base]
                else:
                    crono_hum_sem_mec_h = construir_cronograma_humano_sem_mecanizadas(
                        cronograma, turmas, jornada, executores, atividades_mec_set
                    )
                    crono_hum_sem_mec = sorted(
                        crono_hum_sem_mec_h + cronograma_mec_base,
                        key=lambda r: (int(r.get("Dia", 0)), str(r.get("Turma", ""))),
                    )
                cronograma_com_mec = sorted(
                    crono_hum_sem_mec + cronograma_mec,
                    key=lambda r: (int(r.get("Dia", 0)), str(r.get("Turma", ""))),
                )
                d_hum = max([int(x.get("Dia", 0)) for x in crono_hum_sem_mec], default=0)
                d_mec = max([int(x.get("Dia", 0)) for x in cronograma_mec], default=0)
                d_comb = max(d_hum, d_mec)
                t_mec = Table(title="Comparativo Operacional - Modo Mecanizado")
                t_mec.add_column("Metrica", style="cyan")
                t_mec.add_column("Valor", justify="right")
                t_mec.add_row("Dias baseline (cronograma base)", str(dias_simulado))
                t_mec.add_row("Dias base sem atividades opcionais", str(d_hum))
                t_mec.add_row("Dias recursos mecanizados (filas dedicadas)", str(d_mec))
                t_mec.add_row("Dias cenario combinado (humano || mecanizado)", str(d_comb))
                t_mec.add_row("Ganho de prazo (dias)", f"{int(dias_simulado) - int(d_comb):+d}")
                t_mec.add_row("Regra mecanizada", regra_implantacao_mec)
                for rec in recursos_mec:
                    t_mec.add_row(
                        f"  Recurso: {rec['nome']}", f"{rec['prod_ha_h']} ha/h",
                    )
                    t_mec.add_row(
                        f"  Atividades ({rec['nome']})",
                        str(len(rec.get("atividades", set()))),
                    )
                hm_mec_total = sum(
                    float(x.get("HM", x.get("HH", 0)) or 0) for x in cronograma_mec
                )
                t_mec.add_row("Horas mecanizadas (HM)", f"{hm_mec_total:.1f}")
                console.print(t_mec)

                t_alt = Table(title="Cronograma Alternativo (Humano + Mecanizado)")
                t_alt.add_column("Semana", justify="center", style="cyan")
                t_alt.add_column("Dias", justify="center")
                t_alt.add_column("Acoes", style="green")
                sem_alt = defaultdict(lambda: {"dias": set(), "acoes": set()})
                for c in cronograma_com_mec:
                    s = (int(math.ceil(float(c.get("Dia", 0)) / 5.0)) if c.get("Dia") else 0)
                    if s <= 0:
                        continue
                    sem_alt[s]["dias"].add(int(c["Dia"]))
                    txt = f"[{str(c.get('Talhao', ''))[:18]}] {str(c.get('Atividade', ''))[:18]} ({c.get('Turma', '')})"
                    sem_alt[s]["acoes"].add(txt)
                for s in sorted(sem_alt.keys())[:8]:
                    d = sem_alt[s]
                    dias_str = f"Dia {min(d['dias'])} a {max(d['dias'])}"
                    acoes = ", ".join(list(d["acoes"])[:3])
                    if len(d["acoes"]) > 3:
                        acoes += " (+)"
                    t_alt.add_row(f"Sem {s}", dias_str, acoes)
                console.print(t_alt)
    return recursos_mec, cronograma_mec, cronograma_com_mec, atividades_mec_set


def _render_tabela_cenarios(rows, label):
    if not rows:
        return
    t_sc = Table(title=f"Comparativo de Cenários (Equipe x Jornada) - {label}")
    t_sc.add_column("Equipe", justify="right")
    t_sc.add_column("Jornada", justify="right")
    t_sc.add_column("Dias", justify="right")
    t_sc.add_column("Meses", justify="right")
    t_sc.add_column("Ganho vs Meta", justify="right")
    for r in rows[:40]:
        t_sc.add_row(
            str(r["Equipe"]),
            f"{r['Jornada_h_dia']:.2f}",
            str(r["Dias_Simulados"]),
            f"{r['Meses_Simulados']:.2f}",
            f"{r['Ganho_vs_Meta_dias']:+d}",
        )
    console.print(t_sc)


def _executar_multi_fator_simulation(comparativo_cfg, _batch, recursos_mec, cronograma_com_mec, total_hh, dias_meta, executores, jornada):
    cenarios_rows = []
    if comparativo_cfg is not None and isinstance(comparativo_cfg, dict):
        hh_base_multi = float(total_hh)
        lbl_base_multi = "Sem mecanizado"
        if (not _batch) and recursos_mec and cronograma_com_mec:
            hh_hum_pos_mec = sum(
                float(x.get("HH", 0) or 0)
                for x in cronograma_com_mec
                if not str(x.get("Turma", "")).startswith("MEC_")
            )
            base_opt = selecionar(
                "BASE DO COMPARATIVO MULTI-FATOR",
                ["Sem mecanizado (HH total atual)", "Com mecanizado (HH humano remanescente)"],
            )
            if base_opt and base_opt.startswith("Com mecanizado"):
                hh_base_multi = float(hh_hum_pos_mec)
                lbl_base_multi = "Com mecanizado"
        print(DM + f"  Base selecionada: {lbl_base_multi} | HH={hh_base_multi:.1f}" + RS)
        cenarios_rows = simular_cenarios_multifator(
            total_hh=hh_base_multi, dias_meta=dias_meta,
            executores_base=executores, jornada_base=jornada,
            jornadas_in=comparativo_cfg.get("jornadas"),
            equipes_in=comparativo_cfg.get("equipes"),
            interativo=False,
        )
        _render_tabela_cenarios(cenarios_rows, lbl_base_multi)

    if not _batch:
        while confirmar("Recalcular comparativo multi-fator com novos valores agora?", default=False):
            hh_base_multi = float(total_hh)
            lbl_base_multi = "Sem mecanizado"
            if recursos_mec and cronograma_com_mec:
                hh_hum_pos_mec = sum(
                    float(x.get("HH", 0) or 0)
                    for x in cronograma_com_mec
                    if not str(x.get("Turma", "")).startswith("MEC_")
                )
                base_opt = selecionar(
                    "BASE DO COMPARATIVO MULTI-FATOR",
                    ["Sem mecanizado (HH total atual)", "Com mecanizado (HH humano remanescente)"],
                )
                if base_opt and base_opt.startswith("Com mecanizado"):
                    hh_base_multi = float(hh_hum_pos_mec)
                    lbl_base_multi = "Com mecanizado"
            print(DM + f"  Base selecionada: {lbl_base_multi} | HH={hh_base_multi:.1f}" + RS)
            cenarios_rows = simular_cenarios_multifator(
                total_hh=hh_base_multi, dias_meta=dias_meta,
                executores_base=executores, jornada_base=jornada,
                jornadas_in=comparativo_cfg.get("jornadas") if isinstance(comparativo_cfg, dict) else None,
                equipes_in=comparativo_cfg.get("equipes") if isinstance(comparativo_cfg, dict) else None,
                interativo=True,
            )
            _render_tabela_cenarios(cenarios_rows, lbl_base_multi)
    return cenarios_rows


def _construir_atividade_remap(cfg, ctx=None, _batch=False):
    atividade_remap = {}
    for manual, destino in (cfg.get("de_para", {}) or {}).items():
        manual_n = _norm_atv(manual)
        destino_n = _norm_atv(destino)
        if manual_n and destino_n:
            atividade_remap[manual_n] = destino_n
    if _batch and isinstance(ctx.get("substituicoes_template"), dict):
        for manual, destino in (ctx.get("substituicoes_template") or {}).items():
            manual_n = _norm_atv(manual)
            if isinstance(destino, dict):
                destino_nome = str(
                    destino.get("atividade_mecanizada")
                    or destino.get("nome")
                    or destino.get("recurso")
                    or ""
                ).strip()
            else:
                destino_nome = str(destino).strip()
            destino_n = _norm_atv(destino_nome)
            if manual_n and destino_n:
                atividade_remap[manual_n] = destino_n
    return atividade_remap


def _configurar_projeto_dados(cfg, ctx, _batch):
    if _batch:
        prazo_meses = ctx["prazo_meses"]
        mes_ref = ctx["mes_ref"]
        ano_ref = ctx["ano_ref"]
        dia_ref = ctx.get("dia_ref", 1)
        data_inicio_txt = ctx.get("data_inicio_txt")
        data_fim_txt = ctx.get("data_fim_txt")
        if data_inicio_txt or data_fim_txt:
            contexto_sessao.definir_datas(data_inicio_txt, data_fim_txt)
        jornada = ctx["jornada"]
        executores = ctx["executores"]
        comparativo_cfg = ctx.get("comparativo_cfg")
        turmas = []
        for t in ctx["turmas"]:
            turmas.append(
                {
                    "nome": t["nome"],
                    "operarios": t["operarios"],
                    "atividades": [
                        _norm_atv(a) for a in (t.get("atividades") or []) if _norm_atv(a)
                    ],
                }
            )
    else:
        proj = _configurar_projeto_interativo(cfg)
        if proj is None:
            return None
        prazo_meses = proj["prazo_meses"]
        mes_ref = proj["mes_ref"]
        ano_ref = proj["ano_ref"]
        dia_ref = proj["dia_ref"]
        data_inicio_txt = proj["data_inicio_txt"]
        data_fim_txt = proj["data_fim_txt"]
        jornada = proj["jornada"]
        executores = proj["executores"]
        comparativo_cfg = proj["comparativo_cfg"]
        turmas = proj["turmas"]
    return prazo_meses, mes_ref, ano_ref, dia_ref, data_inicio_txt, \
        data_fim_txt, jornada, executores, comparativo_cfg, turmas


def calcular_cronograma_inteligente(
    cfg,
    df_faz,
    fazenda,
    esperar_enter=True,
    ctx=None,
    escopo_meta=None,
    atividades_catalogo=None,
    modo_comparativo=False,
    substituicoes_comparativo=None,
):
    """
    ctx: optional dict with preconfigured session state for batch mode.
    When ctx is provided, interactive setup questions are skipped.
    """
    _batch = ctx is not None
    comparativo_cfg = None

    erro_colunas, df_faz = _validar_input(df_faz)
    if erro_colunas:
        return None
    tarifas = cfg.get("tarifas") or {}
    if not tarifas:
        aviso("Nenhuma tarifa carregada — rendimentos serao estimados (fallback)")

    contexto_sessao.atualizar_configuracoes(cfg)
    contexto_sessao.atualizar_fazenda(fazenda, df_faz)
    _emitir_monitor_atual()
    dashboard_header()

    if not _batch:
        subcabecalho(f"SMART SCHEDULER - {fazenda}")
        df_faz = avaliar_terreno(df_faz)
        aviso_politica_tarifas_planas()
    else:
        sub()
        print(G + BL + f"  SMART SCHEDULER - {fazenda}" + RS)
        df_faz["penalidade"] = float(ctx.get("penalidade", 1.0))

        _emitir_monitor_state(
            {
                "operacao": {
                    "fazenda_atual": str(fazenda),
                    "modo": "batch" if _batch else "single",
                    "micro_basename": str(cfg.get("arquivo_micro", "")),
                    "status_geral": "iniciando_scheduler",
                    "mensagem_curta": f"Scheduler iniciado para {fazenda}",
                }
            }
        )

    # ── Extrair atividades REAIS da fazenda ──
    df_faz = df_faz.copy()
    df_faz["atividade"] = df_faz["atividade"].map(
        lambda x: _norm_atv(x) if pd.notna(x) else x
    )
    if not _batch and confirmar(
        "Ajustar escopo de atividades (substituir/remover/adicionar) nesta execucao?",
        default=False,
    ):
        df_faz = _menu_ajustar_escopo_atividades(
            df_faz,
            cfg=cfg,
            atividades_catalogo=atividades_catalogo,
        )
    atividades_reais = sorted(
        {a for a in df_faz["atividade"].dropna().unique().tolist() if _norm_atv(a)},
        key=str,
    )
    catalogo_global = _catalogo_atividades_completo(
        atividades_reais,
        cfg=cfg,
        atividades_catalogo=atividades_catalogo,
    )
    talhoes_ordenados = sorted(df_faz["chave"].dropna().unique().tolist())
    escopo_talhoes = []
    if isinstance(escopo_meta, dict):
        escopo_talhoes = list(escopo_meta.get("talhoes") or [])

    if escopo_talhoes:
        contexto_sessao.definir_escopo_talhoes(escopo_talhoes, talhoes_ordenados)
    else:
        contexto_sessao.definir_escopo_talhoes(talhoes_ordenados, talhoes_ordenados)
    contexto_sessao.atualizar_atividades(0, len(atividades_reais))
    _emitir_monitor_atual()

    novos_fixos = aplicar_depara_padrao_exame(cfg, atividades_reais)
    if novos_fixos > 0:
        ok(f"de_para PADRAO aplicado: {novos_fixos} mapeamento(s) fixos EXAME->CT_313.")
    if not cfg.get("orcamento_estrito", True):
        novos_de_para = auto_mapear_de_para(cfg, atividades_reais)
        if novos_de_para > 0:
            ok(f"de_para complementar: {novos_de_para} mapeamento(s) adicionais.")

    if not _batch:
        sub()
        print(
            DM
            + "  Orcamento estrito (sem mediana silenciosa; lacunas pedem input): "
            + C
            + str(cfg.get("orcamento_estrito", True))
            + RS
        )
        if confirmar("  Alternar orcamento_estrito para esta execucao?", default=False):
            cfg["orcamento_estrito"] = not cfg.get("orcamento_estrito", True)
            salvar_config(cfg)
            ok(f"orcamento_estrito = {cfg['orcamento_estrito']}")

    sub()
    print(G + BL + "  ATIVIDADES ENCONTRADAS NESTA FAZENDA:" + RS)
    for i, a in enumerate(atividades_reais, 1):
        print(G + f"  {i:2}. " + C + a + RS)
    print(G + "\n  Talhoes: " + C + f"{len(talhoes_ordenados)}" + RS)
    if escopo_talhoes:
        n_show = min(8, len(escopo_talhoes))
        base = ", ".join(str(x)[:24] for x in escopo_talhoes[:n_show])
        if len(escopo_talhoes) > n_show:
            base += f", ... (+{len(escopo_talhoes) - n_show})"
            print(DM + f" Escopo talhoes selecionados: {base}" + RS)
    sub()

    seq_cfg = cfg.get("sequencia") or {}

    modo_comparativo, substituicoes_comparativo = _configurar_modo_comparativo(
        atividades_reais, _batch,
    )
    _merge_sequencia_defaults(seq_cfg)
    cfg["sequencia"] = seq_cfg

    modo_seq, usar_cascata, usar_bloqueio_global, atividades_bloqueadas, \
    usar_reforco_automatico, usar_pool_pos_bloqueio = _configurar_sequencia_bloqueio(
        cfg, seq_cfg, atividades_reais, ctx, _batch,
    )

    _proj_result = _configurar_projeto_dados(cfg, ctx, _batch)
    if _proj_result is None:
        return
    prazo_meses, mes_ref, ano_ref, dia_ref, data_inicio_txt, \
    data_fim_txt, jornada, executores, comparativo_cfg, turmas = _proj_result

    atividade_remap = _construir_atividade_remap(cfg, ctx, _batch)

    atividades_reais_set = set(atividades_reais)

    atividades_vinculadas = _vincular_atividades_turmas(
        turmas, atividades_reais, _batch, ctx, atividade_remap,
        atividades_reais_set, fazenda, modo_seq, catalogo_global,
    )
    contexto_sessao.atualizar_atividades(
        len(atividades_vinculadas), len(atividades_reais)
    )
    # Não chamar dashboard_header() aqui para evitar flickering

    reatribuicao, paralelo, primaria = _configurar_conflitos_reatribuicao(
        _batch, ctx, atividade_remap, atividades_reais_set, turmas, atividades_reais,
    )

    session_hh = {}
    if ctx and isinstance(ctx.get("session_hh"), dict):
        session_hh.update(ctx["session_hh"])

    def _recalcular_apos_ajuste_escopo():
        nonlocal df_faz, atividades_reais, talhoes_ordenados, catalogo_global
        atividades_reais = sorted(
            {
                a
                for a in df_faz["atividade"].dropna().unique().tolist()
                if _norm_atv(a)
            },
            key=str,
        )
        talhoes_ordenados = sorted(df_faz["chave"].dropna().unique().tolist())
        catalogo_global = _catalogo_atividades_completo(
            atividades_reais,
            cfg=cfg,
            atividades_catalogo=atividades_catalogo,
        )
        for t in turmas:
            cur = [a for a in (t.get("atividades") or []) if a in catalogo_global]
            t["atividades"] = sorted(set(cur), key=str)
        return atividades_reais, talhoes_ordenados, catalogo_global

    cp_result = _executar_checkpoint_retroativo(
        _batch, turmas, atividades_reais, catalogo_global,
        executores, jornada, cfg, session_hh,
        reatribuicao, paralelo, primaria, df_faz,
        _recalcular_apos_ajuste_escopo,
    )
    if isinstance(cp_result, dict) and cp_result.get("acao") == "retroceder_escopo":
        return cp_result
    jornada = cp_result["jornada"]
    executores = cp_result["executores"]
    reatribuicao = cp_result["reatribuicao"]
    paralelo = cp_result["paralelo"]
    primaria = cp_result["primaria"]
    df_faz = cp_result["df_faz"]

    # ── Validacao orcamento estrito (antes das demandas) ──
    if not validar_e_completar_orcamento(cfg, atividades_reais, session_hh=session_hh):
        if not _batch:
            esperar("ENTER para voltar")
            return
        aviso("Modo batch: validacao de orcamento falhou; cenario cancelado.")
        return {"acao": "orcamento_invalido"}

    tarifas = cfg.get("tarifas", {})
    de_para = cfg.get("de_para", {})
    strict = cfg.get("orcamento_estrito", True)

    demandas_data = _construir_demandas(
        talhoes_ordenados, df_faz, cfg, tarifas, strict, session_hh, modo_somente_hh, atividades_reais,
    )
    demandas = demandas_data["demandas"]
    total_hh = demandas_data["total_hh"]
    total_hm = demandas_data["total_hm"]
    total_custo = demandas_data["total_custo"]
    hm_only_atividades = demandas_data["hm_only_atividades"]
    fallback_hh_items = demandas_data["fallback_hh_items"]

    _verificar_atividades_sem_tarifa(demandas, cfg, tarifas, strict)

    sub()
    print(C + BL + "  PRE-CHECAGEM HH/HM ANTES DO CRONOGRAMA" + RS)
    if modo_comparativo and substituicoes_comparativo:
        print(
            DM
            + "  [COMPARATIVO] Esta pre-checagem e o cronograma abaixo representam o CENARIO BASELINE (manual atual)."
            + RS
        )
    _mostrar_painel_hh_hm_pre_scheduler(demandas, fazenda, detalhado=False)
    if (not _batch) and confirmar("Exibir HH/HM detalhado por talhao?", default=False):
        _mostrar_painel_hh_hm_pre_scheduler(demandas, fazenda, detalhado=True)

    _result_sem_exec = _verificar_atividades_sem_executor(
        demandas, turmas, reatribuicao, paralelo, primaria, _batch, cfg,
    )
    if _result_sem_exec is None:
        return
    total_hh, total_custo, total_hm = _result_sem_exec

    sub()
    print(G + BL + "  GERANDO CRONOGRAMA (talhao a talhao)..." + RS + "\n")

    turma_filas, demanda_global, atividades_plantio, atividades_irrig, \
    tem_plantio_por_talhao = _construir_filas_e_demanda_global(
        turmas, talhoes_ordenados, demandas, reatribuicao, paralelo, primaria,
        atividades_reais, seq_cfg, modo_seq, usar_cascata,
    )
    dia_termino_plantio = {}

    config = _SchedulerLoopConfig(
        turmas=turmas,
        turma_filas=turma_filas,
        demanda_global=demanda_global,
        demandas=demandas,
        talhoes_ordenados=talhoes_ordenados,
        jornada=jornada,
        executores=executores,
        seq_cfg=seq_cfg,
        modo_seq=modo_seq,
        usar_cascata=usar_cascata,
        usar_bloqueio_global=usar_bloqueio_global,
        atividades_bloqueadas=atividades_bloqueadas,
        usar_reforco_automatico=usar_reforco_automatico,
        usar_pool_pos_bloqueio=usar_pool_pos_bloqueio,
        atividades_plantio=atividades_plantio,
        atividades_irrig=atividades_irrig,
        fazenda=fazenda,
        cfg=cfg,
        tarifas=tarifas,
        modo_somente_hh=modo_somente_hh,
        dia_termino_plantio=dia_termino_plantio,
        tem_plantio_por_talhao=tem_plantio_por_talhao,
    )
    cronograma, dia, demanda_global = _executar_scheduler_loop(config)



    cronograma_base, dias_simulado_hum, dias_simulado, dias_meta, \
    meses_simulado, hh_por_turma, n_demandas, n_fb, pct_fallback, \
    hm_only_list, cronograma_mec_base = _merge_cronograma_base_e_metricas(
            hm_only_atividades, demandas, cronograma, fazenda, jornada,
            cfg, tarifas, dia, mes_ref, ano_ref, prazo_meses,
            total_hh, executores,
        )

    recursos_mec, cronograma_mec, cronograma_com_mec, atividades_mec_set = \
        _executar_modo_mecanizado_opcional(
            _batch, modo_comparativo, substituicoes_comparativo,
            atividades_reais, cfg, hm_only_list, catalogo_global,
            demandas, fazenda, jornada, cronograma, turmas, executores,
            cronograma_base, cronograma_mec_base, dias_simulado,
        )

    _mostrar_tabela_ocupacao(
        turmas, dias_simulado_hum, jornada, hh_por_turma, cronograma,
        executores, usar_pool_pos_bloqueio, usar_bloqueio_global,
        n_fb, pct_fallback, n_demandas,
    )

    cenarios_rows = _executar_multi_fator_simulation(
        comparativo_cfg, _batch, recursos_mec, cronograma_com_mec,
        total_hh, dias_meta, executores, jornada,
    )

    audit = _auditar_escopo_cronograma(
        df_faz, cronograma_com_mec, cronograma_base, demandas, atividades_mec_set, recursos_mec,
    )
    atividades_escopo = audit["atividades_escopo"]
    escopo_set = audit["escopo_set"]
    ag_hum_set = audit["ag_hum_set"]
    ag_mec_set = audit["ag_mec_set"]
    faltantes_set = audit["faltantes_set"]
    df_audit = audit["df_audit"]

    _exportar_dossier_excel(
        cronograma_base, escopo_meta, fazenda, executores, jornada,
        prazo_meses, dias_meta, dias_simulado, meses_simulado,
        total_hh, total_custo, pct_fallback, n_fb,
        atividades_escopo, ag_hum_set, escopo_set, ag_mec_set, faltantes_set,
        recursos_mec, cronograma, turmas, dias_simulado_hum,
        cronograma_mec, cronograma_com_mec, cronograma_mec_base,
        df_audit, cenarios_rows, mes_ref, ano_ref, dia_ref, cfg,
    )

    _diagnostico_prazo(
        prazo_meses, dias_meta, mes_ref, ano_ref,
        dias_simulado, meses_simulado,
        executores, jornada, total_hh,
        recursos_mec, cronograma_com_mec,
    )

    preencher_orfas = False
    _ui_ctx = _ComparativoUIConfig(
        modo_comparativo=modo_comparativo,
        substituicoes_comparativo=substituicoes_comparativo,
        session_hh=session_hh,
    )
    _exec_ctx = _ComparativoExecutionConfig(
        cfg=cfg,
        df_faz=df_faz,
        fazenda=fazenda,
        modo_seq=modo_seq,
        usar_bloqueio_global=usar_bloqueio_global,
        usar_reforco_automatico=usar_reforco_automatico,
        usar_pool_pos_bloqueio=usar_pool_pos_bloqueio,
        prazo_meses=prazo_meses,
        mes_ref=mes_ref,
        ano_ref=ano_ref,
        data_inicio_txt=data_inicio_txt,
        data_fim_txt=data_fim_txt,
        jornada=jornada,
        executores=executores,
        turmas=turmas,
        preencher_orfas=preencher_orfas,
        reatribuicao=reatribuicao,
        paralelo=paralelo,
        primaria=primaria,
        escopo_meta=escopo_meta,
        atividades_catalogo=atividades_catalogo,
    )
    _result_ctx = _ComparativoResult(
        total_hh=total_hh,
        total_hm=total_hm,
        dias_simulado=dias_simulado,
    )
    resultado_mecanizado, resultado_mecanizado_valido = _executar_modo_comparativo(_ui_ctx, _exec_ctx, _result_ctx)

    resultado_final = _build_resultado_final(
        esperar_enter, fazenda, dias_simulado, meses_simulado,
        prazo_meses, dias_meta, total_hh, total_custo, total_hm,
        cronograma_base, turmas, resultado_mecanizado,
        resultado_mecanizado_valido, substituicoes_comparativo,
        recursos_mec, cronograma_com_mec, demandas,
    )

    return resultado_final


# ──────────────────────────────────────────────
# V6: ABAS EXCEL TIMELINE + OCUPACAO + PERFIS
# ──────────────────────────────────────────────

def _configurar_lote_global(cfg, todas_atvs):
    seq_cfg = cfg.get("sequencia") or {}
    _merge_sequencia_defaults(seq_cfg)
    cfg["sequencia"] = seq_cfg
    modo_seq = _selecionar_sequencia_padrao_sn(cfg, seq_cfg, todas_atvs)

    usar_bloqueio_global = False
    if modo_seq != "personalizado":
        usar_bloqueio_global = confirmar(
            "Aplicar BLOQUEIO GLOBAL (plantio/irrigacao so iniciam quando TODO o resto zerar)?",
            default=True,
        )
    usar_reforco_automatico = confirmar("Ativar REFORCO AUTOMATICO?", default=True)
    usar_pool_pos_bloqueio = False
    if usar_bloqueio_global:
        usar_pool_pos_bloqueio = confirmar(
            "Usar PELOTAO UNIFICADO apos liberacao global?", default=True
        )

    prazo_meses = pedir_float("Prazo META para conclusao (meses)", 6.0)
    prazo_absoluto = confirmar(
        f"  {prazo_meses} meses e o periodo ABSOLUTO? Se sim, havera sugestoes se necessario",
        default=True,
    )
    hoje = datetime.datetime.now()
    mes_ref = pedir_int("Mes inicial (1-12)", hoje.month)
    mes_ref = max(1, min(12, int(mes_ref)))
    ano_ref = pedir_int("Ano inicial", hoje.year)
    dia_max = calendar.monthrange(ano_ref, mes_ref)[1]
    dia_ref = pedir_int(f"Dia inicial (1-{dia_max})", min(hoje.day, dia_max))
    dia_ref = max(1, min(dia_max, int(dia_ref)))

    data_inicio_txt = _formatar_data_dia(dia_ref, mes_ref, ano_ref)
    data_fim_txt = None
    if confirmar("Informar dia final manualmente para o lote?", default=False):
        mes_fim = pedir_int("Mes final (1-12)", mes_ref)
        mes_fim = max(1, min(12, int(mes_fim)))
        ano_fim = pedir_int("Ano final", ano_ref)
        dia_max_fim = calendar.monthrange(ano_fim, mes_fim)[1]
        dia_fim = pedir_int(f"Dia final (1-{dia_max_fim})", min(dia_ref, dia_max_fim))
        dia_fim = max(1, min(dia_max_fim, int(dia_fim)))
        data_fim_txt = _formatar_data_dia(dia_fim, mes_fim, ano_fim)
    else:
        fim_calc = _calcular_data_fim_por_meses(dia_ref, mes_ref, ano_ref, prazo_meses)
        if fim_calc:
            data_fim_txt = _formatar_data_dia(fim_calc[0], fim_calc[1], fim_calc[2])

    contexto_sessao.definir_datas(data_inicio_txt, data_fim_txt)
    j_def = float(cfg.get("jornada_horas") or _JORNADA_DEFAULT_H)
    if j_def <= 0:
        j_def = _JORNADA_DEFAULT_H
    jornada = pedir_jornada("Jornada efetiva diaria (ex: 6.5 ou 6:30 = 6h30)", round(j_def, 2))
    cfg["jornada_horas"] = jornada
    salvar_config(cfg)

    return {
        "modo_seq": modo_seq,
        "usar_bloqueio_global": usar_bloqueio_global,
        "usar_reforco_automatico": usar_reforco_automatico,
        "usar_pool_pos_bloqueio": usar_pool_pos_bloqueio,
        "prazo_meses": prazo_meses,
        "prazo_absoluto": prazo_absoluto,
        "mes_ref": mes_ref,
        "ano_ref": ano_ref,
        "dia_ref": dia_ref,
        "data_inicio_txt": data_inicio_txt,
        "data_fim_txt": data_fim_txt,
        "jornada": jornada,
    }


def _configurar_equipe_template_lote(todas_atvs, jornada):
    sub()
    print(G + BL + "  CONFIGURAR EQUIPE PADRAO" + RS)
    print(DM + "  Defina as turmas que serao reutilizadas em todas as fazendas." + RS)
    print(DM + "  Voce podera ajustar antes de cada fazenda no checkpoint.\n" + RS)

    perfil_carregado = None
    perfis_existentes = _listar_perfis_equipe()
    if perfis_existentes:
        if confirmar("Carregar perfil de equipe salvo anteriormente?", default=False):
            perfil_carregado = _carregar_perfil_equipe_menu()

    if perfil_carregado:
        turmas = [
            {
                "nome": t["nome"],
                "operarios": t["operarios"],
                "atividades": list(t.get("atividades") or []),
            }
            for t in perfil_carregado.get("turmas", [])
        ]
        executores = perfil_carregado.get(
            "executores", sum(t["operarios"] for t in turmas)
        )
        ok(
            f"Perfil '{perfil_carregado['nome']}' carregado: {executores} executores, {len(turmas)} turma(s)."
        )
        for t in turmas:
            print(
                G
                + f"  - {t['nome']}: "
                + C
                + f"{t['operarios']} ops, {len(t.get('atividades', []))} atividades"
                + RS
            )
        if confirmar("Editar este perfil antes de usar?", default=False):
            for turma in turmas:
                menu_vincular_atividades_turma(turma, todas_atvs)
    else:
        executores = pedir_int(
            "Operarios totais da equipe padrao (quem realmente trabalha)",
            9,
        )
        if executores <= 0:
            erro("Precisa de pelo menos 1 executor.")
            return None, None

        turmas = []
        restantes = executores
        while restantes > 0:
            print(G + f"  Operarios disponiveis: {restantes}" + RS)
            nome_turma = prompt("Nome da turma", f"Turma {len(turmas) + 1}")
            def_pad = min(restantes, max(1, restantes // 2 or restantes))
            qtd = pedir_int(f"  Quantos operarios na turma '{nome_turma}'", def_pad)
            if qtd > restantes:
                qtd = restantes
            turmas.append({"nome": nome_turma, "operarios": qtd, "atividades": []})
            restantes -= qtd
            if restantes > 0:
                if not confirmar(
                    f"Criar outra turma? ({restantes} restantes)", default=True
                ):
                    turmas.append(
                        {"nome": "Geral", "operarios": restantes, "atividades": []}
                    )
                    restantes = 0

        sub()
        print(
            G
            + BL
            + "  VINCULAR ATIVIDADES (usa todas as atividades do escopo)"
            + RS
            + "\n"
        )
        for turma in turmas:
            menu_vincular_atividades_turma(turma, todas_atvs)

    if confirmar("Salvar este perfil de equipe para reusar depois?", default=False):
        nome_p = prompt("Nome do perfil", "padrao")
        cam_p = _salvar_perfil_equipe(turmas, executores, jornada, nome_p)
        ok(f"Perfil salvo: {cam_p}")

    return turmas, executores


def _executar_lote_continuo(cfg, df_scope, fazendas, ctx_base, prazo_absoluto, dias_meta, cap_ep_dia, jornada, todas_atvs):
    resultados = []
    dias_acumulados = 0
    for i_f, fz in enumerate(fazendas, 1):
        linha()
        print(C + BL + f"  [{i_f}/{len(fazendas)}] FAZENDA: {fz}" + RS)
        if prazo_absoluto:
            saldo_pre = dias_meta - dias_acumulados
            pct_consumido = (
                (dias_acumulados / dias_meta * 100) if dias_meta > 0 else 0.0
            )
            print(
                DM + f"  Meta: {dias_meta} dias | Consumido: {dias_acumulados} dias "
                f"({pct_consumido:.0f}%) | Saldo: {saldo_pre} dias" + RS
            )
            if pct_consumido >= 100:
                print(
                    Y + BL + "  !! META GLOBAL JA EXCEDIDA antes desta fazenda !!" + RS
                )
            elif pct_consumido >= 80:
                print(
                    Y + f"  ! Atencao: {pct_consumido:.0f}% da meta ja consumida." + RS
                )
        linha()

        if i_f > 1:
            turmas = _checkpoint_editar_template(ctx_base["turmas"], todas_atvs)
            ctx_base["turmas"] = turmas
            ctx_base["executores"] = sum(t["operarios"] for t in turmas)

        try:
            r = calcular_cronograma_inteligente(
                cfg,
                df_scope[df_scope["fazenda"] == fz].copy(),
                fz,
                esperar_enter=False,
                ctx=dict(ctx_base),
            )
        except Exception as _err_faz:
            erro(f"Falha ao processar fazenda {fz}: {_err_faz}")
            traceback.print_exc()
            r = None
        if r:
            dias_faz = int(r.get("dias_simulado", 0))
            dia_inicio_acum = dias_acumulados + 1
            dias_acumulados += dias_faz
            r["dia_inicio_acumulado"] = dia_inicio_acum
            r["dia_fim_acumulado"] = dias_acumulados
            r["saldo_meta_apos"] = max(0, dias_meta - dias_acumulados)
            r["pct_meta_consumida"] = round(
                (dias_acumulados / dias_meta * 100) if dias_meta > 0 else 0.0, 1
            )
            if dias_acumulados > dias_meta:
                r["status_meta_continuo"] = "EXCEDIDO"
            elif dias_acumulados >= dias_meta * 0.8:
                r["status_meta_continuo"] = "RISCO"
            else:
                r["status_meta_continuo"] = "OK"

            hh_faz = float(r.get("total_hh", 0))
            rec = _recomendar_equipes_padrao(
                hh_faz, dias_meta, cap_ep_dia, jornada, prazo_absoluto
            )
            r["rec_ep"] = rec
            if rec and prazo_absoluto:
                _imprimir_recomendacao_ep(rec, fz, prazo_absoluto)

            if prazo_absoluto:
                st_lbl = r["status_meta_continuo"]
                cor_st = G if st_lbl == "OK" else (Y if st_lbl == "RISCO" else R)
                sub()
                print(cor_st + BL + f"  LOTE CONTINUO — apos '{fz}':" + RS)
                print(
                    cor_st + f"  Dia {dia_inicio_acum} a {dias_acumulados} | "
                    f"Saldo: {r['saldo_meta_apos']} dias | "
                    f"Consumo: {r['pct_meta_consumida']:.0f}% | "
                    f"Status: {st_lbl}" + RS
                )
            resultados.append(r)

    return resultados, dias_acumulados


def _exibir_consolidado_lote(resultados, dias_acumulados, dias_meta, turmas, jornada, cap_ep_dia, prazo_meses, prazo_absoluto, modo_seq, data_inicio_txt, data_fim_txt, preencher_orfas_template, empresa_filtro, nome_arquivo_micro, cfg):
    if not resultados:
        return
    linha()
    print(G + BL + "  CONSOLIDADO FINAL (TODAS AS FAZENDAS)" + RS)
    tit_cons = (
        f"Consolidado — {empresa_filtro}"
        if empresa_filtro
        else "Consolidado — todas as empresas (sem filtro EQUIPE)"
    )
    t_all = Table(title=tit_cons)
    t_all.add_column("Metrica", style="cyan")
    t_all.add_column("Valor", justify="right")
    t_all.add_row("Fazendas processadas", str(len(resultados)))
    t_all.add_row(
        "HH total (soma)",
        f"{sum(float(x.get('total_hh', 0)) for x in resultados):,.1f}",
    )
    dias_max_isolado = max(int(x.get("dias_simulado", 0)) for x in resultados)
    t_all.add_row("Dias simulados (maior fazenda isolada)", str(dias_max_isolado))
    t_all.add_row("Dias acumulados lote continuo", str(dias_acumulados))
    t_all.add_row("Meta (dias uteis)", str(dias_meta))
    if dias_meta > 0:
        saldo_final = max(0, dias_meta - dias_acumulados)
        st_final = "DENTRO" if dias_acumulados <= dias_meta else "EXCEDIDO"
        cor_final = "[green]" if st_final == "DENTRO" else "[red]"
        t_all.add_row(
            "Saldo apos todas as fazendas", f"{cor_final}{saldo_final} dias[/]"
        )
        t_all.add_row("Status meta global", f"{cor_final}{st_final}[/]")
    d_mec_vals = [
        int(x.get("dias_mecanizado") or 0)
        for x in resultados
        if x.get("dias_mecanizado")
    ]
    if d_mec_vals:
        t_all.add_row("Dias cenario mecanizado (max)", str(max(d_mec_vals)))
        t_all.add_row(
            "Ganho mecanizado total (dias)",
            f"{sum(int(x.get('ganho_mecanizado_dias', 0)) for x in resultados):+d}",
        )
    console.print(t_all)

    if prazo_absoluto:
        sub()
        print(G + BL + "  ANALISE EQUIPE PADRAO — CONSOLIDADO" + RS)
        ep_cap = sum(t["operarios"] for t in turmas)
        print(
            G
            + f"  Equipe padrao: {ep_cap} executores @ {jornada}h/dia = {cap_ep_dia:.1f} HH/dia"
            + RS
        )
        print(
            G + f"  Meta: {prazo_meses} meses = {dias_meta} dias uteis (ABSOLUTO)" + RS
        )

        t_ep = Table(title=f"Cascata de execucao — {tit_cons}")
        t_ep.add_column("Fazenda", style="cyan")
        t_ep.add_column("HH", justify="right")
        if not modo_somente_hh(cfg):
            t_ep.add_column("Custo R$", justify="right")
        t_ep.add_column("Dias", justify="right")
        t_ep.add_column("Inicio", justify="right")
        t_ep.add_column("Fim", justify="right")
        t_ep.add_column("Meta consumida", justify="right")
        t_ep.add_column("Saldo", justify="right")
        t_ep.add_column("Status", justify="center")
        for r in resultados:
            pct = r.get("pct_meta_consumida", 0)
            st = r.get("status_meta_continuo", "?")
            if st == "OK":
                cor_st = "[green]"
            elif st == "RISCO":
                cor_st = "[yellow]"
            else:
                cor_st = "[red]"
            t_ep.add_row(
                str(r["fazenda"])[:28],
                f"{float(r.get('total_hh', 0)):,.1f}",
                *([f"R$ {float(r.get('total_custo', 0)):,.2f}"] if not modo_somente_hh(cfg) else []),
                str(r.get("dias_simulado", 0)),
                f"Dia {r.get('dia_inicio_acumulado', '?')}",
                f"Dia {r.get('dia_fim_acumulado', '?')}",
                f"{pct:.0f}%",
                f"{r.get('saldo_meta_apos', '?')} dias",
                f"{cor_st}{st}[/]",
            )
        hh_total_all = sum(float(x.get("total_hh", 0)) for x in resultados)
        st_global = "OK" if dias_acumulados <= dias_meta else "EXCEDIDO"
        cor_g = "[green]" if st_global == "OK" else "[red]"
        t_ep.add_row(
            "TOTAL",
            f"{hh_total_all:,.1f}",
            *([f"R$ {sum(float(x.get('total_custo', 0)) for x in resultados):,.2f}"] if not modo_somente_hh(cfg) else []),
            str(dias_acumulados),
            "Dia 1",
            f"Dia {dias_acumulados}",
            f"{(dias_acumulados / dias_meta * 100) if dias_meta > 0 else 0:.0f}%",
            f"{max(0, dias_meta - dias_acumulados)} dias",
            f"{cor_g}{st_global}[/]",
        )
        console.print(t_ep)

    _exportar_excel_consolidado_lote(
        resultados,
        empresa_filtro=empresa_filtro,
        nome_arquivo_micro=nome_arquivo_micro,
        extras={
            "Prazo_meses": prazo_meses,
            "Meta_absoluta": prazo_absoluto,
            "Modo_sequencia": modo_seq,
            "Jornada_h": jornada,
            "Executores_equipe_padrao": sum(t["operarios"] for t in turmas),
            "Preencher_orfas_auto": preencher_orfas_template,
            "Dias_meta": dias_meta,
            "Dias_acumulados_lote": dias_acumulados,
            "Data_inicio": data_inicio_txt,
            "Data_termino": data_fim_txt,
        },
    )

    linha()
    esperar("ENTER para voltar ao menu")


def _executar_lote_fazendas(
    cfg, df_scope, fazendas, empresa_filtro=None, nome_arquivo_micro=""
):
    """Orchestrate all-farms batch: one-time setup, per-farm checkpoint, consolidated report."""
    dashboard_header()
    subcabecalho("CONFIGURACAO GLOBAL — TODAS AS FAZENDAS")

    todas_atvs = sorted(
        {_norm_atv(x) for x in df_scope["atividade"].dropna().unique() if _norm_atv(x)},
        key=str,
    )

    glb = _configurar_lote_global(cfg, todas_atvs)
    turmas, executores = _configurar_equipe_template_lote(todas_atvs, glb["jornada"])
    if turmas is None:
        return

    preencher_orfas_template = confirmar(
        "  Por fazenda: distribuir automaticamente demandas sem turma para a turma com mais operarios?",
        default=False,
    )

    cap_ep_dia = float(executores) * float(glb["jornada"])
    dias_meta = dias_uteis_no_periodo(glb["mes_ref"], glb["ano_ref"], glb["prazo_meses"])

    ctx_base = {
        "modo_seq": glb["modo_seq"],
        "usar_bloqueio_global": glb["usar_bloqueio_global"],
        "usar_reforco_automatico": glb["usar_reforco_automatico"],
        "usar_pool_pos_bloqueio": glb["usar_pool_pos_bloqueio"],
        "prazo_meses": glb["prazo_meses"],
        "mes_ref": glb["mes_ref"],
        "ano_ref": glb["ano_ref"],
        "data_inicio_txt": glb["data_inicio_txt"],
        "data_fim_txt": glb["data_fim_txt"],
        "jornada": glb["jornada"],
        "executores": executores,
        "turmas": turmas,
        "penalidade": 1.0,
        "preencher_orfas_template": preencher_orfas_template,
    }

    resultados, dias_acumulados = _executar_lote_continuo(
        cfg, df_scope, fazendas, ctx_base, glb["prazo_absoluto"], dias_meta,
        cap_ep_dia, glb["jornada"], todas_atvs,
    )

    if resultados:
        _exibir_consolidado_lote(
            resultados, dias_acumulados, dias_meta, turmas, glb["jornada"],
            cap_ep_dia, glb["prazo_meses"], glb["prazo_absoluto"], glb["modo_seq"],
            glb["data_inicio_txt"], glb["data_fim_txt"],
            preencher_orfas_template, empresa_filtro, nome_arquivo_micro, cfg,
        )


# ──────────────────────────────────────────────
#  V6: MODO MULTI-EQUIPES
# ──────────────────────────────────────────────


def _configurar_data_multi_equipes():
    hoje = datetime.datetime.now()
    mes_ref = pedir_int("Mes inicial (1-12)", hoje.month)
    mes_ref = max(1, min(12, int(mes_ref)))
    ano_ref = pedir_int("Ano inicial", hoje.year)
    dia_max = calendar.monthrange(ano_ref, mes_ref)[1]
    dia_ref = pedir_int(f"Dia inicial (1-{dia_max})", min(hoje.day, dia_max))
    dia_ref = max(1, min(dia_max, int(dia_ref)))
    data_inicio_txt = _formatar_data_dia(dia_ref, mes_ref, ano_ref)
    return mes_ref, ano_ref, dia_ref, data_inicio_txt


def _agrupar_e_sugerir_equipes(cfg, fazendas, df_scope, n_equipes):
    usar_modo_empresa = False
    config_empresa = None

    fazendas_por_empresa = _agrupar_fazendas_por_empresa(df_scope)

    if fazendas_por_empresa:
        n_emp = len(fazendas_por_empresa)
        if confirmar(
            f"Distribuir {len(fazendas)} fazenda(s) automaticamente por empresa ({n_emp} empresa(s) detectada(s) no micro)?",
            default=True,
        ):
            dashboard_header()
            subcabecalho("DISTRIBUICAO POR EMPRESA")
            print(DM + " Agrupando fazendas por empresa..." + RS)

            config_empresa = _sugerir_config_empresa(fazendas_por_empresa, cfg)

            print(G + BL + "\n Distribuicao detectada:" + RS)
            for sug in config_empresa["sugestoes"]:
                print(
                    G
                    + f" [{sug['nome_empresa']}]: "
                    + C
                    + f"{sug['n_fazendas']} fazenda(s), "
                    + f"{sug['n_equipes']} equipe(s) "
                    + f"({sug['total_operarios']} operarios)"
                    + RS
                )
                for f in sug["fazendas"]:
                    cidade = _detectar_cidade_por_fazenda(f)
                    cidade_str = f" ({cidade})" if cidade else ""
                    print(DM + f" - {f}{cidade_str}" + RS)

            fazendas_com_empresa = set()
            for fazs in fazendas_por_empresa.values():
                fazendas_com_empresa.update(fazs)
            nao_id = [f for f in fazendas if f not in fazendas_com_empresa]
            if nao_id:
                print(Y + f"\n Fazendas sem empresa no micro ({len(nao_id)}):" + RS)
                for f in nao_id[:5]:
                    print(Y + f" - {f}" + RS)
                if len(nao_id) > 5:
                    print(Y + f" ... e mais {len(nao_id) - 5}" + RS)

            print(
                G + BL
                + f"\n Total: {config_empresa['total_equipes']} equipes, "
                + f"{config_empresa['total_operarios']} operarios"
                + RS
            )

            if confirmar("Aceitar esta distribuicao automatica?", default=True):
                usar_modo_empresa = True
                n_equipes = config_empresa["total_equipes"]
                ok(f"Modo empresa ativado: {n_emp} empresa(s), {n_equipes} equipes automaticas.")
            else:
                aviso("Modo automatico cancelado. Prossiga com configuracao manual.")

            sub()
            esperar("ENTER para continuar")

    if not usar_modo_empresa and confirmar(
        "Usar modo automatico de distribuicao por territorio/cidade?",
        default=False,
    ):
        dashboard_header()
        subcabecalho("DISTRIBUICAO POR TERRITORIO")
        print(DM + " Analisando fazendas e distribuindo por cidade..." + RS)

        distribuicao, nao_id = _distribuir_fazendas_por_territorio(fazendas)

        print(G + BL + "\n Distribuicao por cidade:" + RS)
        for cidade, fazs in distribuicao.items():
            if fazs:
                print(
                    G + f" [{cidade}]: " + C + f"{len(fazs)} fazenda(s)" + RS
                )
                for f in fazs:
                    print(DM + f" - {f}" + RS)

        if nao_id:
            print(Y + f"\n Fazendas nao identificadas ({len(nao_id)}):" + RS)
            for f in nao_id[:5]:
                print(Y + f" - {f}" + RS)
            if len(nao_id) > 5:
                print(Y + f" ... e mais {len(nao_id) - 5}" + RS)

        n_equipes = sum(1 for v in distribuicao.values() if v) or 1
        ok(f"Modo territorio: {n_equipes} grupo(s) por cidade.")
        usar_modo_empresa = True

        config_empresa = {
            "sugestoes": [
                {
                    "empresa": cidade,
                    "nome_empresa": cidade,
                    "n_equipes": 1,
                    "operarios_por_equipe": 10,
                    "coordenadores_por_equipe": 1,
                    "total_por_equipe": 11,
                    "total_operarios": 10,
                    "total_coordenadores": 1,
                    "total_geral": 11,
                    "jornada": 4.3,
                    "fazendas": fazs,
                    "n_fazendas": len(fazs),
                }
                for cidade, fazs in distribuicao.items()
                if fazs
            ],
            "total_equipes": n_equipes,
            "total_operarios": n_equipes * 10,
        }

        sub()
        esperar("ENTER para continuar")

    return usar_modo_empresa, config_empresa, n_equipes


def _configurar_uma_equipe(ie, n_equipes, todas_atvs, fazendas_restantes, mes_ref, ano_ref, dia_ref, data_inicio_txt, modo_seq, usar_modo_empresa, config_empresa):
    sub()
    print(G + BL + f" EQUIPE {ie}/{n_equipes}" + RS)

    if usar_modo_empresa and config_empresa:
        cfg_empresa_eq = None
        equipe_idx_atual = ie - 1
        acum_equipes = 0

        for sug in config_empresa["sugestoes"]:
            n_eq_emp = sug["n_equipes"]
            if equipe_idx_atual < acum_equipes + n_eq_emp:
                nome_eq = f"{sug['nome_empresa']} Eq{equipe_idx_atual - acum_equipes + 1}"
                j_eq = sug.get("jornada", 4.3)
                exec_eq = sug["operarios_por_equipe"]
                turmas_eq = [
                    {
                        "nome": sug["nome_empresa"],
                        "operarios": exec_eq,
                        "atividades": [],
                    }
                ]
                fazs_emp = sug["fazendas"]
                n_por_eq = max(1, len(fazs_emp) // n_eq_emp)
                inicio_emp = equipe_idx_atual - acum_equipes
                faz_eq = fazs_emp[inicio_emp:inicio_emp + n_por_eq]
                if equipe_idx_atual - acum_equipes + 1 == n_eq_emp and len(fazs_emp) > inicio_emp + n_por_eq:
                    faz_eq = fazs_emp[inicio_emp:]

                if not faz_eq:
                    aviso(f"{nome_eq}: nenhuma fazenda atribuivel — pulando equipe.")
                    return None

                ok(f"Configuracao automatica: {nome_eq}")
                print(G + f" Empresa: {sug['nome_empresa']}" + RS)
                print(G + f" Operarios: {exec_eq}" + RS)
                print(G + f" Fazendas: {len(faz_eq)}" + RS)
                for f in faz_eq:
                    if f in fazendas_restantes:
                        fazendas_restantes.remove(f)
                prazo_eq = pedir_float(f"Prazo meta para '{nome_eq}' (meses)", 3.0)
                data_fim_txt = _perguntar_data_fim_equipe(nome_eq, mes_ref, ano_ref, dia_ref, prazo_eq)
                return {
                    "nome": nome_eq,
                    "prazo_meses": prazo_eq,
                    "jornada": j_eq,
                    "executores": exec_eq,
                    "turmas": turmas_eq,
                    "fazendas": faz_eq,
                    "modo_seq": modo_seq,
                    "mes_ref": mes_ref,
                    "ano_ref": ano_ref,
                    "data_inicio_txt": data_inicio_txt,
                    "data_fim_txt": data_fim_txt,
                }
            acum_equipes += n_eq_emp

    # Manual config
    nome_eq = prompt(f"Nome da equipe {ie}", f"Equipe {ie}")
    prazo_eq = pedir_float(f"Prazo meta para '{nome_eq}' (meses)", 3.0)
    j_eq = pedir_float(f"Jornada diaria '{nome_eq}' (horas)", 4.3)
    exec_eq = pedir_int(f"Executores '{nome_eq}'", 10)
    data_fim_txt = _perguntar_data_fim_equipe(nome_eq, mes_ref, ano_ref, dia_ref, prazo_eq)

    perfil_carregado = None
    perfis = _listar_perfis_equipe()
    if perfis and confirmar(f"Carregar perfil de equipe para '{nome_eq}'?", default=False):
        perfil_carregado = _carregar_perfil_equipe_menu()

    if perfil_carregado:
        turmas_eq = [
            {
                "nome": t["nome"],
                "operarios": t["operarios"],
                "atividades": list(t.get("atividades") or []),
            }
            for t in perfil_carregado.get("turmas", [])
        ]
        exec_eq = sum(t["operarios"] for t in turmas_eq)
        ok(f"Perfil carregado: {len(turmas_eq)} turma(s), {exec_eq} executores.")
    else:
        turmas_eq = [{"nome": nome_eq, "operarios": exec_eq, "atividades": []}]
        menu_vincular_atividades_turma(turmas_eq[0], todas_atvs)

    if not fazendas_restantes:
        aviso("Todas as fazendas ja foram atribuidas. Esta equipe ficara vazia.")
        faz_eq = []
    elif ie == n_equipes:
        faz_eq = list(fazendas_restantes)
        ok(f"Restantes ({len(faz_eq)}) atribuidas a '{nome_eq}'.")
        for f in faz_eq:
            if f in fazendas_restantes:
                fazendas_restantes.remove(f)
    else:
        print(G + f"\n Fazendas disponiveis ({len(fazendas_restantes)}):" + RS)
        for idx_f, f in enumerate(fazendas_restantes, 1):
            print(G + f" {idx_f:3}. " + C + f + RS)
        sel_txt = prompt(
            f"Indices das fazendas para '{nome_eq}' (ex: 1,3,5-7) ou ENTER=todas restantes", "",
        )
        if not sel_txt.strip():
            faz_eq = list(fazendas_restantes)
        else:
            idxs = parse_intervalos_escolha(sel_txt, len(fazendas_restantes))
            faz_eq = [fazendas_restantes[i] for i in idxs]
        for f in faz_eq:
            if f in fazendas_restantes:
                fazendas_restantes.remove(f)
        ok(f"{len(faz_eq)} fazenda(s) para '{nome_eq}'.")

    return {
        "nome": nome_eq,
        "prazo_meses": prazo_eq,
        "jornada": j_eq,
        "executores": exec_eq,
        "turmas": turmas_eq,
        "fazendas": faz_eq,
        "modo_seq": modo_seq,
        "mes_ref": mes_ref,
        "ano_ref": ano_ref,
        "data_inicio_txt": data_inicio_txt,
        "data_fim_txt": data_fim_txt,
    }


def _perguntar_data_fim_equipe(nome_equipe, mes_ref, ano_ref, dia_ref, prazo_eq):
    if confirmar(f"Informar dia final manualmente para '{nome_equipe}'?", default=False):
        mes_fim = pedir_int("Mes final (1-12)", mes_ref)
        mes_fim = max(1, min(12, int(mes_fim)))
        ano_fim = pedir_int("Ano final", ano_ref)
        dia_max_fim = calendar.monthrange(ano_fim, mes_fim)[1]
        dia_fim = pedir_int(f"Dia final (1-{dia_max_fim})", min(dia_ref, dia_max_fim))
        dia_fim = max(1, min(dia_max_fim, int(dia_fim)))
        return _formatar_data_dia(dia_fim, mes_fim, ano_fim)
    fim_calc = _calcular_data_fim_por_meses(dia_ref, mes_ref, ano_ref, prazo_eq)
    if fim_calc:
        return _formatar_data_dia(fim_calc[0], fim_calc[1], fim_calc[2])
    return None


def _processar_equipes_e_consolidar(cfg, df_scope, equipes_config, empresa_filtro, nome_arquivo_micro):
    all_eq_results = []
    for ec in equipes_config:
        linha()
        print(G + BL + f"  PROCESSANDO EQUIPE: {ec['nome']} ({len(ec['fazendas'])} fazendas)" + RS)
        linha()

        dias_meta_eq = dias_uteis_no_periodo(ec["mes_ref"], ec["ano_ref"], ec["prazo_meses"])
        cap_eq_dia = float(ec["executores"]) * float(ec["jornada"])
        eq_resultados = []
        dias_acum_eq = 0

        ctx_eq = {
            "modo_seq": ec["modo_seq"],
            "usar_bloqueio_global": False,
            "usar_reforco_automatico": True,
            "usar_pool_pos_bloqueio": False,
            "prazo_meses": ec["prazo_meses"],
            "mes_ref": ec["mes_ref"],
            "ano_ref": ec["ano_ref"],
            "data_inicio_txt": ec.get("data_inicio_txt"),
            "data_fim_txt": ec.get("data_fim_txt"),
            "jornada": ec["jornada"],
            "executores": ec["executores"],
            "turmas": ec["turmas"],
            "penalidade": 1.0,
            "preencher_orfas_template": True,
        }
        contexto_sessao.atualizar_modo("multi_equipes")
        contexto_sessao.atualizar_equipe(ec["nome"])
        contexto_sessao.definir_datas(ec.get("data_inicio_txt"), ec.get("data_fim_txt"))
        _emitir_monitor_atual()
        _emitir_monitor_state({
            "operacao": {
                "modo": "multi_equipes",
                "equipe_atual": str(ec["nome"]),
                "status_geral": "processando_equipe",
                "mensagem_curta": f"Equipe {ec['nome']} ({len(ec['fazendas'])} fazendas)",
            },
            "lote": {
                "dias_meta": int(dias_meta_eq),
                "dias_consumidos": int(dias_acum_eq),
                "saldo_dias": int(max(0, int(dias_meta_eq) - int(dias_acum_eq))),
                "fazenda_indice": 0,
                "n_fazendas": int(len(ec["fazendas"])),
                "status_meta_continuo": "OK",
                "prazo_absoluto": True,
            },
        })

        for fz in ec["fazendas"]:
            r = calcular_cronograma_inteligente(
                cfg, df_scope[df_scope["fazenda"] == fz].copy(), fz,
                esperar_enter=False, ctx=dict(ctx_eq),
            )
            if r:
                dias_faz = int(r.get("dias_simulado", 0))
                r["dia_inicio_acumulado"] = dias_acum_eq + 1
                dias_acum_eq += dias_faz
                r["dia_fim_acumulado"] = dias_acum_eq
                r["saldo_meta_apos"] = max(0, dias_meta_eq - dias_acum_eq)
                r["pct_meta_consumida"] = round(
                    (dias_acum_eq / dias_meta_eq * 100) if dias_meta_eq > 0 else 0.0, 1
                )
                r["status_meta_continuo"] = (
                    "EXCEDIDO" if dias_acum_eq > dias_meta_eq
                    else ("RISCO" if dias_acum_eq >= dias_meta_eq * 0.8 else "OK")
                )
                eq_resultados.append(r)

        all_eq_results.append({
            "equipe": ec["nome"],
            "executores": ec["executores"],
            "jornada": ec["jornada"],
            "prazo_meses": ec["prazo_meses"],
            "data_inicio_txt": ec.get("data_inicio_txt"),
            "data_fim_txt": ec.get("data_fim_txt"),
            "dias_meta": dias_meta_eq,
            "dias_acumulados": dias_acum_eq,
            "hh_total": sum(float(x.get("total_hh", 0)) for x in eq_resultados),
            "total_custo": sum(float(x.get("total_custo", 0)) for x in eq_resultados),
            "n_fazendas": len(ec["fazendas"]),
            "status": "DENTRO" if dias_acum_eq <= dias_meta_eq else "EXCEDIDO",
            "resultados_fazendas": eq_resultados,
        })

    linha()
    print(G + BL + "  CONSOLIDADO MULTI-EQUIPES" + RS)
    t_meq = Table(title="Comparativo entre equipes")
    t_meq.add_column("Equipe", style="cyan")
    t_meq.add_column("Exec.", justify="right")
    t_meq.add_column("Fazendas", justify="right")
    t_meq.add_column("HH", justify="right")
    if not modo_somente_hh(cfg):
        t_meq.add_column("Custo R$", justify="right")
    t_meq.add_column("Dias acum.", justify="right")
    t_meq.add_column("Meta (dias)", justify="right")
    t_meq.add_column("Saldo", justify="right")
    t_meq.add_column("Status", justify="center")
    for eq in all_eq_results:
        saldo = max(0, eq["dias_meta"] - eq["dias_acumulados"])
        st = eq["status"]
        cor = "[green]" if st == "DENTRO" else "[red]"
        t_meq.add_row(
            eq["equipe"], str(eq["executores"]), str(eq["n_fazendas"]),
            f"{eq['hh_total']:,.1f}",
            *([f"R$ {eq.get('total_custo', 0):,.2f}"] if not modo_somente_hh(cfg) else []),
            str(eq["dias_acumulados"]), str(eq["dias_meta"]),
            f"{saldo} dias", f"{cor}{st}[/]",
        )
    console.print(t_meq)

    try:
        pasta = OUTPUT_DIR
        os.makedirs(pasta, exist_ok=True)
        emp_slug = _slug_ficheiro_seguro(empresa_filtro) if empresa_filtro else "Todas"
        nome_xlsx = f"MultiEquipes_{emp_slug}.xlsx"
        caminho = os.path.join(pasta, nome_xlsx)
        rows_eq = []
        for eq in all_eq_results:
            for r in eq["resultados_fazendas"]:
                rows_eq.append({
                    "Equipe": eq["equipe"],
                    "Data_inicio": eq.get("data_inicio_txt"),
                    "Data_termino": eq.get("data_fim_txt"),
                    "Fazenda": r.get("fazenda"),
                    "Dias": r.get("dias_simulado"),
                    "Dia_inicio_acum": r.get("dia_inicio_acumulado"),
                    "Dia_fim_acum": r.get("dia_fim_acumulado"),
                    "Meta_consumida_%": r.get("pct_meta_consumida"),
                    "Saldo": r.get("saldo_meta_apos"),
                    "Status": r.get("status_meta_continuo"),
                    "HH": r.get("total_hh"),
                    "Custo_MO": r.get("total_custo") if not modo_somente_hh(cfg) else None,
                })
        rows_sumario = [
            {
                "Equipe": eq["equipe"],
                "Data_inicio": eq.get("data_inicio_txt"),
                "Data_termino": eq.get("data_fim_txt"),
                "Executores": eq["executores"],
                "Jornada": eq["jornada"],
                "Fazendas": eq["n_fazendas"],
                "HH_total": eq["hh_total"],
                "Custo_total": eq.get("total_custo", 0) if not modo_somente_hh(cfg) else None,
                "Dias_acumulados": eq["dias_acumulados"],
                "Meta_dias": eq["dias_meta"],
                "Status": eq["status"],
            }
            for eq in all_eq_results
        ]
        with pd.ExcelWriter(caminho, engine="openpyxl") as w:
            pd.DataFrame(rows_sumario).to_excel(w, sheet_name="SUMARIO_EQUIPES", index=False)
            pd.DataFrame(rows_eq).to_excel(w, sheet_name="DETALHE_POR_FAZENDA", index=False)
        ok(f"Multi-equipes exportado: {nome_xlsx}")
    except Exception as ex:
        aviso(f"Erro ao exportar multi-equipes: {ex}")

    linha()
    esperar("ENTER para voltar ao menu")


def _executar_multi_equipes(
    cfg, df_scope, fazendas, empresa_filtro=None, nome_arquivo_micro=""
):
    """Modo avançado: N equipes independentes, cada uma com carteira de fazendas e meta própria."""
    dashboard_header()
    subcabecalho("MODO MULTI-EQUIPES")
    print(DM + "  Cada equipe tera sua propria configuracao, meta e carteira de fazendas." + RS)
    print(DM + "  Ao final, um consolidado comparativo mostra a situacao de cada equipe.\n" + RS)

    n_equipes = pedir_int("Quantas equipes independentes?", 2)
    if n_equipes < 1:
        aviso("Precisa de pelo menos 1 equipe.")
        return

    todas_atvs = sorted(
        {_norm_atv(x) for x in df_scope["atividade"].dropna().unique() if _norm_atv(x)},
        key=str,
    )

    seq_cfg = cfg.get("sequencia") or {}
    _merge_sequencia_defaults(seq_cfg)
    cfg["sequencia"] = seq_cfg
    modo_seq = _selecionar_sequencia_padrao_sn(cfg, seq_cfg, todas_atvs)

    mes_ref, ano_ref, dia_ref, data_inicio_txt = _configurar_data_multi_equipes()

    usar_modo_empresa, config_empresa, n_equipes = _agrupar_e_sugerir_equipes(
        cfg, fazendas, df_scope, n_equipes,
    )

    equipes_config = []
    fazendas_restantes = list(fazendas)

    for ie in range(1, n_equipes + 1):
        ec = _configurar_uma_equipe(
            ie, n_equipes, todas_atvs, fazendas_restantes,
            mes_ref, ano_ref, dia_ref, data_inicio_txt, modo_seq,
            usar_modo_empresa, config_empresa,
        )
        if ec:
            equipes_config.append(ec)

    if usar_modo_empresa and fazendas_restantes:
        orfas = list(fazendas_restantes)
        if equipes_config:
            maior = max(equipes_config, key=lambda e: len(e["fazendas"]))
            maior["fazendas"] = maior["fazendas"] + orfas
            ok(f"{len(orfas)} fazenda(s) orfa(s) (sem empresa) atribuidas a '{maior['nome']}'.")
        else:
            n_equipes += 1
            nome_orfa = f"Equipe Orfa {n_equipes}"
            equipes_config.append({
                "nome": nome_orfa, "prazo_meses": 3.0, "jornada": 4.3,
                "executores": 10,
                "turmas": [{"nome": nome_orfa, "operarios": 10, "atividades": []}],
                "fazendas": orfas, "modo_seq": modo_seq,
                "mes_ref": mes_ref, "ano_ref": ano_ref,
                "data_inicio_txt": data_inicio_txt, "data_fim_txt": None,
            })
            ok(f"{len(orfas)} fazenda(s) orfa(s) atribuidas a '{nome_orfa}' (equipe extra).")
        fazendas_restantes.clear()

    if equipes_config:
        _processar_equipes_e_consolidar(cfg, df_scope, equipes_config, empresa_filtro, nome_arquivo_micro)


