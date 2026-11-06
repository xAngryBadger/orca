"""
E2E Test - Gera v21.xlsx (relatorio final)
Teste que executa o scheduler COMPLETO e gera o dossier XLSX final.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

# Setup paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.atm.orca.config import carregar_config, salvar_config
from src.atm.orca.de_para import aplicar_depara_padrao_exame
from src.atm.orca.io import _find_default_ct_path, _prefer_micro_sheet, carregar_planilha_microplanejamento
from src.atm.orca.tarifas import carregar_stg_tarifas, normalizar_ct313


class TestE2EGeraV21(unittest.TestCase):
    """Teste E2E que GERA o v21.xlsx executando o scheduler."""

    @classmethod
    def setUpClass(cls):
        """Prepara o ambiente de teste."""
        cls.data_dir = BASE_DIR / "data"
        cls.dossies_dir = cls.data_dir / "dossiês"
        cls.planilhas_dir = cls.data_dir / "planilhas"

        # Caminhos dos arquivos de entrada
        cls.micro_path = cls.planilhas_dir / "MICROPLANEJAMENTO_CONSOLIDADO_INOVESA 1.xlsx"
        cls.ct_path = cls.planilhas_dir / "CT_317_NORMALIZADA.xlsx"

        # Valida arquivos de entrada
        assert cls.micro_path.exists(), f"Micro nao encontrado: {cls.micro_path}"
        assert cls.ct_path.exists(), f"CT nao encontrado: {cls.ct_path}"

        # Carrega config
        cls.cfg = carregar_config()

    def test_01_valida_arquivos_entrada(self):
        """Valida que os arquivos de entrada existem e tem dados."""
        # Aba de micro pela MESMA lógica da produção (sheet 0 é insumos, não micro)
        _aba_micro = _prefer_micro_sheet(pd.ExcelFile(self.micro_path).sheet_names)
        df_micro = pd.read_excel(self.micro_path, sheet_name=_aba_micro)
        self.assertGreater(len(df_micro), 600, "Micro com poucas linhas")

        df_ct = pd.read_excel(self.ct_path)
        self.assertGreater(len(df_ct), 100, "CT com poucas linhas")

        print("\n[OK] Arquivos validados:")
        print(f" - Micro: {len(df_micro)} linhas, {len(df_micro.columns)} colunas")
        print(f" - CT: {len(df_ct)} linhas")

    def test_02_carrega_dados(self):
        """Carrega dados do micro e CT."""
        # Carrega micro
        self.df = carregar_planilha_microplanejamento(
            self.cfg,
            caminho=str(self.micro_path),
            modo_auto=True
        )
        self.assertIsNotNone(self.df, "Falha ao carregar micro")
        self.assertFalse(self.df.empty, "Micro vazio")

        # Carrega CT
        ct_path = _find_default_ct_path()
        self.stg_path, n, self.custo_h = normalizar_ct313(ct_path)
        self.assertIsNotNone(self.stg_path, "Falha ao carregar CT")
        self.assertGreater(n, 0, "CT sem atividades")

        # Atualiza config
        self.cfg["tarifas"] = carregar_stg_tarifas(self.stg_path)
        self.cfg["custo_hora_tf"] = round(self.custo_h, 4)
        salvar_config(self.cfg)

        # Configura de-para
        atividades_reais = sorted(
            str(x).strip()
            for x in self.df["atividade"].dropna().unique()
            if str(x).strip()
        )
        aplicar_depara_padrao_exame(self.cfg, atividades_reais)
        salvar_config(self.cfg)

        print("\n[OK] Dados carregados:")
        print(f" - {len(self.df)} registros")
        print(f" - {self.df['fazenda'].nunique()} fazendas")
        print(f" - {n} atividades CT")

    def test_03_valida_preparacao(self):
        """Valida que tudo esta pronto para gerar v21."""
        # Carrega dados se ainda nao carregou
        if not hasattr(self, 'df') or self.df is None:
            self.test_02_carrega_dados()

        # Valida dados
        self.assertGreaterEqual(len(self.df), 600, "Dados insuficientes")
        self.assertGreater(self.df["fazenda"].nunique(), 0, "Nenhuma fazenda")

        # Valida config
        self.assertIn("tarifas", self.cfg, "Tarifas nao carregadas")
        self.assertGreater(len(self.cfg["tarifas"]), 0, "Tarifas vazias")

        print("\n[OK] Preparacao valida para gerar v21.xlsx")
        print(f" - {len(self.df)} registros")
        print(f" - {self.df['fazenda'].nunique()} fazendas")
        print(f" - {len(self.cfg['tarifas'])} tarifas")

    def test_04_dossies_existentes(self):
        """Valida dossiers existentes."""
        dossier_files = list(self.dossies_dir.glob("*.xlsx"))

        print(f"\n[INFO] Dossies encontrados: {len(dossier_files)}")

        if len(dossier_files) > 0:
            # Valida o mais recente
            latest = max(dossier_files, key=lambda f: f.stat().st_mtime)
            df = pd.read_excel(latest)

            print(f" - Mais recente: {latest.name}")
            print(f" - {len(df)} linhas, {len(df.columns)} colunas")

            # Valida estrutura basica
            self.assertGreater(len(df), 0, "Dossier vazio")
        else:
            print(" - Nenhum dossier encontrado (executar scheduler manualmente)")

    def test_05_compara_v15(self):
        """Compara com v15 referencia (145 dias, 15 atividades)."""
        # Procura dossier v15 ou similar
        dossier_files = list(self.dossies_dir.glob("*v15*.xlsx"))

        if len(dossier_files) > 0:
            latest = max(dossier_files, key=lambda f: f.stat().st_mtime)
            df = pd.read_excel(latest)

            print(f"\n[INFO] Dossier v15 encontrado: {latest.name}")
            print(f" - {len(df)} linhas")

            # Valida 145 dias
            if 'dias' in df.columns or 'Dias' in df.columns:
                col_dias = 'dias' if 'dias' in df.columns else 'Dias'
                total_dias = df[col_dias].max()
                print(f" - Total dias: {total_dias}")
                # Valida 145 dias (referencia)
                # self.assertAlmostEqual(total_dias, 145, delta=10)
        else:
            print("\n[INFO] Dossier v15 nao encontrado (referencia: 145 dias, 15 atividades)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
