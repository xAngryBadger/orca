"""Teste de paridade: bridge._construir_demanda_canonica vs engine._construir_demandas.

Este teste garante que a demanda construída pelo bridge (painel web) é IDÊNTICA
à demanda construída pelo motor canônico (CLI), evitando o bug de divergência
documentado em docs/auditorias/corretude-calculos.md (achado #1).
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd

from src.atm.orca.config import carregar_config, modo_somente_hh
from src.atm.orca.tarifas import carregar_stg_tarifas
from src.atm.orca.schemas import MicroRow, micro_de_dataframe
from src.atm.orca.engine_pkg.engine import _construir_demandas
from src.atm.web.bridge import _construir_demanda_canonica, _micro_rows_para_dataframe


class TestWebDemandaParidade(unittest.TestCase):
    """Testa paridade entre demanda do bridge (web) e demanda do motor canônico (CLI)."""

    @classmethod
    def setUpClass(cls):
        """Cria fixtures temporários para o teste."""
        cls.temp_dir = tempfile.mkdtemp()
        
        # Tarifas STG com HH, HM, e HM-only
        tarifas_data = [
            {
                "atividade": "ROÇADA MANUAL",
                "tipo": "Manual",
                "rendimento_hh": 8.0,
                "rendimento_hm": 0.0,
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "fonte_aba": "Preço Final",
            },
            {
                "atividade": "PLANTIO MANUAL",
                "tipo": "Manual",
                "rendimento_hh": 15.8,
                "rendimento_hm": 0.0,
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "fonte_aba": "Preço Final",
            },
            {
                "atividade": "COLHEITA MECANIZADA",
                "tipo": "Mecanizada",
                "rendimento_hh": 0.0,
                "rendimento_hm": 2.5,  # 2.5 ha/dia (HM-only)
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "fonte_aba": "Preço Final",
            },
        ]
        tarifas_df = pd.DataFrame(tarifas_data)
        cls.tarifas_path = os.path.join(cls.temp_dir, "STG_TARIFAS_TESTE.xlsx")
        with pd.ExcelWriter(cls.tarifas_path, engine="openpyxl") as w:
            tarifas_df.to_excel(w, sheet_name="STG_TARIFAS", index=False)
        
        # Config mínimo
        cls.cfg = {
            "de_para": {},
            "tarifas": {},
            "atividades": {},
            "orcamento_estrito": True,
            "filtros_bloqueio_global": ["plantio", "irrig"],
            "fazendas_ct": ["FAZENDA TESTE"],
            "sequencia": {"modo": "implantacao"},
            "modo_somente_hh": True,
            "empresas": {},
            "comparativo": {"execucao_compacta": True},
        }
        cls.config_path = os.path.join(cls.temp_dir, "config_teste.json")
        import json
        with open(cls.config_path, "w", encoding="utf-8") as f:
            json.dump(cls.cfg, f, ensure_ascii=False, indent=2)

    @classmethod
    def tearDownClass(cls):
        """Limpa arquivos temporários."""
        import shutil
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        """Cria MicroRow diretamente com os nomes de campo corretos."""
        # Cria MicroRow usando os nomes de campo do schema (fazenda, chave, area_ha, atividade, penalidade)
        self.micro_rows = [
            MicroRow(
                fazenda="FAZENDA TESTE",
                chave="TALHAO 01",
                area_ha=10.0,
                atividade="ROÇADA MANUAL",
                penalidade=1.0,
            ),
            MicroRow(
                fazenda="FAZENDA TESTE",
                chave="TALHAO 01",
                area_ha=10.0,
                atividade="PLANTIO MANUAL",
                penalidade=1.2,  # Com penalidade
            ),
            MicroRow(
                fazenda="FAZENDA TESTE",
                chave="TALHAO 02",
                area_ha=15.0,
                atividade="COLHEITA MECANIZADA",  # HM-only
                penalidade=1.0,
            ),
        ]
        
        # Carrega tarifas
        self.tarifas = carregar_stg_tarifas(self.tarifas_path)
        
        # Config
        self.cfg = self.cfg.copy()

    def test_paridade_chaves_mesmas(self):
        """As chaves (talhao, atividade) devem ser idênticas entre bridge e motor."""
        demanda_bridge = _construir_demanda_canonica(self.micro_rows, self.tarifas, self.cfg)
        
        # Chama o motor canônico diretamente
        df_faz = _micro_rows_para_dataframe(self.micro_rows)
        talhoes_ordenados = sorted(df_faz["chave"].unique().tolist())
        atividades_reais = sorted(df_faz["atividade"].unique().tolist())
        
        resultado_motor = _construir_demandas(
            talhoes_ordenados=talhoes_ordenados,
            df_faz=df_faz,
            cfg=self.cfg,
            tarifas=self.tarifas,
            strict=True,
            session_hh={},
            modo_somente_hh=modo_somente_hh,
            atividades_reais=atividades_reais,
        )
        
        demanda_motor = {}
        for talhao, tarefas in resultado_motor["demandas"].items():
            for tarefa in tarefas:
                if tarefa["hh_total"] > 0:
                    demanda_motor[(talhao, tarefa["atividade"])] = round(tarefa["hh_total"], 2)
        
        # As chaves devem ser idênticas
        self.assertEqual(
            set(demanda_bridge.keys()),
            set(demanda_motor.keys()),
            "Chaves da demanda divergem entre bridge e motor canônico"
        )

    def test_paridade_valores_hh_only(self):
        """Valores HH para atividades HH-only devem bater (delta 0.01)."""
        demanda_bridge = _construir_demanda_canonica(self.micro_rows, self.tarifas, self.cfg)
        
        df_faz = _micro_rows_para_dataframe(self.micro_rows)
        talhoes_ordenados = sorted(df_faz["chave"].unique().tolist())
        atividades_reais = sorted(df_faz["atividade"].unique().tolist())
        
        resultado_motor = _construir_demandas(
            talhoes_ordenados=talhoes_ordenados,
            df_faz=df_faz,
            cfg=self.cfg,
            tarifas=self.tarifas,
            strict=True,
            session_hh={},
            modo_somente_hh=modo_somente_hh,
            atividades_reais=atividades_reais,
        )
        
        demanda_motor = {}
        for talhao, tarefas in resultado_motor["demandas"].items():
            for tarefa in tarefas:
                if tarefa["hh_total"] > 0:
                    demanda_motor[(talhao, tarefa["atividade"])] = round(tarefa["hh_total"], 2)
        
        # Verifica cada chave HH-only
        for chave, valor_bridge in demanda_bridge.items():
            valor_motor = demanda_motor.get(chave)
            self.assertIsNotNone(valor_motor, f"Chave {chave} ausente no motor")
            self.assertAlmostEqual(
                valor_bridge, valor_motor, places=2,
                msg=f"Valor HH diverge para {chave}: bridge={valor_bridge}, motor={valor_motor}"
            )

    def test_hm_only_nao_gera_hh_fake(self):
        """Atividade HM-only (mecanizada) NÃO deve gerar HH fake no bridge.
        
        Bug original: bridge fazia area / rendimento_hm gerando HH fake.
        Correto: HM-only roda em paralelo, não consome HH da equipe humana.
        """
        demanda_bridge = _construir_demanda_canonica(self.micro_rows, self.tarifas, self.cfg)
        
        # COLHEITA MECANIZADA é HM-only (rendimento_hh=0, rendimento_hm=2.5)
        # Não deve aparecer na demanda (hh_total = 0)
        chaves_hm_only = [k for k in demanda_bridge.keys() if "COLHEITA" in str(k[1]).upper()]
        
        self.assertEqual(
            len(chaves_hm_only), 0,
            f"HM-only não deve gerar demanda HH, mas gerou: {chaves_hm_only}"
        )

    def test_penalidade_aplicada(self):
        """Penalidade deve ser aplicada no cálculo de HH (bridge == motor)."""
        demanda_bridge = _construir_demanda_canonica(self.micro_rows, self.tarifas, self.cfg)
        
        df_faz = _micro_rows_para_dataframe(self.micro_rows)
        talhoes_ordenados = sorted(df_faz["chave"].unique().tolist())
        atividades_reais = sorted(df_faz["atividade"].unique().tolist())
        
        resultado_motor = _construir_demandas(
            talhoes_ordenados=talhoes_ordenados,
            df_faz=df_faz,
            cfg=self.cfg,
            tarifas=self.tarifas,
            strict=True,
            session_hh={},
            modo_somente_hh=modo_somente_hh,
            atividades_reais=atividades_reais,
        )
        
        demanda_motor = {}
        for talhao, tarefas in resultado_motor["demandas"].items():
            for tarefa in tarefas:
                if tarefa["hh_total"] > 0:
                    demanda_motor[(talhao, tarefa["atividade"])] = round(tarefa["hh_total"], 2)
        
        # PLANTIO MANUAL tem penalidade 1.2
        chave_plantio = ("TALHAO 01", "PLANTIO MANUAL")
        self.assertIn(chave_plantio, demanda_bridge)
        self.assertIn(chave_plantio, demanda_motor)
        
        # Valor deve incluir penalidade: area * rendimento_hh * penalidade
        # 10.0 * 15.8 * 1.2 = 189.6
        self.assertAlmostEqual(demanda_bridge[chave_plantio], 189.6, places=1)
        self.assertAlmostEqual(demanda_motor[chave_plantio], 189.6, places=1)

    def test_de_para_respeitado(self):
        """Se houver de_para no config, deve ser respeitado (bridge == motor)."""
        # Adiciona de_para: "ROÇADA MANUAL" -> "ROÇADA MANUAL CT"
        cfg_com_depara = self.cfg.copy()
        cfg_com_depara["de_para"] = {"ROÇADA MANUAL": "ROÇADA MANUAL CT"}
        
        # Adiciona tarifa com chave mapeada
        tarifas_com_depara = dict(self.tarifas)
        tarifas_com_depara["ROÇADA MANUAL CT"] = {
            "rendimento_hh": 6.0,
            "rendimento_hm": 0.0,
            "preco_ha": 0.0,
            "custo_hora": 0.0,
            "custo_ha": 0.0,
            "tipo": "Manual",
        }
        
        demanda_bridge = _construir_demanda_canonica(self.micro_rows, tarifas_com_depara, cfg_com_depara)
        
        df_faz = _micro_rows_para_dataframe(self.micro_rows)
        talhoes_ordenados = sorted(df_faz["chave"].unique().tolist())
        atividades_reais = sorted(df_faz["atividade"].unique().tolist())
        
        resultado_motor = _construir_demandas(
            talhoes_ordenados=talhoes_ordenados,
            df_faz=df_faz,
            cfg=cfg_com_depara,
            tarifas=tarifas_com_depara,
            strict=True,
            session_hh={},
            modo_somente_hh=modo_somente_hh,
            atividades_reais=atividades_reais,
        )
        
        demanda_motor = {}
        for talhao, tarefas in resultado_motor["demandas"].items():
            for tarefa in tarefas:
                if tarefa["hh_total"] > 0:
                    demanda_motor[(talhao, tarefa["atividade"])] = round(tarefa["hh_total"], 2)
        
        # A atividade original "ROÇADA MANUAL" deve usar a tarifa "ROÇADA MANUAL CT" (rendimento 6.0)
        # HH = 10.0 * 6.0 = 60.0
        chave_rocada = ("TALHAO 01", "ROÇADA MANUAL")
        self.assertIn(chave_rocada, demanda_bridge)
        self.assertAlmostEqual(demanda_bridge[chave_rocada], 60.0, places=1)
        self.assertAlmostEqual(demanda_motor[chave_rocada], 60.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)