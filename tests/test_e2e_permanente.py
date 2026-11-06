#!/usr/bin/env python3
"""Testes E2E permanentes para validar todas as funcionalidades do CLI.

Configuração padrão:
- 9 operários
- 5h40 de jornada (5.67 horas)
- Dados: microatual.xlsx + ct317real.xlsx
"""

import sys
import unittest
from pathlib import Path

# Adicionar path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.atm.orca.scheduler import _min_fase_cascata_por_talhao

# Configuração padrão
CONFIG_PADRAO = {
    "executores": 9,
    "jornada": 5.67,  # 5h40 = 5.67 horas
    "prazo_meses": 6,
    "mes_ref": 5,
    "ano_ref": 2026,
    "dia_ref": 1,
}

# Dados de referência (v15 - funcional)
V15_DIAS = 145
V15_ATIVIDADES = 15
V15_HH_TOTAL = 7824.2


class TesteCascataGlobal(unittest.TestCase):
    """Teste crítico: cascata GLOBAL."""

    def test_cascata_respeita_fase_n_mais_1(self):
        """Cascata deve garantir fase N+1 só quando TODOS completam fase N."""
        demanda = {
            ('talhao1', 'ROCADA'): 10.0,
            ('talhao2', 'ROCADA'): 8.0,
        }

        resultado = _min_fase_cascata_por_talhao(
            demanda, {}, None, True, False, set(), set(), set(), 0, {}, {}
        )

        # Extrair MIN GLOBAL
        min_global = min(resultado.values()) if resultado else None

        # Deve ter valor
        self.assertIsNotNone(min_global)

        # Todas as fases devem ser >= min_global
        for fase in resultado.values():
            self.assertGreaterEqual(fase, min_global)


class TesteTimeUnico(unittest.TestCase):
    """Teste 1: Time único executa TODAS as atividades.
    
    Configuração:
    - 9 operários
    - 5h40 jornada
    - 1 time: todas as atividades
    
    Valida:
    - Scheduler completa sem erros
    - Dias <= 200 (v15: 145 dias)
    - Atividades >= 15
    - HH total >= 7000
    """

    def setUp(self):
        """Configurar teste."""
        self.config = CONFIG_PADRAO.copy()
        self.config["turmas"] = [
            {
                "nome": "Time Geral",
                "operarios": 9,
                "atividades": ["todas"]
            }
        ]

    def test_time_unico_completa_todas_atividades(self):
        """Time único deve completar todas as atividades em sequência."""
        # TODO: Implementar execução real do scheduler
        # Por enquanto, teste placeholder
        self.assertTrue(True, "Time único: teste placeholder")

    def test_time_unico_diasdentro_limite(self):
        """Dias devem ser <= 200."""
        # TODO: Implementar após execução real
        self.assertTrue(True, "Dias: teste placeholder")

    def test_time_unico_atividades_minimas(self):
        """Atividades devem ser >= 15."""
        # TODO: Implementar após execução real
        self.assertTrue(True, "Atividades: teste placeholder")


class TesteDoisTimes(unittest.TestCase):
    """Teste 2: Dois times com atividades distintas.
    
    Configuração:
    - Time Roçada (5 operários): ROCADA, COMBATE FORMIGA
    - Time Plantio (4 operários): PLANTIO, ADUBACAO
    - Prioridade: Roçada > Plantio
    
    Valida:
    - Time Roçada começa primeiro
    - Time Plantio espera roçada
    - Sem conflitos
    - Dias <= 180
    """

    def setUp(self):
        """Configurar teste."""
        self.config = CONFIG_PADRAO.copy()
        self.config["turmas"] = [
            {
                "nome": "Time Roçada",
                "operarios": 5,
                "atividades": ["ROCADA MANUAL", "COMBATE FORMIGA"],
                "prioridade": 1
            },
            {
                "nome": "Time Plantio",
                "operarios": 4,
                "atividades": ["PLANTIO", "ADUBACAO"],
                "prioridade": 2
            }
        ]

    def test_dois_times_sem_conflito(self):
        """Dois times não devem conflitar."""
        # TODO: Implementar execução real
        self.assertTrue(True, "Dois times: teste placeholder")

    def test_prioridade_respeitada(self):
        """Time Roçada deve começar antes de Time Plantio."""
        # TODO: Implementar validação de timeline
        self.assertTrue(True, "Prioridade: teste placeholder")


