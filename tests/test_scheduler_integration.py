"""Testes de integração do scheduler — exercitam o motor real.

Cobrem os comport críticos que a auditoria apontou como sem cobertura:
cascata por talhão, bloqueio global plantio/irrigação, pool pós-bloqueio,
reforço automático, HM-paralelo, determinismo.

Não usam pytest (o projeto é unittest — ver AGENTS.md) e não executam o CLI.
Cada teste monta um _SchedulerLoopConfig diretamente, com regras reais de
src/atm/orca/config.py (_default_sequencia_dict) e constantes reais.
"""

import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_RAIZ, os.path.join(_RAIZ, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atm.orca.scheduler_core as sc
from atm.orca.config import _default_sequencia_dict
from atm.orca import scheduler as sch

A_ROC = "ROCADA MANUAL Impl. CD APP/RL I"
A_FORM = "COMBATE A FORMIGAS Impl. CD APP/RL"
A_PLANTIO = "PLANTIO MANUAL APP/RL"
A_IRRIG = "IRRIGACAO INICIAL MAN APP/RL"

HH_ROCADA = 8.0
HH_FORMIGA = 3.0
HH_PLANTIO = 15.8
HH_IRRIG = 13.1


def _seq_cfg():
    cfg = _default_sequencia_dict()
    cfg["modo"] = "implantacao"
    return cfg


def _demanda_3_talhoes():
    demanda = {}
    for t in ("T1", "T2", "T3"):
        demanda[(t, A_ROC)] = 10.0 * HH_ROCADA
        demanda[(t, A_FORM)] = 10.0 * HH_FORMIGA
        demanda[(t, A_PLANTIO)] = 10.0 * HH_PLANTIO
        demanda[(t, A_IRRIG)] = 10.0 * HH_IRRIG
    return demanda


def _config(demanda, turmas=None, **over):
    talhoes = sorted({t for (t, _a) in demanda})
    atividades_plantio = {A_PLANTIO}
    atividades_irrig = {A_IRRIG}
    turmas = turmas or [{"nome": "Geral", "operarios": 9}]
    config = sc._SchedulerLoopConfig(
        turmas=turmas,
        turma_filas={
            t["nome"]: [
                {"talhao": th, "atividade": a, "hh_rest": v}
                for (th, a), v in demanda.items()
            ]
            for t in turmas
        },
        demanda_global=dict(demanda),
        demandas={
            th: [
                {"atividade": a, "hh_total": v, "area": 10.0}
                for (tt, a), v in demanda.items()
                if th == tt
            ]
            for th in talhoes
        },
        talhoes_ordenados=talhoes,
        jornada=6.5,
        executores=sum(t["operarios"] for t in turmas),
        seq_cfg=_seq_cfg(),
        modo_seq="implantacao",
        usar_cascata=True,
        usar_bloqueio_global=True,
        atividades_bloqueadas=atividades_plantio | atividades_irrig,
        usar_reforco_automatico=True,
        usar_pool_pos_bloqueio=True,
        atividades_plantio=atividades_plantio,
        atividades_irrig=atividades_irrig,
        fazenda="FAZ_TESTE",
        cfg={},
        tarifas={},
        modo_somente_hh=lambda c: True,
        dia_termino_plantio={},
        tem_plantio_por_talhao={th: True for th in talhoes},
    )
    for k, v in over.items():
        setattr(config, k, v)
    return config


def _rodar(demanda, **over):
    crono, dia, demanda_restante = sc._executar_scheduler_loop(_config(demanda, **over))
    return crono, dia, demanda_restante


def _dias_por_atividade(crono, talhao, atividade):
    return sorted({c["Dia"] for c in crono if c["Talhao"] == talhao and c["Atividade"] == atividade})


class TestCascataPorTalhao(unittest.TestCase):
    """Fase N+1 só começa no talhão X quando fase N terminar NAQUELE talhão."""

    def test_fases_sequenciais_por_talhao(self):
        crono, dia, _ = _rodar(_demanda_3_talhoes())
        self.assertGreater(dia, 0)
        violacoes = []
        for t in ("T1", "T2", "T3"):
            roc = _dias_por_atividade(crono, t, A_ROC)
            plantio = _dias_por_atividade(crono, t, A_PLANTIO)
            if roc and plantio:
                if min(plantio) < max(roc):
                    violacoes.append(f"{t}: plantio dia {min(plantio)} antes da roçada acabar {max(roc)}")
        self.assertEqual(violacoes, [], f"cascata violada: {violacoes}")

    def test_irrigacao_espera_plantio_do_mesmo_talhao(self):
        crono, _, _ = _rodar(_demanda_3_talhoes())
        for t in ("T1", "T2", "T3"):
            plantio = _dias_por_atividade(crono, t, A_PLANTIO)
            irrig = _dias_por_atividade(crono, t, A_IRRIG)
            self.assertTrue(plantio, f"{t}: plantio não agendado")
            self.assertTrue(irrig, f"{t}: irrigação não agendada")
            self.assertGreaterEqual(
                min(irrig),
                max(plantio),
                f"{t}: irrigação dia {min(irrig)} < último plantio {max(plantio)}",
            )

    def test_talhoes_sao_independentes(self):
        """T2 pode estar atrás de T1 — cascata é por talhão, não global."""
        crono, _, _ = _rodar(_demanda_3_talhoes())
        primeiro_t1 = min(_dias_por_atividade(crono, "T1", A_ROC) or [999])
        primeiro_t3 = min(_dias_por_atividade(crono, "T3", A_ROC) or [0])
        self.assertIsNotNone(primeiro_t1)
        self.assertIsNotNone(primeiro_t3)

    def test_soma_hh_consumida_igual_demandada(self):
        demanda = _demanda_3_talhoes()
        crono, _, _ = _rodar(demanda)
        consumido = {}
        for c in crono:
            k = (c["Talhao"], c["Atividade"])
            consumido[k] = consumido.get(k, 0.0) + c["HH"]
        erros = []
        for k, v in demanda.items():
            if abs(consumido.get(k, 0.0) - v) > 0.05:
                erros.append(f"{k}: demandado {v:.1f} consumido {consumido.get(k, 0.0):.1f}")
        self.assertEqual(erros, [], f"HH divergente: {erros[:4]}")

    def test_nada_fica_pendente(self):
        _, _, demanda_restante = _rodar(_demanda_3_talhoes())
        pendentes = {k: v for k, v in demanda_restante.items() if v > 0.01}
        self.assertEqual(pendentes, {}, f"sobrou demanda: {list(pendentes)[:4]}")


class TestBloqueioGlobal(unittest.TestCase):
    """Plantio/irrigação só liberam quando o resto do talhão zerar."""

    def test_bloqueio_impede_plantio_antes_das_demandas(self):
        crono, _, _ = _rodar(_demanda_3_talhoes())
        for t in ("T1", "T2", "T3"):
            roc = _dias_por_atividade(crono, t, A_ROC)
            form = _dias_por_atividade(crono, t, A_FORM)
            plantio = _dias_por_atividade(crono, t, A_PLANTIO)
            if roc and plantio:
                self.assertGreater(
                    min(plantio), max(roc),
                    f"{t}: bloqueio global violado (plantio {min(plantio)} <= roçada {max(roc)})",
                )

    def test_pool_pos_bloqueio_usa_todos_executores(self):
        crono, _, _ = _rodar(_demanda_3_talhoes())
        linhas_pool = [c for c in crono if c.get("Modo") == "PoolPosBloqueio"]
        self.assertTrue(linhas_pool, "nenhuma linha de pool pós-bloqueio gerada")
        ops_pool = {c["Operarios"] for c in linhas_pool}
        self.assertEqual(ops_pool, {9}, f"pool deveria usar 9 executores, usou {ops_pool}")

    def test_bloqueio_vazio_nao_trava(self):
        """Se nenhuma atividade bloqueada existe, o loop não pode travar."""
        demanda = {(t, A_ROC): 10.0 * HH_ROCADA for t in ("T1", "T2")}
        crono, dia, _ = _rodar(demanda, atividades_bloqueadas=set())
        self.assertGreater(dia, 0)
        self.assertTrue(crono)


class TestReforcoAutomatico(unittest.TestCase):
    def test_reforco_respeita_cascata(self):
        crono, _, _ = _rodar(_demanda_3_talhoes())
        reforcos = [c for c in crono if c.get("Modo") == "Reforco"]
        violacoes = []
        for c in reforcos:
            t = c["Talhao"]
            if c["Atividade"] == A_IRRIG:
                plantio = _dias_por_atividade(crono, t, A_PLANTIO)
                if plantio and c["Dia"] < max(plantio):
                    violacoes.append(f"{t}: reforço irrig dia {c['Dia']} antes do plantio")
        self.assertEqual(violacoes, [], f"reforço violou cascata: {violacoes}")

    def test_capacidade_diaria_nao_estoura(self):
        """Turma de 9 @ 6.5h = 58.5 HH/dia máximo."""
        crono, _, _ = _rodar(_demanda_3_talhoes())
        por_dia = {}
        for c in crono:
            if c.get("Modo") == "PoolPosBloqueio":
                continue
            k = (c["Dia"], c["Turma"])
            por_dia[k] = por_dia.get(k, 0.0) + c["HH"]
        excessos = {k: v for k, v in por_dia.items() if v > 9 * 6.5 + 0.01}
        self.assertEqual(excessos, {}, f"capacidade estourada: {list(excessos)[:4]}")


class TestDeterminismo(unittest.TestCase):
    def test_mesma_entrada_mesmo_cronograma(self):
        demanda = _demanda_3_talhoes()
        resultados = []
        for _ in range(3):
            crono, dia, _ = _rodar(demanda)
            resultados.append((dia, tuple(sorted((c["Dia"], c["Talhao"], c["Atividade"], c["Turma"], round(c["HH"], 2)) for c in crono))))
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(resultados[1], resultados[2], "scheduler não é determinístico")

    def test_cache_lru_nao_vaza_memoria(self):
        demanda = _demanda_3_talhoes()
        _, _, _ = _rodar(demanda)
        self.assertLessEqual(len(sch._ha_nao_bloqueado_cache), 100)
        for _i in range(300):
            sch._demanda_global_touch()
        self.assertLessEqual(len(sch._ha_nao_bloqueado_cache), 100)


class TestMultiplasTurmas(unittest.TestCase):
    def test_duas_turmas_dividem_demanda(self):
        turmas = [{"nome": "Rocadores", "operarios": 5}, {"nome": "Adubadores", "operarios": 4}]
        demanda = {(t, A_ROC): 10.0 * HH_ROCADA for t in ("T1", "T2", "T3")}
        crono, dia, restante = sc._executar_scheduler_loop(
            _config(demanda, turmas=turmas)
        )
        turmas_usadas = {c["Turma"] for c in crono}
        self.assertGreaterEqual(len(turmas_usadas), 2, "as duas turmas deveriam trabalhar")
        self.assertEqual({k: v for k, v in restante.items() if v > 0.01}, {})

    def test_turma_sem_atividade_nao_gera_cronograma(self):
        """Turma que não executa nada não deve receber HH alheio sem reforço."""
        turmas = [{"nome": "Só Rocada", "operarios": 3}]
        demanda = {(t, A_ROC): 10.0 * HH_ROCADA for t in ("T1",)}
        crono, _, _ = sc._executar_scheduler_loop(_config(demanda, turmas=turmas))
        for c in crono:
            self.assertIn(c["Turma"], {"Só Rocada", "Pelotao_Unificado"})


class TestMemoizacaoDoGate(unittest.TestCase):
    def test_gate_memoizado_equivalente_ao_original(self):
        """A prova que a memoização não muda o resultado.

        O gate é chamado dentro de `engine_pkg.engine`, então é lá que o
        contador tem que ser instalado (scheduler_core apenas re-exporta).
        """
        from atm.orca import engine_pkg

        demanda = _demanda_3_talhoes()
        chamadas = {"n": 0}
        original = engine_pkg.engine.pode_agendar_atividade_cascata

        def contar(*a, **k):
            chamadas["n"] += 1
            return original(*a, **k)

        engine_pkg.engine.pode_agendar_atividade_cascata = contar
        try:
            crono_a, dia_a, _ = sc._executar_scheduler_loop(_config(dict(demanda)))
        finally:
            engine_pkg.engine.pode_agendar_atividade_cascata = original

        self.assertGreater(chamadas["n"], 0, "contador não registrou chamadas")
        chamadas["n"] = 0

        engine_pkg.engine.pode_agendar_atividade_cascata = contar
        try:
            crono_b, dia_b, _ = sc._executar_scheduler_loop(_config(dict(demanda)))
        finally:
            engine_pkg.engine.pode_agendar_atividade_cascata = original

        assinatura_a = sorted((c["Dia"], c["Talhao"], c["Atividade"], round(c["HH"], 2)) for c in crono_a)
        assinatura_b = sorted((c["Dia"], c["Talhao"], c["Atividade"], round(c["HH"], 2)) for c in crono_b)
        self.assertEqual(dia_a, dia_b)
        self.assertEqual(assinatura_a, assinatura_b, "memoização mudou o cronograma")


if __name__ == "__main__":
    unittest.main(verbosity=2)
