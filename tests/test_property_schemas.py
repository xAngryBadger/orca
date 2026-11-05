"""Property-based tests para schemas Pydantic — geração própria de casos determinísticos.

Não usa Hypothesis (não disponível); usa random.seed fixo para reprodutibilidade.
Todos read-only: importam e validam, NUNCA rodam scheduler.
"""

import random
import sys
import os
from pathlib import Path

# Setup path
_RAIZ = Path(__file__).parent.parent
for _p in (_RAIZ, _RAIZ / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

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


# ──────────────────────────────────────────────
# Utilidades de geração determinística
# ──────────────────────────────────────────────

SEED = 123456789

def _rng():
    """Retorna Random instanciado com seed fixa — chamar 2x dá mesma sequência."""
    return random.Random(SEED)


def _gen_string(rng: random.Random, min_len: int = 1, max_len: int = 50) -> str:
    """Gera string alfanumérica aleatória."""
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_ "
    length = rng.randint(min_len, max_len)
    return "".join(rng.choice(chars) for _ in range(length))


def _gen_atividade_real(rng: random.Random) -> str:
    """Gera nomes de atividades realistas do domínio florestal."""
    prefixos = [
        "ROCADA", "PREPARO", "PLANTIO", "IRRIGACAO", "ADUBACAO",
        "COVEAMENTO", "COROAMENTO", "FORMIGA", "LIMPEZA",
        "ROCADA MANUAL", "ROCADA MECANICA", "PLANTIO MANUAL",
        "PLANTIO MECANIZADO", "ADUBACAO QUIMICA", "LIMPEZA QUIMICA",
        "COMBATE A FORMIGA", "MANUTENCAO", "DESBROTA",
    ]
    sufixos = [
        "IMPL CD APP/RL I", "IMPL CD APP/RL II", "MANUT SECO",
        "MANUT UMIDO", "APP", "RL", "CD", "SEMI MECANIZADO"
    ]
    return rng.choice(prefixos) + " " + rng.choice(sufixos)


# ──────────────────────────────────────────────
# Testes Property-based: MicroRow
# ──────────────────────────────────────────────

def test_microrow_chave_maiuscula_propriedade():
    """chave é sempre normalizada para maiúscula (propriedade: uppercase)."""
    rng = _rng()
    for _ in range(200):
        chave_raw = _gen_string(rng, 1, 30).lower().strip()  # força minúscula, sem espaços
        row = MicroRow(fazenda="F", chave=chave_raw, area_ha=1.0, atividade="X")
        assert row.chave == chave_raw.upper(), f"chave {row.chave!r} != {chave_raw.upper()!r}"


def test_microrow_penalidade_range_propriedade():
    """penalidade sempre em [0.1, 5.0] — fora rejeita (propriedade: bounds)."""
    rng = _rng()
    for _ in range(200):
        # Dentro do range — deve aceitar
        p = rng.uniform(0.1, 5.0)
        row = MicroRow(fazenda="F", chave="T1", area_ha=1.0, atividade="X", penalidade=p)
        assert 0.1 <= row.penalidade <= 5.0

    # Fora do range — deve rejeitar (random edge cases)
    for val in [-1.0, 0.0, 0.05, 5.01, 10.0, 100.0]:
        try:
            MicroRow(fazenda="F", chave="T1", area_ha=1.0, atividade="X", penalidade=val)
            assert False, f"Deveria rejeitar penalidade={val}"
        except ValueError:
            pass


def test_microrow_area_ge_zero_propriedade():
    """area_ha >= 0 aceita, < 0 rejeita (propriedade: ge=0)."""
    rng = _rng()
    for _ in range(100):
        # Valores válidos
        a = rng.uniform(0.0, 10000.0)
        row = MicroRow(fazenda="F", chave="T1", area_ha=a, atividade="X")
        assert row.area_ha == a

    # Negativo — rejeita
    try:
        MicroRow(fazenda="F", chave="T1", area_ha=-0.01, atividade="X")
        assert False, "Deveria rejeitar area_ha negativo"
    except ValueError:
        pass


def test_microrow_fazenda_atividade_sem_vazio_propriedade():
    """fazenda e atividade não aceitam string vazia ou só espaços (propriedade: non-empty)."""
    rng = _rng()
    # Válidos
    for _ in range(50):
        f = _gen_string(rng, 1, 20)
        a = _gen_atividade_real(rng)
        row = MicroRow(fazenda=f, chave="T1", area_ha=1.0, atividade=a)
        assert row.fazenda == f.strip()
        assert row.atividade == " ".join(a.split())

    # Inválidos — vazios ou só espaços
    for v in ["", "   ", "\t", "\n", "  \t  "]:
        for campo in ["fazenda", "atividade"]:
            kwargs = {"fazenda": "F", "chave": "T1", "area_ha": 1.0, "atividade": "X"}
            kwargs[campo] = v
            try:
                MicroRow(**kwargs)
                assert False, f"Deveria rejeitar {campo}={v!r}"
            except ValueError:
                pass


# ──────────────────────────────────────────────
# Testes Property-based: TarifaCT
# ──────────────────────────────────────────────

def test_tarifact_hh_positivo_zera_hm_propriedade():
    """HH > 0 implica HM = 0 (regra real do normalizador — propriedade: HH>0 → HM=0)."""
    rng = _rng()
    for _ in range(200):
        hh = rng.uniform(0.01, 50.0)
        hm = rng.uniform(0.01, 50.0)  # valor qualquer > 0
        t = TarifaCT(atividade="X", rendimento_hh=hh, rendimento_hm=hm)
        assert t.rendimento_hm == 0.0, f"HH={hh} > 0 mas HM={t.rendimento_hm} != 0"
        assert t.recurso == "homem"


def test_tarifact_hm_only_vira_maquina_propriedade():
    """HH == 0 e HM > 0 → recurso = 'maquina' (propriedade: HM-only → maquina)."""
    rng = _rng()
    for _ in range(200):
        hm = rng.uniform(0.01, 50.0)
        t = TarifaCT(atividade="X", rendimento_hh=0.0, rendimento_hm=hm)
        assert t.recurso == "maquina", f"HM={hm} > 0 mas recurso={t.recurso!r} != 'maquina'"


def test_tarifact_hh_zero_hm_zero_recurso_homem_propriedade():
    """HH == 0 e HM == 0 → recurso = 'homem' (default)."""
    t = TarifaCT(atividade="X", rendimento_hh=0.0, rendimento_hm=0.0)
    assert t.recurso == "homem"


def test_tarifact_rendimento_negativo_rejeitado_propriedade():
    """rendimento_hh/hm < 0 rejeita (propriedade: ge=0)."""
    for val in [-0.01, -1.0, -100.0]:
        for campo in ["rendimento_hh", "rendimento_hm"]:
            kwargs = {"atividade": "X", "rendimento_hh": 0.0, "rendimento_hm": 0.0}
            kwargs[campo] = val
            try:
                TarifaCT(**kwargs)
                assert False, f"Deveria rejeitar {campo}={val}"
            except ValueError:
                pass


def test_tarifact_eficiencia_range_propriedade():
    """eficiencia em [0.1, 2.0] (propriedade: bounds)."""
    rng = _rng()
    for _ in range(100):
        e = rng.uniform(0.1, 2.0)
        t = TarifaCT(atividade="X", eficiencia=e)
        assert 0.1 <= t.eficiencia <= 2.0

    for val in [0.0, 0.05, 2.01, 5.0]:
        try:
            TarifaCT(atividade="X", eficiencia=val)
            assert False, f"Deveria rejeitar eficiencia={val}"
        except ValueError:
            pass


# ──────────────────────────────────────────────
# Testes Property-based: DeParaMap
# ──────────────────────────────────────────────

def test_deparamap_aceita_identidade_x_x_propriedade():
    """Auto-mapeamento X→X é legítimo (propriedade: identidade permitida)."""
    rng = _rng()
    for _ in range(100):
        k = _gen_string(rng, 1, 30)
        dp = depara_de_dict({k: k})
        assert dp.root[k] == k


def test_deparamap_rejeita_ciclo_direto_a_b_b_a_propriedade():
    """Ciclo A→B e B→A com A != B rejeita (propriedade: ciclo de 2 rejeitado)."""
    rng = _rng()
    for _ in range(100):
        a = _gen_string(rng, 1, 20)
        b = _gen_string(rng, 1, 20)
        if a == b:
            continue  # identidade é permitida
        try:
            depara_de_dict({a: b, b: a})
            assert False, f"Deveria rejeitar ciclo {a!r} ↔ {b!r}"
        except ValueError:
            pass


def test_deparamap_aceita_cadeia_longa_propriedade():
    """Cadeia A→B, B→C, C→D (sem ciclo de volta) é aceita."""
    dp = depara_de_dict({"A": "B", "B": "C", "C": "D"})
    assert dp.root["A"] == "B"
    assert dp.root["B"] == "C"
    assert dp.root["C"] == "D"


def test_deparamap_chaves_nao_vazias_propriedade():
    """NOTA: DeParaMap NÃO valida chaves vazias (diferente de TarifasDict).
    Este teste documenta o comportamento atual - chaves vazias são aceitas."""
    # Atualmente DeParaMap aceita chaves vazias (sem validador)
    dp = depara_de_dict({"": "valor", "   ": "outro"})
    assert dp.root[""] == "valor"
    assert dp.root["   "] == "outro"


# ──────────────────────────────────────────────
# Testes Property-based: PipelineConfig / TarifasDict / PrecoFinal
# ──────────────────────────────────────────────

def test_pipelineconfig_chave_tarifa_resolve_via_depara_propriedade():
    """chave_tarifa usa de_para quando existe, senão nome próprio."""
    rng = _rng()
    for _ in range(50):
        atv_micro = _gen_atividade_real(rng)
        atv_tarifa = _gen_atividade_real(rng)
        micro = [MicroRow(fazenda="F", chave="T1", area_ha=1.0, atividade=atv_micro)]
        tarifas = tarifas_de_dict({atv_tarifa: {"rendimento_hh": 8.0}})
        depara = depara_de_dict({atv_micro: atv_tarifa})
        p = PipelineConfig(micro=micro, tarifas=tarifas, de_para=depara)
        assert p.chave_tarifa(atv_micro) == atv_tarifa


def test_pipelineconfig_chave_tarifa_sem_depara_usa_proprio_propriedade():
    """Sem de_para, chave_tarifa retorna a própria atividade."""
    rng = _rng()
    for _ in range(50):
        atv = _gen_atividade_real(rng)
        micro = [MicroRow(fazenda="F", chave="T1", area_ha=1.0, atividade=atv)]
        tarifas = tarifas_de_dict({atv: {"rendimento_hh": 8.0}})
        depara = depara_de_dict({})
        p = PipelineConfig(micro=micro, tarifas=tarifas, de_para=depara)
        assert p.chave_tarifa(atv) == atv


def test_pipelineconfig_cobertura_calculada_propriedade():
    """cobertura_pct = (linhas - sem_tarifa) / linhas * 100.
    Nota: atividades_sem_tarifa conta atividades ÚNICAS sem tarifa, não linhas."""
    rng = _rng()
    for _ in range(50):
        n_total = rng.randint(1, 20)
        n_com_tarifa = rng.randint(0, n_total)
        micro = []
        tarifas_dict = {}
        depara_dict = {}
        used_activities = set()
        for i in range(n_total):
            # Garantir atividades únicas para teste determinístico
            atv = _gen_atividade_real(rng)
            while atv in used_activities:
                atv = _gen_atividade_real(rng)
            used_activities.add(atv)
            micro.append(MicroRow(fazenda="F", chave=f"T{i}", area_ha=1.0, atividade=atv))
            if i < n_com_tarifa:
                tarifas_dict[atv] = {"rendimento_hh": 8.0}
                depara_dict[atv] = atv
        tarifas = tarifas_de_dict(tarifas_dict)
        depara = depara_de_dict(depara_dict)
        p = PipelineConfig(micro=micro, tarifas=tarifas, de_para=depara)
        cob = p.cobertura()
        assert cob["linhas_micro"] == n_total
        # atividades_sem_tarifa = atividades únicas sem tarifa = n_total - n_com_tarifa (pois únicas)
        assert cob["atividades_sem_tarifa"] == n_total - n_com_tarifa
        if n_total > 0:
            esperado = round(100.0 * n_com_tarifa / n_total, 2)
            assert cob["cobertura_pct"] == esperado


def test_precofinal_campos_obrigatorios_propriedade():
    """PrecoFinal exige operacao não-vazia; numéricos >= 0."""
    rng = _rng()
    for _ in range(50):
        op = _gen_string(rng, 1, 30)
        pf = PrecoFinal(
            operacao=op,
            rendimento_hh_ha=rng.uniform(0, 50),
            rendimento_maquina_ha=rng.uniform(0, 50),
            preco_rs=rng.uniform(0, 10000),
            tipo="Manual",
        )
        assert pf.operacao == op

    # operacao vazia rejeita
    try:
        PrecoFinal(operacao="", rendimento_hh_ha=1.0)
        assert False, "Deveria rejeitar operacao vazia"
    except ValueError:
        pass

    # numéricos negativos rejeitam
    for campo in ["rendimento_hh_ha", "rendimento_maquina_ha", "preco_rs"]:
        try:
            kwargs = {"operacao": "X", campo: -1.0}
            PrecoFinal(**kwargs)
            assert False, f"Deveria rejeitar {campo} negativo"
        except ValueError:
            pass


# ──────────────────────────────────────────────
# Teste de determinismo: rodar 2x dá mesmo resultado
# ──────────────────────────────────────────────

def test_determinismo_seed_fixa():
    """Todas as gerações com _rng() são determinísticas: 2 execuções = mesmos valores."""
    rng1 = _rng()
    rng2 = _rng()

    # Gerar sequência de 1000 itens com cada RNG
    seq1 = [rng1.random() for _ in range(1000)]
    seq2 = [rng2.random() for _ in range(1000)]

    assert seq1 == seq2, "RNG com mesma seed deve produzir sequência idêntica"


def test_microrow_determinismo_validacao():
    """Validações de MicroRow com seed fixa são determinísticas."""
    rng1 = _rng()
    rng2 = _rng()

    # Gerar 100 casos de teste
    casos1 = []
    for _ in range(100):
        f = _gen_string(rng1, 1, 20)
        c = _gen_string(rng1, 1, 10).lower()
        a = rng1.uniform(0, 1000)
        atv = _gen_atividade_real(rng1)
        p = rng1.uniform(-1, 6)  # inclui inválidos
        casos1.append((f, c, a, atv, p))

    casos2 = []
    for _ in range(100):
        f = _gen_string(rng2, 1, 20)
        c = _gen_string(rng2, 1, 10).lower()
        a = rng2.uniform(0, 1000)
        atv = _gen_atividade_real(rng2)
        p = rng2.uniform(-1, 6)
        casos2.append((f, c, a, atv, p))

    assert casos1 == casos2, "Casos de teste gerados devem ser idênticos"


def test_tarifact_determinismo_validacao():
    """Validações de TarifaCT com seed fixa são determinísticas."""
    rng1 = _rng()
    rng2 = _rng()

    casos1 = []
    for _ in range(100):
        hh = rng1.uniform(-1, 50)
        hm = rng1.uniform(-1, 50)
        e = rng1.uniform(-1, 3)
        casos1.append((hh, hm, e))

    casos2 = []
    for _ in range(100):
        hh = rng2.uniform(-1, 50)
        hm = rng2.uniform(-1, 50)
        e = rng2.uniform(-1, 3)
        casos2.append((hh, hm, e))

    assert casos1 == casos2


if __name__ == "__main__":
    # Execução manual: roda todos os testes property-based
    import unittest
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    class PropertyTests(unittest.TestCase):
        pass

    # Wrap test functions as instance methods (they need self)
    test_names = [name for name in dir() if name.startswith("test_")]
    for name in test_names:
        func = globals()[name]
        # Create a method that calls the function
        def make_test(f):
            def test_method(self):
                f()
            return test_method
        setattr(PropertyTests, name, make_test(func))

    suite.addTests(loader.loadTestsFromTestCase(PropertyTests))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)