"""Ajuste de escopo de atividades e utilidades de caminho — dominio puro.

Extraido de app.py para quebrar o ciclo scheduler_core <-> app:
scheduler_core precisa destas funcoes, e app importa scheduler_core.
"""

import os

import pandas as pd

from ..text_utils import _norm_atv, normalizar_chave, parse_intervalos_escolha
from ..turmas import _catalogo_atividades_completo, _mostrar_catalogo_atividades
from ..ui import (
    confirmar,
    esperar,
    ok,
    pedir_float,
    prompt,
    selecionar,
    sub,
    aviso,
)


def _menu_ajustar_escopo_atividades(df_faz, cfg=None, atividades_catalogo=None):
    """
    Ajustes por execucao no escopo atual:
      - substituir atividade
      - remover atividade
      - adicionar atividade em talhao(es)
    """
    if df_faz is None or df_faz.empty:
        return df_faz

    if "atividade" not in df_faz.columns or "chave" not in df_faz.columns:
        aviso("Escopo sem colunas necessarias para ajuste de atividade.")
        return df_faz

    out = df_faz.copy()
    if "area_ha" not in out.columns:
        out["area_ha"] = 0.0
    if "penalidade" not in out.columns:
        out["penalidade"] = 1.0

    def _atividades():
        return sorted(
            {
                str(x).strip()
                for x in out["atividade"].dropna().tolist()
                if str(x).strip()
            },
            key=str,
        )

    def _talhoes():
        return sorted(
            {str(x).strip() for x in out["chave"].dropna().tolist() if str(x).strip()},
            key=str,
        )

    while True:
        atvs = _atividades()
        catalogo_all = _catalogo_atividades_completo(
            atvs,
            cfg=cfg,
            atividades_catalogo=atividades_catalogo,
        )
        tls = _talhoes()
        sub()
        print(G + BL + "  AJUSTE DE ATIVIDADES (APENAS NESTA EXECUCAO)" + RS)
        print(
            DM
            + f"  Atividades no escopo: {len(atvs)} | Catalogo completo: {len(catalogo_all)} | Talhoes no escopo: {len(tls)}"
            + RS
        )
        op = selecionar(
            "OPERACAO DE AJUSTE",
            [
                "Substituir atividade",
                "Remover atividade",
                "Adicionar atividade",
                "Ver listas completas (escopo x catalogo)",
                "Concluir ajustes",
            ],
        )
        if not op or op == "Concluir ajustes":
            break

        if op == "Ver listas completas (escopo x catalogo)":
            _mostrar_catalogo_atividades(atvs, catalogo_all)
            esperar()
            continue

        if op == "Substituir atividade":
            if not atvs:
                aviso("Sem atividades para substituir.")
                continue
            print(DM + " Origens (ex: 1,3,5-8 ou ENTER para selecionar uma)" + RS)
            for i, a in enumerate(atvs, 1):
                print(G + f" [{i:2}] " + C + str(a)[:70] + RS)
            raw = prompt("Origens", "")
            if str(raw).strip():
                idxs = parse_intervalos_escolha(raw, len(atvs))
                if not idxs:
                    aviso("Nenhum indice valido.")
                    continue
                srcs = [atvs[i] for i in idxs]
            else:
                src = selecionar("ATIVIDADE ORIGEM", atvs)
                if not src:
                    continue
                srcs = [src]
            destinos = [x for x in catalogo_all if x not in srcs]
            dst_opt = selecionar(
                "DESTINO", destinos + ["[DIGITAR NOVA ATIVIDADE]"]
            )
            if not dst_opt:
                continue
            dst = (
                prompt("Nova atividade", "")
                if dst_opt == "[DIGITAR NOVA ATIVIDADE]"
                else dst_opt
            )
            dst = _norm_atv(dst)
            if not dst:
                aviso("Destino invalido.")
                continue
            n_sub = 0
            for src in srcs:
                mask = out["atividade"].astype(str) == str(src)
                n_sub += int(mask.sum())
                out.loc[mask, "atividade"] = dst
            ok(f"{len(srcs)} atividade(s) substituida(s) -> '{dst}' ({n_sub} linhas).")
            continue

        if op == "Remover atividade":
            if not atvs:
                aviso("Sem atividades para remover.")
                continue
            print(DM + " Remover (ex: 1,3,5-8 ou ENTER para selecionar uma)" + RS)
            for i, a in enumerate(atvs, 1):
                print(G + f" [{i:2}] " + C + str(a)[:70] + RS)
            raw = prompt("Remover", "")
            if str(raw).strip():
                idxs = parse_intervalos_escolha(raw, len(atvs))
                if not idxs:
                    aviso("Nenhum indice valido.")
                    continue
                rms = [atvs[i] for i in idxs]
            else:
                rm = selecionar("ATIVIDADE PARA REMOVER", atvs)
                if not rm:
                    continue
                rms = [rm]
            n0 = len(out)
            mask = out["atividade"].astype(str).isin([str(r) for r in rms])
            out = out[~mask].copy()
            ok(f"{len(rms)} atividade(s) removida(s) ({n0 - len(out)} linha(s)).")
            continue

        if op == "Adicionar atividade":
            print(DM + " Atividades (ex: 1,3,5-8 ou ENTER para selecionar uma)" + RS)
            for i, a in enumerate(catalogo_all, 1):
                print(G + f" [{i:2}] " + C + str(a)[:70] + RS)
            print(G + f" [{len(catalogo_all)+1:2}] " + C + "[DIGITAR NOVA ATIVIDADE]" + RS)
            raw = prompt("Atividades", "")
            if str(raw).strip():
                idxs = parse_intervalos_escolha(raw, len(catalogo_all) + 1)
                novas = []
                for i in idxs:
                    if i < len(catalogo_all):
                        novas.append(catalogo_all[i])
                    else:
                        t = prompt("Nome da atividade", "")
                        t = _norm_atv(t)
                        if t:
                            novas.append(t)
                if not novas:
                    aviso("Nenhuma atividade valida.")
                    continue
            else:
                base_opt = selecionar(
                    "NOVA ATIVIDADE",
                    catalogo_all + ["[DIGITAR NOVA ATIVIDADE]"],
                )
                if not base_opt:
                    continue
                nova = (
                    prompt("Nome da atividade", "")
                    if base_opt == "[DIGITAR NOVA ATIVIDADE]"
                    else base_opt
                )
                nova = _norm_atv(nova)
                if not nova:
                    aviso("Atividade invalida.")
                    continue
                novas = [nova]
            op_t = selecionar(
                "APLICAR EM",
                [
                    "Todos os talhoes do escopo",
                    "Talhoes por lista",
                    "Talhoes por texto",
                ],
            )
            if not op_t:
                continue
            sel_talhoes = tls[:]
            if op_t == "Talhoes por lista":
                print(DM + "  Digite numeros separados por virgula (ex.: 1,3,7)." + RS)
                for i, t in enumerate(tls, 1):
                    print(G + f"  [{i:2}] " + C + str(t) + RS)
                raw = prompt("Talhoes", "")
                idxs = []
                for p in str(raw).replace(";", ",").split(","):
                    p = p.strip()
                    if p.isdigit():
                        iv = int(p)
                        if 1 <= iv <= len(tls):
                            idxs.append(iv - 1)
                idxs = sorted(set(idxs))
                sel_talhoes = [tls[i] for i in idxs]
            elif op_t == "Talhoes por texto":
                fx = normalizar_chave(prompt("Texto no talhao", ""))
                sel_talhoes = [t for t in tls if fx and fx in normalizar_chave(t)]

            if not sel_talhoes:
                aviso("Nenhum talhao selecionado para adicionar atividade.")
                continue

            area_def = float(out["area_ha"].median() or 1.0)
            area_nova = pedir_float(
                "Area/ha para nova atividade (por talhao)", round(area_def, 2),
                allow_zero=True,
            )
            pen_def = float(out["penalidade"].median() or 1.0)
            pen_nova = pedir_float(
                "Penalidade de terreno da nova atividade", round(pen_def, 2),
                allow_zero=False,
            )

            add_rows = []
            for nova in novas:
                for th in sel_talhoes:
                    ja = out[
                        (out["chave"].astype(str) == str(th))
                        & (out["atividade"].astype(str) == str(nova))
                    ]
                    if not ja.empty:
                        continue
                    ref = out[out["chave"].astype(str) == str(th)].head(1)
                    row = ref.iloc[0].to_dict() if not ref.empty else {}
                    row["chave"] = th
                    row["atividade"] = nova
                    row["area_ha"] = float(area_nova)
                    row["penalidade"] = float(pen_nova)
                    add_rows.append(row)
            if add_rows:
                out = pd.concat([out, pd.DataFrame(add_rows)], ignore_index=True)
                ok(f"{len(novas)} atividade(s) adicionada(s) em {len(add_rows)} linha(s).")

    return out


def _proximo_caminho_livre(pasta, nome_arquivo):
    """
    Retorna nome/caminho sem colisao:
    - se nao existe, usa o nome original
    - se existe, gera sufixo _v2, _v3...
    """
    base, ext = os.path.splitext(str(nome_arquivo))
    candidato_nome = str(nome_arquivo)
    candidato_path = os.path.join(pasta, candidato_nome)
    if not os.path.exists(candidato_path):
        return candidato_nome, candidato_path
    i = 2
    while True:
        candidato_nome = f"{base}_v{i}{ext}"
        candidato_path = os.path.join(pasta, candidato_nome)
        if not os.path.exists(candidato_path):
            return candidato_nome, candidato_path
        i += 1
