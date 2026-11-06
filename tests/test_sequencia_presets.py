"""Testes para presets de sequência de atividades (Missão 1)."""
import sys
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.atm.orca.config import (
    _default_sequencia_dict,
    _preset_implantacao_padrao,
    _preset_manutencao_seco_sugerido,
    _preset_manutencao_umido_sugerido,
    _aplicar_preset_sequencia,
    _SEQUENCIAS_DISPONIVEIS,
)
from src.atm.orca.scheduler import classificar_fase_cascata_valor
from src.atm.orca.text_utils import normalizar_chave


class TestSequencePresets(unittest.TestCase):
    """Testes para presets de sequência."""

    def test_preset_implantacao_padrao_existe(self):
        """Preset de implantação padrão existe e tem as fases esperadas."""
        preset = _preset_implantacao_padrao()
        self.assertEqual(preset["modo"], "implantacao")
        self.assertIn("implantacao_fases", preset)
        fases = preset["implantacao_fases"]
        self.assertGreaterEqual(len(fases), 5)
        # Verifica fases principais da cascata de implantação
        fase_ids = [f["id"] for f in fases]
        self.assertIn("rocada", fase_ids)
        self.assertIn("formiga", fase_ids)
        self.assertIn("coroamento", fase_ids)
        self.assertIn("coveamento", fase_ids)
        self.assertIn("adubacao_quimica", fase_ids)
        # Tem filtros de plantio e irrigacao
        self.assertIn("plantio", preset.get("filtros_plantio", []))
        self.assertIn("irrig", preset.get("filtros_irrigacao", []))

    def test_preset_manutencao_seco_sugerido_existe(self):
        """Preset sugerido para manutenção seco existe e não tem cascata de implantação."""
        preset = _preset_manutencao_seco_sugerido()
        self.assertEqual(preset["modo"], "manutencao_seco")
        self.assertIn("implantacao_fases", preset)
        fases = preset["implantacao_fases"]
        # Não deve ter fases de implantação como coroamento/coveamento/adubacao_quimica
        fase_ids = [f["id"] for f in fases]
        self.assertNotIn("coroamento", fase_ids)
        self.assertNotIn("coveamento", fase_ids)
        self.assertNotIn("adubacao_quimica", fase_ids)
        # Deve ter fases de manutenção
        self.assertIn("rocada_manutencao", fase_ids)
        self.assertIn("formiga_manutencao", fase_ids)
        self.assertIn("adubacao_cobertura", fase_ids)
        # Filtros de plantio/irrigacao vazios (não há plantio/irrigacao na manutenção)
        self.assertEqual(preset.get("filtros_plantio", []), [])
        self.assertEqual(preset.get("filtros_irrigacao", []), [])

    def test_preset_manutencao_umido_sugerido_existe(self):
        """Preset sugerido para manutenção úmido existe e não tem cascata de implantação."""
        preset = _preset_manutencao_umido_sugerido()
        self.assertEqual(preset["modo"], "manutencao_umido")
        self.assertIn("implantacao_fases", preset)
        fases = preset["implantacao_fases"]
        fase_ids = [f["id"] for f in fases]
        self.assertNotIn("coroamento", fase_ids)
        self.assertNotIn("coveamento", fase_ids)
        self.assertNotIn("adubacao_quimica", fase_ids)
        # Deve ter fases de manutenção incluindo invasoras/aceiro
        self.assertIn("rocada_manutencao", fase_ids)
        self.assertIn("formiga_manutencao", fase_ids)
        self.assertIn("adubacao_cobertura", fase_ids)
        self.assertIn("invasoras_aceiro", fase_ids)
        self.assertEqual(preset.get("filtros_plantio", []), [])
        self.assertEqual(preset.get("filtros_irrigacao", []), [])

    def test_aplicar_preset_sequencia_implantacao(self):
        """Aplicar preset de implantação preenche seq_cfg corretamente."""
        seq_cfg = {}
        _aplicar_preset_sequencia(seq_cfg, "implantacao")
        self.assertEqual(seq_cfg["modo"], "implantacao")
        self.assertIn("implantacao_fases", seq_cfg)
        self.assertGreaterEqual(len(seq_cfg["implantacao_fases"]), 5)

    def test_aplicar_preset_sequencia_manutencao_seco(self):
        """Aplicar preset de manutenção seco preenche seq_cfg corretamente."""
        seq_cfg = {}
        _aplicar_preset_sequencia(seq_cfg, "manutencao_seco")
        self.assertEqual(seq_cfg["modo"], "manutencao_seco")
        self.assertIn("implantacao_fases", seq_cfg)
        # Não deve ter fases de implantação
        fase_ids = [f["id"] for f in seq_cfg["implantacao_fases"]]
        self.assertNotIn("coroamento", fase_ids)
        self.assertNotIn("coveamento", fase_ids)

    def test_aplicar_preset_sequencia_manutencao_umido(self):
        """Aplicar preset de manutenção úmido preenche seq_cfg corretamente."""
        seq_cfg = {}
        _aplicar_preset_sequencia(seq_cfg, "manutencao_umido")
        self.assertEqual(seq_cfg["modo"], "manutencao_umido")
        self.assertIn("implantacao_fases", seq_cfg)
        fase_ids = [f["id"] for f in seq_cfg["implantacao_fases"]]
        self.assertIn("invasoras_aceiro", fase_ids)

    def test_aplicar_preset_sequencia_personalizado(self):
        """Modo personalizado não altera seq_cfg (mantém configuração do usuário)."""
        seq_cfg = {"personalizado_ordem": [{"id": "custom", "filtros": ["foo"], "exclusoes": []}]}
        _aplicar_preset_sequencia(seq_cfg, "personalizado")
        self.assertIn("personalizado_ordem", seq_cfg)
        self.assertEqual(len(seq_cfg["personalizado_ordem"]), 1)

    def test_aplicar_preset_sequencia_modo_desconhecido_erro(self):
        """Modo desconhecido levanta ValueError com mensagem clara."""
        seq_cfg = {}
        with self.assertRaises(ValueError) as cm:
            _aplicar_preset_sequencia(seq_cfg, "modo_inexistente")
        self.assertIn("não tem configuração de sequência válida", str(cm.exception))
        self.assertIn("modo_inexistente", str(cm.exception))

    def test_paridade_classificacao_fases_implantacao(self):
        """Preset implantação classifica fases igual ao hardcoded anterior (paridade)."""
        seq_cfg = _preset_implantacao_padrao()
        atividades_plantio = {"PLANTIO MANUAL"}
        atividades_irrig = {"IRRIGACAO"}

        # Atividades da cascata de implantação devem ter fases 0-4
        testes = [
            ("ROCADA MANUAL", 0.0),
            ("COMBATE A FORMIGAS", 1.0),
            ("COROAMENTO", 2.0),
            ("COVEAMENTO", 3.0),
            ("ADUBACAO QUIMICA", 4.0),
            ("PLANTIO MANUAL", 6.0),
            ("IRRIGACAO", 7.0),
        ]
        for atv, fase_esperada in testes:
            fase = classificar_fase_cascata_valor(
                atv, seq_cfg, "implantacao", atividades_plantio, atividades_irrig
            )
            self.assertEqual(
                fase, fase_esperada,
                f"Atividade '{atv}': esperava fase {fase_esperada}, obteve {fase}"
            )

    def test_manutencao_sem_cascata_implantacao(self):
        """Presets de manutenção não classificam atividades como fases de implantação."""
        seq_cfg_seco = _preset_manutencao_seco_sugerido()
        seq_cfg_umido = _preset_manutencao_umido_sugerido()
        atividades_plantio = set()
        atividades_irrig = set()

        # Em manutenção, atividades de implantação devem cair em "outras" (5.5)
        # ou nas fases de manutenção definidas
        atv_impl = "ROCADA MANUAL"
        fase_seco = classificar_fase_cascata_valor(
            atv_impl, seq_cfg_seco, "manutencao_seco", atividades_plantio, atividades_irrig
        )
        fase_umido = classificar_fase_cascata_valor(
            atv_impl, seq_cfg_umido, "manutencao_umido", atividades_plantio, atividades_irrig
        )
        # Devem ser classificadas na fase de roçada_manutencao (fase 0)
        self.assertEqual(fase_seco, 0.0)
        self.assertEqual(fase_umido, 0.0)

        # Atividades que não batem em nenhum filtro vão para "outras" (5.5)
        atv_desconhecida = "ATIVIDADE DESCONHECIDA XYZ"
        fase_out = classificar_fase_cascata_valor(
            atv_desconhecida, seq_cfg_seco, "manutencao_seco", atividades_plantio, atividades_irrig
        )
        self.assertEqual(fase_out, 5.5)

    def test_sequencias_disponiveis_atualizadas(self):
        """_SEQUENCIAS_DISPONIVEIS reflete os novos presets (sem [EM PROGRESSO])."""
        modos = [m[0] for m in _SEQUENCIAS_DISPONIVEIS]
        self.assertIn("implantacao", modos)
        self.assertIn("manutencao_seco", modos)
        self.assertIn("manutencao_umido", modos)
        self.assertIn("personalizado", modos)
        # Verifica que não tem mais "[EM PROGRESSO]" nas descrições
        for modo_id, descr in _SEQUENCIAS_DISPONIVEIS:
            if modo_id in ("manutencao_seco", "manutencao_umido"):
                self.assertNotIn("[EM PROGRESSO]", descr)
                self.assertNotIn("ainda nao definidas", descr.lower())


if __name__ == "__main__":
    unittest.main()