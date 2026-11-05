"""Property-based tests para gate de cascata — classificar_fase_cascata_valor.

Geração própria de casos determinísticos (random.seed fixo).
Read-only: importa e valida, NUNCA roda scheduler.
"""

import random
import sys
from pathlib import Path

# Setup path
_RAIZ = Path(__file__).parent.parent
for _p in (_RAIZ, _RAIZ / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.atm.orca.scheduler import classificar_fase_cascata_valor  # noqa: E402
from src.atm.orca.config import _default_sequencia_dict  # noqa: E402


# ──────────────────────────────────────────────
# Utilidades de geração determinística
# ──────────────────────────────────────────────

SEED = 987654321

def _rng():
    """Random com seed fixa — reprodutível."""
    return random.Random(SEED)


def _gen_atividade_cascata(rng: random.Random) -> str:
    """Gera nomes de atividades que mapeiam para fases conhecidas da cascata."""
    # Mapeamento: fase -> (filtros, peso)
    fases = [
        (0.0, ["rocada", "rocada"]),
        (1.0, ["formiga", "combate a formiga", "combate a formigas"]),
        (2.0, ["coroamento", "coroa"]),
        (3.0, ["coveamento", "coveam"]),
        (4.0, ["adubacao quim", "adubacao quim", "melhora quim"]),
        (5.5, ["preparo", "preparo solo", "aracao", "gradeamento", "sulfatacao", "calagem"]),  # "outras"
        (6.0, ["plantio"]),
        (7.0, ["irrig", "irrigacao"]),
        (8.0, ["limpeza quim", "limpeza quimica"]),  # limpeza quimica pos-plantio
    ]

    fase_valor, filtros = rng.choice(fases)
    base = rng.choice(filtros)
    sufixos = ["", " IMPL CD APP/RL I", " MANUT SECO", " MANUT UMIDO", " APP", " RL", " CD"]
    return base + rng.choice(sufixos)


# ──────────────────────────────────────────────
# Configuração padrão da cascata (implantação)
# ──────────────────────────────────────────────

def _seq_cfg_padrao():
    """Retorna configuração de sequência padrão para testes."""
    return _default_sequencia_dict()


def _atividades_plantio_padrao():
    return set()


def _atividades_irrig_padrao():
    return set()


# ──────────────────────────────────────────────
# Testes Property-based: Ordem da Cascata
# ──────────────────────────────────────────────

def test_cascata_ordem_numerica_crescente_propriedade():
    """classificar_fase_cascata_valor devolve fase numérica crescente:
    Rocada(0) < Formiga(1) < Coroamento(2) < Coveamento(3) < Adubação(4) < Plantio(6) < Irrigação(7) < Limpeza(8).
    """
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    # Fases esperadas na ordem (usar os mesmos filtros do config)
    fases_esperadas = [
        ("rocada", 0.0),
        ("formiga", 1.0),
        ("coroamento", 2.0),
        ("coveamento", 3.0),
        ("adubacao quim", 4.0),
        ("plantio", 6.0),
        ("irrigacao", 7.0),
        ("limpeza quimica", 8.0),
    ]

    resultados = {}
    for nome, fase_esperada in fases_esperadas:
        # Testar várias variações de cada fase
        # Para limpeza quimica, evitar sufixos com "impl" (exclusão)
        if nome == "limpeza quimica":
            sufixos = ["", " POS PLANTIO", " MANUT SECO", " APP"]
        else:
            sufixos = ["", " IMPL CD APP/RL I", " MANUT SECO", " APP"]
        for sufixo in sufixos:
            atv = nome + sufixo
            fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
            resultados.setdefault(nome, []).append(fv)
            # Cada variação deve retornar a fase esperada
            assert fv == fase_esperada, (
                f"Atividade {atv!r}: esperado fase {fase_esperada}, "
                f"obteve {fv}"
            )

    # Verificar ordem estrita crescente
    fases_ordenadas = [resultados[nome][0] for nome, _ in fases_esperadas]
    for i in range(len(fases_ordenadas) - 1):
        assert fases_ordenadas[i] < fases_ordenadas[i + 1], (
            f"Ordem quebrada: {fases_esperadas[i][0]} ({fases_ordenadas[i]}) "
            f">= {fases_esperadas[i+1][0]} ({fases_ordenadas[i+1]})"
        )


def test_cascata_manutencao_sem_cascata_propriedade():
    """Modos manutencao_seco/umido retornam 0.0 (sem cascata)."""
    seq_cfg = _seq_cfg_padrao()
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    for modo in ["manutencao_seco", "manutencao_umido"]:
        for _ in range(50):
            atv = _gen_atividade_cascata(_rng())
            fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
            assert fv == 0.0, f"Modo {modo}: {atv!r} retornou {fv} != 0.0"


def test_cascata_atividade_nao_mapeada_fase_outras_propriedade():
    """Atividades não mapeadas em nenhuma fase → implantacao_outras_fase (default 5.5)."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    rng = _rng()
    atividades_nao_mapeadas = [
        "ATIVIDADE INEXISTENTE XYZ",
        "OUTRA COISA QUALQUER",
        "FOO BAR BAZ",
        "TESTE 123",
        "NADA A VER",
    ]

    for atv in atividades_nao_mapeadas:
        fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
        assert fv == 5.5, f"Atividade não mapeada {atv!r}: esperado 5.5, obteve {fv}"


def test_cascata_limpeza_quimica_pos_plantio_propriedade():
    """Limpeza química pós-plantio (contém 'limpeza' E 'quim', sem 'impl') → fase 8.0."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    # Casos que DEVEM ser limpeza quimica pos-plantio
    positivos = [
        "LIMPEZA QUIMICA POS PLANTIO",
        "LIMPEZA QUIMICA",
        "LIMPEZA QUIM POS",
        "APLICACAO QUIMICA LIMPEZA",
        "HERBICIDA LIMPEZA QUIM",
    ]

    # Casos que NÃO devem (têm exclusão 'impl')
    negativos = [
        "LIMPEZA QUIMICA IMPL",
        "LIMPEZA QUIMICA IMPL.",
        "LIMPEZA QUIMICA IMPL CD",
    ]

    for atv in positivos:
        fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
        assert fv == 8.0, f"{atv!r}: esperado 8.0 (limpeza quim pos-plantio), obteve {fv}"

    for atv in negativos:
        fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
        # Com exclusão 'impl', cai na fase "outras" (5.5) ou outra fase que case
        assert fv != 8.0, f"{atv!r}: NÃO deveria ser limpeza quim pos-plantio (tem 'impl')"


def test_cascata_plantio_antes_irrigacao_propriedade():
    """Plantio (fase 6) < Irrigação (fase 7) — ordem relativa fixa."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    plantios = ["PLANTIO", "PLANTIO MANUAL", "PLANTIO MECANIZADO", "PLANTIO APP/RL"]
    irrigacoes = ["IRRIGACAO", "IRRIGACAO GOTEJAMENTO", "IRRIGACAO PIVO"]

    for p in plantios:
        fp = classificar_fase_cascata_valor(p, seq_cfg, modo, ap, ai)
        assert fp == 6.0, f"Plantio {p!r}: esperado 6.0, obteve {fp}"

    for i in irrigacoes:
        fi = classificar_fase_cascata_valor(i, seq_cfg, modo, ap, ai)
        assert fi == 7.0, f"Irrigação {i!r}: esperado 7.0, obteve {fi}"

    # Plantio sempre < Irrigação
    for p in plantios:
        for i in irrigacoes:
            fp = classificar_fase_cascata_valor(p, seq_cfg, modo, ap, ai)
            fi = classificar_fase_cascata_valor(i, seq_cfg, modo, ap, ai)
            assert fp < fi, f"Plantio {p!r} ({fp}) !< Irrigação {i!r} ({fi})"


def test_cascata_fases_configuraveis_ordem_propriedade():
    """Fases configuradas em implantacao_fases mantêm ordem do índice (i)."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    fases_config = seq_cfg.get("implantacao_fases", [])
    for i, fase in enumerate(fases_config):
        for filtro in fase.get("filtros", []):
            atv = filtro.upper() + " TESTE"
            fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
            assert fv == float(i), (
                f"Fase config '{fase['id']}' índice {i}: "
                f"atividade {atv!r} deveria retornar {float(i)}, obteve {fv}"
            )

    # Verificar ordem crescente dos índices
    indices = [float(i) for i in range(len(fases_config))]
    for i in range(len(indices) - 1):
        assert indices[i] < indices[i + 1]


def test_cascata_modo_personalizado_ordem_propriedade():
    """Modo personalizado respeita ordem de personalizado_ordem."""
    seq_cfg = _seq_cfg_padrao()
    seq_cfg["modo"] = "personalizado"
    seq_cfg["personalizado_ordem"] = [
        {"id": "fase_a", "filtros": ["ALFA"], "exclusoes": []},
        {"id": "fase_b", "filtros": ["BETA"], "exclusoes": []},
        {"id": "fase_c", "filtros": ["GAMA"], "exclusoes": []},
    ]
    modo = "personalizado"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    assert classificar_fase_cascata_valor("ALFA TESTE", seq_cfg, modo, ap, ai) == 0.0
    assert classificar_fase_cascata_valor("BETA TESTE", seq_cfg, modo, ap, ai) == 1.0
    assert classificar_fase_cascata_valor("GAMA TESTE", seq_cfg, modo, ap, ai) == 2.0


# ──────────────────────────────────────────────
# Testes de robustez: entradas extremas
# ──────────────────────────────────────────────

def test_cascata_string_vazia_propriedade():
    """String vazia → fase 'outras' (5.5)."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    fv = classificar_fase_cascata_valor("", seq_cfg, modo, ap, ai)
    assert fv == 5.5


def test_cascata_case_insensitive_propriedade():
    """Classificação é case-insensitive (usa normalizar_chave internamente)."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    variacoes = [
        "rocada", "ROCADA", "Rocada", "RoCaDa",
        "FORMIGA", "formiga", "Formiga",
        "PLANTIO", "plantio", "Plantio",
    ]

    for atv in variacoes:
        fv = classificar_fase_cascata_valor(atv, seq_cfg, modo, ap, ai)
        if "rocada" in atv.lower() or "rocada" in atv.lower():
            assert fv == 0.0
        elif "formiga" in atv.lower():
            assert fv == 1.0
        elif "plantio" in atv.lower():
            assert fv == 6.0


