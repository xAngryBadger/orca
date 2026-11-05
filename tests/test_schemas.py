"""Testes dos contratos Pydantic — contra estruturas REAIS do motor."""

import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_RAIZ, os.path.join(_RAIZ, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atm.orca.schemas import (  # noqa: E402
    DeParaMap,
    MicroRow,
    PipelineConfig,
    PrecoFinal,
    TarifaCT,
    TarifasDict,
    depara_de_dict,
    micro_de_dataframe,
    tarifas_de_dict,
)


class TestMicroRow(unittest.TestCase):
    def test_colunas_reais_do_loader(self):
        """io.py:325 produz exatamente estes campos obrigatórios."""
        row = MicroRow(
            fazenda="FAZ A", chave="t1", area_ha=12.5, atividade="ROCADA MANUAL Impl. CD APP/RL I"
        )
        self.assertEqual(row.fazenda, "FAZ A")
        self.assertEqual(row.chave, "T1")  # normalizado para maiúscula
        self.assertEqual(row.area_ha, 12.5)
        self.assertEqual(row.penalidade, 1.0)  # default do pipeline
        self.assertIsNone(row.equipe)
        self.assertIsNone(row.metodologia)

    def test_area_negativa_rejeitada(self):
        with self.assertRaises(ValueError):
            MicroRow(fazenda="F", chave="T1", area_ha=-5.0, atividade="X")

    def test_penalidade_fora_de_range_rejeitada(self):
        with self.assertRaises(ValueError):
            MicroRow(fazenda="F", chave="T1", area_ha=1.0, atividade="X", penalidade=99.0)

    def test_opcionais_aceitos(self):
        row = MicroRow(
            fazenda="F", chave="T1", area_ha=1.0, atividade="X",
            equipe="INOVESA", municipio="Paragominas", estado="PA", metodologia="Implantação",
        )
        self.assertEqual(row.estado, "PA")
        self.assertEqual(row.equipe, "INOVESA")

    def test_conversao_de_dataframe(self):
        import pandas as pd

        df = pd.DataFrame([
            {"fazenda": "F1", "chave": "T1", "area_ha": 10.0, "atividade": "ROCADA"},
            {"fazenda": "F1", "chave": "T2", "area_ha": 5.0, "atividade": "PLANTIO"},
        ])
        linhas = micro_de_dataframe(df)
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0].chave, "T1")


class TestTarifaCT(unittest.TestCase):
    def test_espelha_carregar_stg_tarifas(self):
        """tarifas.py:695-705 — mesmos campos."""
        t = TarifaCT(
            atividade="ROÇADA MANUAL Impl. CD APP/RL I",
            rendimento_hh=8.0, rendimento_hm=0.0,
            preco_ha=680.0, custo_hora=80.0, custo_ha=640.0,
            tipo="Manual", preco_unit=680.0, recurso="homem", eficiencia=1.0,
        )
        self.assertEqual(t.rendimento_hh, 8.0)
        self.assertEqual(t.recurso, "homem")

    def test_hh_positivo_zera_hm(self):
        """Regra real: HH>0 implica HM=0 (normalizar_ct313 faz isso)."""
        t = TarifaCT(atividade="X", rendimento_hh=10.0, rendimento_hm=2.0)
        self.assertEqual(t.rendimento_hm, 0.0)

    def test_hm_only_vira_maquina(self):
        t = TarifaCT(atividade="X", rendimento_hh=0.0, rendimento_hm=1.7)
        self.assertEqual(t.recurso, "maquina")

    def test_rendimento_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            TarifaCT(atividade="X", rendimento_hh=-1.0)


class TestDeParaMap(unittest.TestCase):
    def test_de_para_real_do_config(self):
        """constants.py DEFAULT_DEPARA_EXAME_CT317 — pares reais."""
        dp = depara_de_dict({
            "rocada manual impl cd app rl i": "ROÇADA MANUAL Impl. CD APP/RL I",
            "plantio manual app rl": "PLANTIO MANUAL APP/RL",
        })
        self.assertEqual(dp.root["plantio manual app rl"], "PLANTIO MANUAL APP/RL")

    def test_ciclo_direto_rejeitado(self):
        with self.assertRaises(ValueError):
            depara_de_dict({"A": "B", "B": "A"})


class TestPipelineConfig(unittest.TestCase):
    def _pipeline(self):
        micro = [
            MicroRow(fazenda="F1", chave="T1", area_ha=10.0, atividade="ROCADA MANUAL Impl. CD APP/RL I"),
            MicroRow(fazenda="F1", chave="T1", area_ha=10.0, atividade="PLANTIO MANUAL APP/RL"),
            MicroRow(fazenda="F1", chave="T2", area_ha=5.0, atividade="ATIVIDADE INVENTADA"),
        ]
        tarifas = tarifas_de_dict({
            "ROÇADA MANUAL Impl. CD APP/RL I": {"rendimento_hh": 8.0, "tipo": "Manual"},
            "PLANTIO MANUAL APP/RL": {"rendimento_hh": 0.0, "rendimento_hm": 15.8, "tipo": "Mecanizada"},
        })
        depara = depara_de_dict({
            "ROCADA MANUAL Impl. CD APP/RL I": "ROÇADA MANUAL Impl. CD APP/RL I",
            "PLANTIO MANUAL APP/RL": "PLANTIO MANUAL APP/RL",
        })
        return PipelineConfig(micro=micro, tarifas=tarifas, de_para=depara)

    def test_resolve_chave_via_de_para(self):
        p = self._pipeline()
        self.assertEqual(
            p.chave_tarifa("PLANTIO MANUAL APP/RL"), "PLANTIO MANUAL APP/RL"
        )

    def test_detecta_atividade_sem_tarifa(self):
        p = self._pipeline()
        faltando = p.actividades_sem_tarifa()
        self.assertEqual(len(faltando), 1)
        self.assertIn("ATIVIDADE INVENTADA", faltando[0])

    def test_cobertura_calculada(self):
        p = self._pipeline()
        cob = p.cobertura()
        self.assertEqual(cob["linhas_micro"], 3)
        self.assertEqual(cob["atividades_sem_tarifa"], 1)
        self.assertAlmostEqual(cob["cobertura_pct"], 66.67, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
