"""
Testes E2E rodando em modo batch com DADOS REAIS.
Ignorado caso microatual.xlsx e ct317real.xlsx nao existam localmente.
"""
import os
import sys
import unittest
import pandas as pd
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.atm.orca.io import carregar_planilha_microplanejamento
from src.atm.orca.tarifas import normalizar_ct313, carregar_stg_tarifas
from src.atm.orca.scheduler_core import calcular_cronograma_inteligente

REAL_MICRO = os.path.join(ROOT, "data", "planilhas", "microatual.xlsx")
REAL_CT = os.path.join(ROOT, "data", "planilhas", "ct317real.xlsx")


class TestE2ERealDataBatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skip_run = False
        if not os.path.exists(REAL_MICRO):
            cls.skip_run = "microatual.xlsx nao encontrado"
        elif not os.path.exists(REAL_CT):
            cls.skip_run = "ct317real.xlsx nao encontrado"

    def setUp(self):
        if self.skip_run:
            self.skipTest(self.skip_run)

    def test_run_real_farm_batch(self):
        """Carrega dados reais, escolhe a primeira fazenda e roda o scheduler."""
        
        # 1. Carregar Tarifas Reais
        stg_path, n_ct, custo = normalizar_ct313(REAL_CT)
        self.assertIsNotNone(stg_path, "Falha ao normalizar CT real")
        self.assertGreater(n_ct, 0, "CT real gerou 0 linhas validas")
        tarifas = carregar_stg_tarifas(stg_path)
        self.assertTrue(bool(tarifas), "Tarifas vazias apos carregamento")

        # 2. Carregar Micro Real
        df_micro = carregar_planilha_microplanejamento({}, REAL_MICRO, modo_auto=True)
        self.assertIsNotNone(df_micro, "Falha ao carregar micro real")
        self.assertIn("fazenda", df_micro.columns, "Planilha micro nao tem coluna fazenda")
        
        df_micro["fazenda"] = df_micro["fazenda"].astype(str).str.strip().str.upper()
        df_micro = df_micro[df_micro["fazenda"] != "NAN"]
        df_micro = df_micro[df_micro["fazenda"] != ""]
        fazendas = sorted(df_micro["fazenda"].unique().tolist())
        self.assertTrue(len(fazendas) > 0, "Nenhuma fazenda valida encontrada no micro")
        
        fazenda_alvo = fazendas[0]
        df_faz = df_micro[df_micro["fazenda"] == fazenda_alvo].copy()

        # 3. Configurar contexto batch minino
        atividades_reais = df_faz["atividade"].dropna().unique().tolist()
        turmas_mock = [
            {"nome": "T_ROB", "operarios": 10, "atividades": atividades_reais},
            {"nome": "T_MEC", "operarios": 3, "atividades": []},
        ]
        
        cfg = {
            "arquivo_micro": os.path.basename(REAL_MICRO),
            "tarifas": tarifas,
            "custo_hora_tf": custo,
            "sequencia": {
                 "filtros_plantio": ["plantio", "replantio"],
                 "filtros_irrigacao": ["irrigacao", "irrig"],
                 "fases_cascata": {
                     "PRE-PLANTIO": ["coveamento", "rocada", "controle"],
                     "PLANTIO": ["plantio", "replantio"],
                     "POS-PLANTIO": ["manutencao", "irrigacao", "adubacao"]
                 }
            },
            "orcamento_estrito": False
        }
        
        ctx = {
            "prazo_meses": 6.0,
            "mes_ref": 1,
            "ano_ref": 2026,
            "dia_ref": 1,
            "data_inicio_txt": "01/01/2026",
            "jornada": 4.6,
            "executores": {"T_ROB": 10, "T_MEC": 3},
            "turmas": turmas_mock,
            "substituicoes_template": {},
            "penalidade": 1.0,
            "modo": "batch",
            "session_hh": {},
            "modo_seq": "implantacao",
            "usar_bloqueio_global": False,
            "usar_reforco_automatico": True,
            "usar_pool_pos_bloqueio": False
        }

        # 4. Rodar processamento (simula E2E)
        resultado = calcular_cronograma_inteligente(
            cfg=cfg,
            df_faz=df_faz,
            fazenda=fazenda_alvo,
            esperar_enter=False,
            ctx=ctx
        )
        
        self.assertIsNotNone(resultado, "Scheduler retornou None para dados reais")
        self.assertIsInstance(resultado, dict, "Resultado do scheduler deve ser dict")
        self.assertIn("cronograma", resultado)
        self.assertGreaterEqual(len(resultado["cronograma"]), 0)
        
        # 5. Check if output file was created
        from src.atm.orca.config import OUTPUT_DIR
        out_dir = Path(OUTPUT_DIR)
        
        # Procurar por Dossier daquela fazenda
        escaped_fazenda = fazenda_alvo.replace("/", "_").replace(" ", "_")
        arquivos = list(out_dir.glob(f"Dossier_{escaped_fazenda}*OPERACIONAL*.xlsx"))
        self.assertTrue(len(arquivos) > 0, "Dossier operacional xlsx nao foi gerado")
        
        # Ler o arquivo e checar abas
        excel_path = arquivos[0]
        xls = pd.ExcelFile(excel_path)
        self.assertIn("CRONOGRAMA_DETALHADO", xls.sheet_names, "Aba CRONOGRAMA_DETALHADO faltando")

if __name__ == "__main__":
    unittest.main()
