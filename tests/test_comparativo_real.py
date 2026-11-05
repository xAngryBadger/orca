"""Testes do comparativo multi-fator REAL (scheduler, não aproximação)."""

import math
import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_RAIZ, os.path.join(_RAIZ, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atm.orca.comparativo_mec import simular_cenarios_multifator  # noqa: E402
from atm.orca.comparativo_real import (  # noqa: E402
    simular_cenario_real,
    simular_cenarios_reais,
)
from atm.orca.config import _default_sequencia_dict  # noqa: E402


def _demanda_com_cascata():
    """Cenário com 3 fases encadeadas + plantio + irrigação no mesmo talhão."""
    demanda = {}
    for t in ("T1", "T2", "T3", "T4"):
        demanda[(t, "ROCADA MANUAL Impl. CD APP/RL I")] = 10.0 * 8.0
        demanda[(t, "COMBATE A FORMIGAS Impl. CD APP/RL")] = 10.0 * 3.0
        demanda[(t, "PLANTIO MANUAL APP/RL")] = 10.0 * 15.8
        demanda[(t, "IRRIGACAO INICIAL MAN APP/RL")] = 10.0 * 13.1
    return demanda


SEQ = _default_sequencia_dict()


class TestCenarioReal(unittest.TestCase):
    def test_roda_um_cenario(self):
        r = simular_cenario_real(_demanda_com_cascata(), executores=9, jornada=6.5, seq_cfg=SEQ)
        self.assertEqual(r["executores"], 9)
        self.assertEqual(r["jornada"], 6.5)
        self.assertGreater(r["dias_simulados"], 0)
        self.assertEqual(r["aprovacao"], "COMPLETO")
        self.assertLessEqual(r["hh_pendente"], 0.01)

    def test_mais_executores_reduz_dias(self):
        demanda = _demanda_com_cascata()
        r9 = simular_cenario_real(demanda, 9, 6.5, seq_cfg=SEQ)
        r18 = simular_cenario_real(demanda, 18, 6.5, seq_cfg=SEQ)
        self.assertLessEqual(r18["dias_simulados"], r9["dias_simulados"])

    def test_mais_jornada_reduz_dias(self):
        demanda = _demanda_com_cascata()
        curto = simular_cenario_real(demanda, 9, 4.0, seq_cfg=SEQ)
        longo = simular_cenario_real(demanda, 9, 8.8, seq_cfg=SEQ)
        self.assertLessEqual(longo["dias_simulados"], curto["dias_simulados"])

    def test_uso_de_capacidade_coerente(self):
        """HH total / (dias × capacidade) não pode passar de 100% com sobra."""
        demanda = _demanda_com_cascata()
        r = simular_cenario_real(demanda, 9, 6.5, seq_cfg=SEQ)
        cap = r["capacidade_dia_hh"]
        self.assertEqual(cap, 9 * 6.5)
        self.assertLessEqual(r["uso_capacidade_pct"], 100.0 + 1e-6)
        self.assertGreater(r["uso_capacidade_pct"], 0.0)


class TestGradeReal(unittest.TestCase):
    def test_grade_completa(self):
        demanda = _demanda_com_cascata()
        linhas = simular_cenarios_reais(
            demanda, executores_base=9, jornada_base=6.5,
            jornadas=[4.3, 5.3, 6.5], equipes=[6, 9, 12], seq_cfg=SEQ,
        )
        self.assertEqual(len(linhas), 9)
        for linha in linhas:
            self.assertEqual(linha["aprovacao"], "COMPLETO")
            self.assertGreater(linha["dias_simulados"], 0)

    def test_ordenacao_deterministica(self):
        demanda = _demanda_com_cascata()
        a = simular_cenarios_reais(demanda, 9, 6.5, [4.0, 8.0], [6, 12], seq_cfg=SEQ)
        b = simular_cenarios_reais(demanda, 9, 6.5, [4.0, 8.0], [6, 12], seq_cfg=SEQ)
        self.assertEqual([x["dias_simulados"] for x in a], [x["dias_simulados"] for x in b])


class TestComparacaoAproximacao(unittest.TestCase):
    """A prova de que a aproximação antiga erra — e o real não."""

    def test_aprovacao_ignora_cascata(self):
        demanda = _demanda_com_cascata()
        total_hh = sum(demanda.values())
        real = simular_cenario_real(demanda, 9, 6.5, seq_cfg=SEQ)
        # aproximação da função antiga
        cap = 9 * 6.5
        aprox = int(math.ceil(total_hh / cap))
        # o real TEM que ser >= a aproximação (cascata só atrasa)
        self.assertGreaterEqual(
            real["dias_simulados"], aprox,
            f"scheduler real ({real['dias_simulados']}d) < aproximação ({aprox}d)?",
        )
        # e a diferença tem que ser material neste cenário encadeado
        self.assertGreater(
            real["dias_simulados"] - aprox, 0,
            "cenário encadeado deveria mostrar atraso vs aproximação",
        )

    def test_funcao_antiga_ainda_existe_para_compat(self):
        """A aproximação permanece disponível (não quebramos a API)."""
        demanda = _demanda_com_cascata()
        linhas = simular_cenarios_multifator(
            total_hh=sum(demanda.values()), dias_meta=130,
            executores_base=9, jornada_base=6.5,
            jornadas_in=[6.5], equipes_in=[9], interativo=False,
        )
        self.assertEqual(len(linhas), 1)
        self.assertIn("Dias_Simulados", linhas[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
