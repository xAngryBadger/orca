"""Testes para agregador financeiro (bridge.agregar_por_periodo)."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.atm.web.bridge import agregar_por_periodo


class TestAgregadorFinanceiro(unittest.TestCase):
    """Testa a função agregar_por_periodo do bridge."""

    def setUp(self):
        """Cronograma de exemplo com 3 fazendas, 10 dias."""
        self.cronograma = [
            # Semana 1 (dias 1-5)
            {"Dia": 1, "Fazenda": "FAZENDA A", "HH": 40.0, "Custo_MO": 800.0},
            {"Dia": 2, "Fazenda": "FAZENDA A", "HH": 40.0, "Custo_MO": 800.0},
            {"Dia": 3, "Fazenda": "FAZENDA B", "HH": 30.0, "Custo_MO": 600.0},
            {"Dia": 4, "Fazenda": "FAZENDA B", "HH": 30.0, "Custo_MO": 600.0},
            {"Dia": 5, "Fazenda": "FAZENDA C", "HH": 20.0, "Custo_MO": 400.0},
            # Semana 2 (dias 6-10)
            {"Dia": 6, "Fazenda": "FAZENDA A", "HH": 40.0, "Custo_MO": 800.0},
            {"Dia": 7, "Fazenda": "FAZENDA A", "HH": 40.0, "Custo_MO": 800.0},
            {"Dia": 8, "Fazenda": "FAZENDA B", "HH": 30.0, "Custo_MO": 600.0},
            {"Dia": 9, "Fazenda": "FAZENDA B", "HH": 30.0, "Custo_MO": 600.0},
            {"Dia": 10, "Fazenda": "FAZENDA C", "HH": 20.0, "Custo_MO": 400.0},
        ]

    def test_modo_hh_only_degrada_para_hh(self):
        """(a) Modo HH-only deve degradar para somar HH (não Custo_MO)."""
        resultado = agregar_por_periodo(self.cronograma, periodo="semana", modo_somente_hh=True)
        
        # Semana 1: FAZENDA A=80, FAZENDA B=60, FAZENDA C=20
        self.assertIn("Semana 1", resultado)
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA A"], 80.0, places=1)
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA B"], 60.0, places=1)
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA C"], 20.0, places=1)
        
        # Semana 2: FAZENDA A=80, FAZENDA B=60, FAZENDA C=20
        self.assertIn("Semana 2", resultado)
        self.assertAlmostEqual(resultado["Semana 2"]["FAZENDA A"], 80.0, places=1)
        self.assertAlmostEqual(resultado["Semana 2"]["FAZENDA B"], 60.0, places=1)
        self.assertAlmostEqual(resultado["Semana 2"]["FAZENDA C"], 20.0, places=1)

    def test_modo_financeiro_soma_custo_mo_correto(self):
        """(b) Modo financeiro deve somar Custo_MO corretamente por mês/semana."""
        resultado = agregar_por_periodo(self.cronograma, periodo="semana", modo_somente_hh=False)
        
        # Semana 1: FAZENDA A=1600, FAZENDA B=1200, FAZENDA C=400
        self.assertIn("Semana 1", resultado)
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA A"], 1600.0, places=1)
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA B"], 1200.0, places=1)
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA C"], 400.0, places=1)
        
        # Semana 2: FAZENDA A=1600, FAZENDA B=1200, FAZENDA C=400
        self.assertIn("Semana 2", resultado)
        self.assertAlmostEqual(resultado["Semana 2"]["FAZENDA A"], 1600.0, places=1)
        self.assertAlmostEqual(resultado["Semana 2"]["FAZENDA B"], 1200.0, places=1)
        self.assertAlmostEqual(resultado["Semana 2"]["FAZENDA C"], 400.0, places=1)

    def test_fazenda_sem_tarifa_nao_entra_como_zero(self):
        """(c) Fazenda sem tarifa (Custo_MO=None ou 0) não entra como zero fake."""
        # Cronograma com uma linha sem Custo_MO (simula atividade sem tarifa)
        cronograma_sem_tarifa = [
            {"Dia": 1, "Fazenda": "FAZENDA A", "HH": 40.0, "Custo_MO": 800.0},
            {"Dia": 2, "Fazenda": "FAZENDA B", "HH": 30.0, "Custo_MO": None},  # Sem tarifa
            {"Dia": 3, "Fazenda": "FAZENDA C", "HH": 20.0, "Custo_MO": 0.0},   # Custo zero
        ]
        
        # Modo financeiro: apenas FAZENDA A deve aparecer
        resultado = agregar_por_periodo(cronograma_sem_tarifa, periodo="semana", modo_somente_hh=False)
        
        self.assertIn("Semana 1", resultado)
        self.assertIn("FAZENDA A", resultado["Semana 1"])
        self.assertAlmostEqual(resultado["Semana 1"]["FAZENDA A"], 800.0, places=1)
        
        # FAZENDA B (Custo_MO=None) e FAZENDA C (Custo_MO=0) NÃO devem aparecer
        self.assertNotIn("FAZENDA B", resultado["Semana 1"])
        self.assertNotIn("FAZENDA C", resultado["Semana 1"])

    def test_agregacao_mensal(self):
        """Testa agregação por mês (22 dias úteis)."""
        # Cria cronograma de 30 dias
        cronograma_30dias = []
        for dia in range(1, 31):
            cronograma_30dias.append({
                "Dia": dia,
                "Fazenda": "FAZENDA A",
                "HH": 10.0,
                "Custo_MO": 200.0,
            })
        
        resultado = agregar_por_periodo(cronograma_30dias, periodo="mes", modo_somente_hh=False)
        
        # Mês 1 = dias 1-22, Mês 2 = dias 23-30 (parcial)
        self.assertIn("Mês 1", resultado)
        self.assertIn("Mês 2", resultado)
        
        # Mês 1: 22 dias * 200 = 4400
        self.assertAlmostEqual(resultado["Mês 1"]["FAZENDA A"], 4400.0, places=1)
        # Mês 2: 8 dias * 200 = 1600
        self.assertAlmostEqual(resultado["Mês 2"]["FAZENDA A"], 1600.0, places=1)

    def test_cronograma_vazio_retorna_vazio(self):
        """Cronograma vazio deve retornar dict vazio."""
        resultado = agregar_por_periodo([], periodo="semana", modo_somente_hh=True)
        self.assertEqual(resultado, {})

    def test_periodo_invalido_levanta_erro(self):
        """Período inválido deve levantar ValueError."""
        with self.assertRaises(ValueError):
            agregar_por_periodo(self.cronograma, periodo="trimestre", modo_somente_hh=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)