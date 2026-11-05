"""
SRF constants — large data dictionaries loaded from YAML.

The data is pure data (no code logic) and lives under ``data/`` as YAML so it
can be versioned/diffed/inspected without touching Python:

- ``data/ct317_hardcode_hh_base.yaml``    -> ``CT317_HARDCODE_HH_BASE``
- ``data/comparativo_manual_mec.yaml``    -> ``COMPARATIVO_MANUAL_MEC``
- ``data/default_depara_exame_ct317.yaml`` -> ``DEFAULT_DEPARA_EXAME_CT317``

IMPORTANT: The original monolith uses accented strings as dictionary keys
(matching the CT317 Excel source). The YAML preserves the EXACT original
keys to maintain lookup correctness. Do NOT normalize accents on keys.
"""

import os

import yaml

_DATA_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
    "data",
)


def _carregar_yaml_constantes(nome_arquivo, nome_constante):
    caminho = os.path.join(_DATA_DIR, nome_arquivo)
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(
            f"Falha ao carregar constantes de {caminho} ({nome_constante}): {exc}"
        ) from exc
    if not isinstance(dados, dict):
        raise RuntimeError(
            f"{caminho} deveria ser um mapeamento, retornou {type(dados).__name__}"
        )
    return dados


CT317_HARDCODE_HH_BASE = _carregar_yaml_constantes(
    "ct317_hardcode_hh_base.yaml", "CT317_HARDCODE_HH_BASE"
)

COMPARATIVO_MANUAL_MEC = _carregar_yaml_constantes(
    "comparativo_manual_mec.yaml", "COMPARATIVO_MANUAL_MEC"
)

DEFAULT_DEPARA_EXAME_CT317 = _carregar_yaml_constantes(
    "default_depara_exame_ct317.yaml", "DEFAULT_DEPARA_EXAME_CT317"
)

del _carregar_yaml_constantes


# ═══════════════════════════════════════════════════════════════════════════════
# FASE CORES HEX — color mapping for Excel timeline visualization
# ═══════════════════════════════════════════════════════════════════════════════
_FASE_CORES_HEX = {
    "rocada": "4472C4",
    "formiga": "ED7D31",
    "coroamento": "70AD47",
    "coveamento": "FFC000",
    "adubacao_quimica": "9B59B6",
    "plantio": "2ECC71",
    "irrigacao": "3498DB",
    "limpeza_quimica": "95A5A6",
    "demais": "BDC3C7",
    "reforco": "D5DBDB",
    "pool": "1ABC9C",
}