def test_cascata_exclusoes_funcionam_propriedade():
    """Exclusões impedem match de fase."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    # Limpeza quimica tem exclusao "impl" — com "impl" não deve ser fase 8
    fv_com_exclusao = classificar_fase_cascata_valor("LIMPEZA QUIMICA IMPL", seq_cfg, modo, ap, ai)
    fv_sem_exclusao = classificar_fase_cascata_valor("LIMPEZA QUIMICA", seq_cfg, modo, ap, ai)

    assert fv_sem_exclusao == 8.0
    assert fv_com_exclusao != 8.0  # cai em outra fase


# ──────────────────────────────────────────────
# Teste de determinismo: rodar 2x dá mesmo resultado
# ──────────────────────────────────────────────

def test_determinismo_cascata_seed_fixa():
    """classificar_fase_cascata_valor é determinística para mesma entrada."""
    seq_cfg = _seq_cfg_padrao()
    modo = "implantacao"
    ap = _atividades_plantio_padrao()
    ai = _atividades_irrig_padrao()

    # Gerar 200 atividades aleatórias com seed fixa
    rng1 = _rng()
    atividades1 = [_gen_atividade_cascata(rng1) for _ in range(200)]

    rng2 = _rng()
    atividades2 = [_gen_atividade_cascata(rng2) for _ in range(200)]

    assert atividades1 == atividades2, "Geração de atividades deve ser determinística"

    # Classificar ambas as listas
    resultados1 = [classificar_fase_cascata_valor(a, seq_cfg, modo, ap, ai) for a in atividades1]
    resultados2 = [classificar_fase_cascata_valor(a, seq_cfg, modo, ap, ai) for a in atividades2]

    assert resultados1 == resultados2, "Classificação deve ser determinística"


def test_determinismo_rng_interno():
    """Verificar que _rng() produz mesma sequência em 2 chamadas."""
    rng1 = _rng()
    rng2 = _rng()

    seq1 = [rng1.random() for _ in range(500)]
    seq2 = [rng2.random() for _ in range(500)]

    assert seq1 == seq2


if __name__ == "__main__":
    import unittest
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    class PropertyCascadeTests(unittest.TestCase):
        pass

    # Wrap test functions as instance methods (they need self)
    test_names = [name for name in dir() if name.startswith("test_")]
    for name in test_names:
        func = globals()[name]
        def make_test(f):
            def test_method(self):
                f()
            return test_method
        setattr(PropertyCascadeTests, name, make_test(func))

    suite.addTests(loader.loadTestsFromTestCase(PropertyCascadeTests))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)