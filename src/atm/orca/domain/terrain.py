"""Avaliacao de terreno (penalidade por declividade) — dominio puro.

Extraido de app.py para quebrar o ciclo scheduler_core <-> app.
"""

from ..ui import confirmar, selecionar, sub, BL, C, DM, G, RS


def avaliar_terreno(df_faz):
    print(G + BL + "\n  REFINAMENTO DE DECLIVIDADE\n" + RS)
    print(
        DM
        + "  Isto aplica um fator multiplicativo extra sobre HH/ha (1,0 / 1,15 / 1,30), "
        "independente da classe I–V da CT. Classe I vs V ja esta na linha de preco da CT; "
        "este passo e so para penalizar o cronograma se quiser simular declive geral."
        + RS
    )
    if not confirmar("Aplicar penalidade por declive?", default=False):
        df_faz["penalidade"] = 1.0
        return df_faz
    terrenos = ["Plano (Base x1.0)", "Misto (x1.15)", "Inclinado (x1.30)"]
    t = selecionar("DECLIVIDADE", terrenos)
    if t and "Inclinado" in t:
        df_faz["penalidade"] = 1.3
    elif t and "Misto" in t:
        df_faz["penalidade"] = 1.15
    else:
        df_faz["penalidade"] = 1.0
    return df_faz
