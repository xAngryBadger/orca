#!/usr/bin/env python3
"""Generate minimal microplanejamento .xlsx for E2E testing.

Creates a file with 3 activities across 2 talhoes in 1 fazenda,
using activity names that match entries in the fixture tarifas
so HH resolution doesn't silently zero out.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd

FIXTURE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_minimal_microplanejamento(path=None):
    path = path or os.path.join(FIXTURE_DIR, "minimal_micro.xlsx")
    df = pd.DataFrame([
        {
            "NOME FAZENDA": "FAZENDA TESTE",
            "CHAVE POLIGONO": "TALHAO 01",
            "AREA TRABALHADA ESTIMADA (HECTARE)": 10.0,
            "ATIVIDADES": "ROÇADA MANUAL Impl. PL APP/RL I",
        },
        {
            "NOME FAZENDA": "FAZENDA TESTE",
            "CHAVE POLIGONO": "TALHAO 01",
            "AREA TRABALHADA ESTIMADA (HECTARE)": 10.0,
            "ATIVIDADES": "COMBATE A FORMIGAS Impl. PL APP/ RL",
        },
        {
            "NOME FAZENDA": "FAZENDA TESTE",
            "CHAVE POLIGONO": "TALHAO 02",
            "AREA TRABALHADA ESTIMADA (HECTARE)": 15.0,
            "ATIVIDADES": "ROÇADA MANUAL Impl. PL APP/RL I",
        },
        {
            "NOME FAZENDA": "FAZENDA TESTE",
            "CHAVE POLIGONO": "TALHAO 02",
            "AREA TRABALHADA ESTIMADA (HECTARE)": 15.0,
            "ATIVIDADES": "COMBATE A FORMIGAS Impl. PL APP/ RL",
        },
        {
            "NOME FAZENDA": "FAZENDA TESTE",
            "CHAVE POLIGONO": "TALHAO 02",
            "AREA TRABALHADA ESTIMADA (HECTARE)": 15.0,
            "ATIVIDADES": "PLANTIO MANUAL APP/RL",
        },
    ])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Microplanejamento", index=False)
    return path


def create_minimal_config_json(path=None):
    """Create a config.json with tarifas matching the fixture activities."""
    import json
    path = path or os.path.join(FIXTURE_DIR, "minimal_config.json")
    cfg = {
        "de_para": {},
        "tarifas": {
            "ROÇADA MANUAL Impl. PL APP/RL I": {
                "rendimento_hh": 8.0,
                "rendimento_hm": 0.0,
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "tipo": "Manual",
                "preco_unit": 0.0,
                "recurso": "homem",
                "eficiencia": 1.0,
            },
            "COMBATE A FORMIGAS Impl. PL APP/ RL": {
                "rendimento_hh": 3.0,
                "rendimento_hm": 0.0,
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "tipo": "Manual",
                "preco_unit": 0.0,
                "recurso": "homem",
                "eficiencia": 1.0,
            },
            "PLANTIO MANUAL APP/RL": {
                "rendimento_hh": 15.8,
                "rendimento_hm": 0.0,
                "preco_ha": 0.0,
                "custo_hora": 0.0,
                "custo_ha": 0.0,
                "tipo": "Manual",
                "preco_unit": 0.0,
                "recurso": "homem",
                "eficiencia": 1.0,
            },
        },
        "atividades": {},
        "orcamento_estrito": True,
        "filtros_bloqueio_global": ["plantio", "irrig"],
        "fazendas_ct": ["FAZENDA TESTE"],
        "sequencia": {
            "modo": "implantacao",
        },
        "modo_somente_hh": True,
        "empresas": {},
        "comparativo": {"execucao_compacta": True},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


def create_minimal_stg_tarifas(path=None):
    """Cria xlsx no formato STG_TARIFAS (mesmas atividades do fixture de micro)."""
    path = path or os.path.join(FIXTURE_DIR, "minimal_stg.xlsx")
    df = pd.DataFrame([
        {"atividade": "ROÇADA MANUAL Impl. PL APP/RL I", "tipo": "Manual", "rendimento_hh": 8.0,
         "rendimento_hm": 0.0, "preco_ha": 0.0, "custo_hora": 0.0, "custo_ha": 0.0, "fonte_aba": "Preço Final"},
        {"atividade": "COMBATE A FORMIGAS Impl. PL APP/ RL", "tipo": "Manual", "rendimento_hh": 3.0,
         "rendimento_hm": 0.0, "preco_ha": 0.0, "custo_hora": 0.0, "custo_ha": 0.0, "fonte_aba": "Preço Final"},
        {"atividade": "PLANTIO MANUAL APP/RL", "tipo": "Manual", "rendimento_hh": 15.8,
         "rendimento_hm": 0.0, "preco_ha": 0.0, "custo_hora": 0.0, "custo_ha": 0.0, "fonte_aba": "Preço Final"},
    ])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="STG_TARIFAS", index=False)
    return path


if __name__ == "__main__":
    mp = create_minimal_microplanejamento()
    print(f"Created: {mp}")
    cp = create_minimal_config_json()
    print(f"Created: {cp}")
    sp = create_minimal_stg_tarifas()
    print(f"Created: {sp}")
