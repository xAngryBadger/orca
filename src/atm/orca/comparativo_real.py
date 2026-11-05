"""Comparativo multi-fator com o SCHEDULER REAL.

A aproximação antiga (`simular_cenarios_multifator` em comparativo_mec.py)
faz `dias = ceil(HH / (equipes * jornada))`, o que ignora cascata por talhão,
bloqueio global plantio/irrigação, pool pós-bloqueio, reforço automático e
HM-paralelo. Para uma fazenda com muitas fases encadeadas ela subestima os
dias de forma grotesca — a auditoria marcou isso como P0.

Aqui cada cenário roda o `_executar_scheduler_loop` de verdade, com as
regras reais de `config._default_sequencia_dict()`. Custo computacional
maior, resultado confiável.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from .config import _default_sequencia_dict, modo_somente_hh
from .engine_pkg import _executar_scheduler_loop


def _config_cenario(
    demanda: Dict[Any, float],
    turmas: List[Dict[str, Any]],
    jornada: float,
    seq_cfg: Optional[Dict[str, Any]] = None,
    usando_cascata: bool = True,
    usando_bloqueio: bool = True,
    usando_pool: bool = True,
    usando_reforco: bool = True,
):
    seq = dict(seq_cfg or _default_sequencia_dict())
    atividades = {a for (_t, a) in demanda}
    plantio = {a for a in atividades if "plantio" in str(a).lower()}
    irrig = {a for a in atividades if "irrig" in str(a).lower()}
    talhoes = sorted({t for (t, _a) in demanda})

    filas = {
        t["nome"]: [
            {"talhao": th, "atividade": a, "hh_rest": v}
            for (th, a), v in demanda.items()
        ]
        for t in turmas
    }

    from .engine_pkg import _construir_demandas

    class _C:
        pass

    c = _C()
    c.turmas = turmas
    c.turma_filas = filas
    c.demanda_global = dict(demanda)
    c.demandas = {
        th: [
            {"atividade": a, "hh_total": v, "area": 0.0}
            for (tt, a), v in demanda.items()
            if th == tt
        ]
        for th in talhoes
    }
    c.talhoes_ordenados = talhoes
    c.jornada = float(jornada)
    c.executores = sum(int(t["operarios"]) for t in turmas)
    c.seq_cfg = seq
    c.modo_seq = seq.get("modo", "implantacao")
    c.usar_cascata = usando_cascata
    c.usar_bloqueio_global = usando_bloqueio
    c.atividades_bloqueadas = plantio | irrig
    c.usar_reforco_automatico = usando_reforco
    c.usar_pool_pos_bloqueio = usando_pool
    c.atividades_plantio = plantio
    c.atividades_irrig = irrig
    c.fazenda = "CENARIO"
    c.cfg = {}
    c.tarifas = {}
    c.modo_somente_hh = modo_somente_hh
    c.dia_termino_plantio = {}
    c.tem_plantio_por_talhao = {th: True for th in talhoes}
    return c


def simular_cenario_real(
    demanda: Dict[Any, float],
    executores: int,
    jornada: float,
    seq_cfg: Optional[Dict[str, Any]] = None,
    nome_turma: str = "Geral",
    **flags: Any,
) -> Dict[str, Any]:
    """Roda UM cenário pelo scheduler real e devolve as métricas."""
    turmas = [{"nome": nome_turma, "operarios": int(executores)}]
    config = _config_cenario(demanda, turmas, jornada, seq_cfg=seq_cfg, **flags)

    cronograma, dias, demanda_restante = _executar_scheduler_loop(config)

    total_hh = sum(v for v in demanda.values())
    pendente = sum(v for v in demanda_restante.values() if v > 0.01)
    capacidade_dia = float(executores) * float(jornada)
    uso_pct = (100.0 * total_hh / (dias * capacidade_dia)) if dias > 0 and capacidade_dia > 0 else 0.0

    return {
        "executores": int(executores),
        "jornada": float(jornada),
        "dias_simulados": int(dias),
        "meses_simulados": round(dias / 22.0, 2),
        "hh_total": round(total_hh, 2),
        "hh_pendente": round(pendente, 2),
        "linhas_cronograma": len(cronograma),
        "capacidade_dia_hh": round(capacidade_dia, 2),
        "uso_capacidade_pct": round(uso_pct, 1),
        "aprovacao": "COMPLETO" if pendente <= 0.01 else "INCOMPLETO",
    }


def simular_cenarios_reais(
    demanda: Dict[Any, float],
    executores_base: int,
    jornada_base: float,
    jornadas: Sequence[float] = (),
    equipes: Sequence[int] = (),
    seq_cfg: Optional[Dict[str, Any]] = None,
    nome_turma: str = "Geral",
    **flags: Any,
) -> List[Dict[str, Any]]:
    """Grade de cenários (jornada × equipe) rodados pelo scheduler REAL."""
    jornadas_l = sorted({float(x) for x in (jornadas or [jornada_base])})
    equipes_l = sorted({int(x) for x in (equipes or [executores_base])})

    linhas: List[Dict[str, Any]] = []
    for jornada in jornadas_l:
        for equipe in equipes_l:
            linhas.append(
                simular_cenario_real(
                    demanda,
                    executores=equipe,
                    jornada=jornada,
                    seq_cfg=seq_cfg,
                    nome_turma=nome_turma,
                    **flags,
                )
            )
    return linhas