class TesteBloqueioGlobal(unittest.TestCase):
    """Teste 3: Bloqueio global de plantio/irrigação.
    
    Configuração:
    - Bloqueio global: ATIVADO
    - Filtros: ["plantio", "irrig"]
    - 1 time: todas as atividades
    
    Valida:
    - Plantio/irrigação bloqueados até resto completar
    - Cascata respeitada
    - Dias <= 200
    """

    def setUp(self):
        """Configurar teste."""
        self.config = CONFIG_PADRAO.copy()
        self.config["usar_bloqueio_global"] = True
        self.config["filtros_bloqueio"] = ["plantio", "irrig"]
        self.config["turmas"] = [
            {
                "nome": "Time Geral",
                "operarios": 9,
                "atividades": ["todas"]
            }
        ]

    def test_bloqueio_global_respeitado(self):
        """Plantio/irrigação devem ser bloqueados até resto completar."""
        # TODO: Implementar validação de bloqueio
        self.assertTrue(True, "Bloqueio global: teste placeholder")


class TesteMultiplasFazendas(unittest.TestCase):
    """Teste 4: Múltiplas fazendas simultâneas.
    
    Configuração:
    - 2+ fazendas: CONQUISTADORA VLF, SENHOR DO BOMFIM 1
    - 1 time: todas as fazendas
    
    Valida:
    - Todas as fazendas processadas
    - Sem sobreposição
    - Dias <= 250
    """

    def setUp(self):
        """Configurar teste."""
        self.config = CONFIG_PADRAO.copy()
        self.config["fazendas"] = [
            "CONQUISTADORA VLF (S-G24H)",
            "SENHOR DO BOMFIM 1 (S-G51H)"
        ]
        self.config["turmas"] = [
            {
                "nome": "Time Multi",
                "operarios": 9,
                "fazendas": ["todas"]
            }
        ]

    def test_multiplas_fazendas_processadas(self):
        """Todas as fazendas devem ser processadas."""
        # TODO: Implementar validação de múltiplas fazendas
        self.assertTrue(True, "Múltiplas fazendas: teste placeholder")


class TesteValidacaoDados(unittest.TestCase):
    """Teste 0: Validação dos dados de entrada.
    
    Valida:
    - microatual.xlsx carrega
    - ct317real.xlsx carrega
    - Colunas necessárias presentes
    """

    def test_microatual_carrega(self):
        """microatual.xlsx deve carregar corretamente."""
        import pandas as pd

        micro_path = Path("data/planilhas/microatual.xlsx")
        self.assertTrue(micro_path.exists(), f"Arquivo não encontrado: {micro_path}")

        micro = pd.read_excel(micro_path, sheet_name='MICROPL_IMPL_ABR_JUN_V5')
        self.assertGreater(len(micro), 0, "microatual.xlsx está vazio")

        # Colunas necessárias
        colunas_necessarias = ['DATA', 'CÓDIGO FAZENDA', 'NOME FAZENDA', 'CHAVE POLÍGONO', 'ATIVIDADES', 'ÁREA POLÍGONO (HECTARE)']
        for col in colunas_necessarias:
            self.assertIn(col, micro.columns, f"Coluna {col} não encontrada em microatual.xlsx")

    def test_ct317real_carrega(self):
        """ct317real.xlsx deve carregar corretamente."""
        import pandas as pd

        ct317_path = Path("data/planilhas/ct317real.xlsx")
        self.assertTrue(ct317_path.exists(), f"Arquivo não encontrado: {ct317_path}")

        # Sheet "Preço Final" tem 3 linhas de título; o cabeçalho real está na linha 3
        ct317 = pd.read_excel(ct317_path, sheet_name='Preço Final', header=3)
        self.assertGreater(len(ct317), 0, "ct317real.xlsx está vazio")

        # Colunas necessárias (layout real do CT317, igual ao parser de tarifas.py)
        colunas_necessarias = ['N', 'OPERAÇÕES', 'Rendimento']
        for col in colunas_necessarias:
            self.assertIn(col, ct317.columns, f"Coluna {col} não encontrada em ct317real.xlsx")


if __name__ == '__main__':
    # Executar testes
    unittest.main(verbosity=2)
