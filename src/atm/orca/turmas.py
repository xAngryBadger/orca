"""Team (turma) management — resource editing, activity linking, conflict resolution, candidate detection."""

from .constants import CT317_HARDCODE_HH_BASE
from .monitor import _emitir_monitor_rendimentos
from .tarifas import resolver_chave_tarifa
from .text_utils import _norm_atv, atividades_por_filtro, filtrar_atividades_por_texto, normalizar_chave
from .ui import (
    BL,
    DM,
    RS,
    C,
    G,
    Y,
    aviso,
    confirmar,
    esperar,
    ok,
    pedir_float,
    prompt,
    selecionar,
    selecionar_paginado,
    sub,
)


def _menu_editar_recurso_mecanizado(recursos, pool_catalogo):
    """Permite revisar e alterar atividades/produtividade/custo de recursos mecanizados."""
    if not recursos:
        aviso("Nao ha recursos mecanizados para editar.")
        return recursos

    while True:
        sub()
        print(G + BL + "  EDICAO RETROATIVA — RECURSOS MECANIZADOS" + RS)
        nomes = [
            f"{r['nome']} ({len(r.get('atividades', set()))} atividades)"
            for r in recursos
        ]
        op = selecionar("SELECIONE O RECURSO", nomes + ["Concluir edicao"])
        if not op or op == "Concluir edicao":
            break
        idx = nomes.index(op)
        rec = recursos[idx]

        while True:
            cur = sorted(list(rec.get("atividades", set())), key=str)
            sub()
            print(G + BL + f" RECURSO: {rec['nome']}" + RS)
            print(DM + f" Produtividade: {rec.get('prod_ha_h', 0)} ha/h" + RS)
            print(DM + f" Custo/h: R$ {rec.get('custo_h', 0)}" + RS)
            print(DM + f" Atividades vinculadas: {len(cur)}" + RS)
            acao = selecionar(
                    "ACAO",
                    [
                        "Adicionar atividade",
                        "Remover atividade",
                        "Substituir atividade",
                        "Alterar produtividade",
                        "Alterar custo/h",
                        "Ver lista filtrada (mec/mecanizado/semimec)",
                        "Ver listas completas (vinculadas x catalogo)",
                        "Voltar",
                    ],
                )
            if not acao or acao == "Voltar":
                break

            if acao == "Adicionar atividade":
                disp = [a for a in pool_catalogo if a not in rec.get("atividades", [])]
                if not disp:
                    aviso("Nao ha atividade nova para adicionar.")
                    continue
                idx_add = selecionar_paginado("ADICIONAR ATIVIDADE", disp)
                if idx_add >= 0:
                    rec.setdefault("atividades", [])
                    if disp[idx_add] not in rec["atividades"]:
                        rec["atividades"].append(disp[idx_add])
                    ok("Atividade adicionada.")
                continue

            if acao == "Remover atividade":
                if not cur:
                    aviso("Recurso sem atividades vinculadas.")
                    continue
                idx_rm = selecionar_paginado("REMOVER ATIVIDADE", cur)
                if idx_rm >= 0:
                    rec.setdefault("atividades", [])
                    if cur[idx_rm] in rec["atividades"]:
                        rec["atividades"].remove(cur[idx_rm])
                    ok("Atividade removida.")
                continue

            if acao == "Substituir atividade":
                if not cur:
                    aviso("Recurso sem atividades vinculadas.")
                    continue
                idx_src = selecionar_paginado("ATIVIDADE ORIGEM", cur)
                if idx_src < 0:
                    continue
                src = cur[idx_src]
                disp = [a for a in pool_catalogo if a != src]
                idx_dst = selecionar_paginado("ATIVIDADE DESTINO", disp)
                if idx_dst >= 0:
                    dst = disp[idx_dst]
                    rec.setdefault("atividades", [])
                    if src in rec["atividades"]:
                        rec["atividades"].remove(src)
                    if dst not in rec["atividades"]:
                        rec["atividades"].append(dst)
                    ok(f"Substituida: '{src[:45]}' -> '{dst[:45]}'.")
                continue

            if acao == "Alterar produtividade":
                rec["prod_ha_h"] = pedir_float(
                    "Nova produtividade (ha/h)",
                    float(rec.get("prod_ha_h") or 0.18),
                )
                ok("Produtividade atualizada.")
                continue

            if acao == "Alterar custo/h":
                rec["custo_h"] = pedir_float(
                    "Novo custo (R$/h)",
                    float(rec.get("custo_h") or 0.0),
                    allow_zero=True,
                )
                ok("Custo/h atualizado.")
                continue

                if acao == "Ver lista filtrada (mec/mecanizado/semimec)":
                    # Filtrar apenas atividades mecanizadas (com HM > 0 ou tipo Mecanizada/SemiMecanizada)
                    atividades_mec = []
                    for atv_nome, dados in CT317_HARDCODE_HH_BASE.items():
                        if dados.get("rendimento_hm", 0) > 0 or dados.get("tipo", "").lower() in ("mecanizada", "semimecanizada"):
                            atividades_mec.append(atv_nome)

                    # Também incluir do catálogo que tenham 'mec', 'mecaniz', 'semimec' no nome
                    for atv in pool_catalogo:
                        atv_norm = normalizar_chave(str(atv))
                        if any(k in atv_norm for k in ["mec", "mecaniz", "semimec", "trator", "robo", "drone"]):
                            if atv not in atividades_mec:
                                atividades_mec.append(atv)

                    atividades_mec.sort(key=str)

                    print(G + BL + "\n LISTA FILTRADA — ATIVIDADES MECANIZADAS" + RS)
                    print(DM + " (atividades com HM > 0, 'mec' no nome, ou tipo Mecanizada/SemiMecanizada)" + RS)
                    if atividades_mec:
                        for i, a in enumerate(atividades_mec, 1):
                            # Buscar valor HM se disponível
                            hm_val = ""
                            for atv_nome, dados in CT317_HARDCODE_HH_BASE.items():
                                if atv_nome == a:
                                    hm = dados.get("rendimento_hm", 0)
                                    if hm > 0:
                                        hm_val = f" {C}(HM={hm:.2f}){RS}"
                                    break
                            print(f" {Y}{i:2}{RS}. {a}{hm_val}")
                        sub()
                        print(G + f"Total filtrado: {len(atividades_mec)} atividade(s)" + RS)
                    else:
                        print(Y + " (nenhuma atividade mecanizada encontrada)" + RS)

                    # Mostrar também as já vinculadas
                    cur_mec = [a for a in cur if a in atividades_mec]
                    if cur_mec:
                        sub()
                        print(G + " Já vinculadas a este recurso:" + RS)
                        for a in cur_mec:
                            print(f" {C}✓{RS} {a}")

                    esperar()
                    continue

                if acao == "Ver listas completas (vinculadas x catalogo)":
                    _mostrar_catalogo_atividades(cur, pool_catalogo)
                    esperar()

                return recursos


def _cadastrar_recursos_mecanizados_sn(atividades_reais, cfg=None, atividades_catalogo=None):
    """Cadastrar N recursos mecanizados com seleção de atividades via S/N e edição retroativa."""
    pool_catalogo = _catalogo_atividades_completo(
        atividades_reais,
        cfg=cfg,
        atividades_catalogo=atividades_catalogo,
    )
    cand_mec = atividades_candidatas_mecanizado(atividades_reais, cfg)
    pool = list(atividades_reais)
    if cand_mec:
        sub()
        print(G + BL + "  LISTA DE ATIVIDADES (modo mecanizado)" + RS)
        print(
            DM
            + f"  Encontradas {len(cand_mec)} candidata(s) (nome: trator, mec., solo mec, etc.; ou tipo HM na tarifa)."
            + RS
        )
        if confirmar(
            "  Mostrar apenas candidatas a mecanizado na pergunta S/N abaixo?",
            default=True,
        ):
            pool = cand_mec
        else:
            pool = list(pool_catalogo)
    elif cfg:
        aviso("Nenhuma candidata automatica; listando todas as atividades da fazenda.")
        pool = list(pool_catalogo)
    recursos = []
    while True:
        sub()
        print(G + BL + f"  MODO MECANIZADO — recurso #{len(recursos) + 1}" + RS)
        nome = prompt(
            "Nome do recurso (ex: Robo Rocador, Trator X)",
            f"Mecanizado_{len(recursos) + 1}",
        )
        prod = pedir_float("Produtividade (ha/h)", 0.18)
        custo = pedir_float("Custo (R$/h, 0 se placeholder)", 0.0, allow_zero=True)
        print(G + BL + f"\n  Selecionar atividades para '{nome}' (S/N):" + RS)
        print(DM + "  s=sim  n=nao  a=nao e encerrar  ok=sim e encerrar" + RS)
        atvs = []
        cur_all = sorted(pool, key=str)
        for i, a in enumerate(cur_all, 1):
            v = prompt(f"[{i}/{len(cur_all)}] Vincular '{str(a)[:54]}'? (s/n/a/ok)", "")
            v = str(v).strip().lower()
            if v in ("s", "sim", "y", "yes"):
                if a not in atvs:
                    atvs.append(a)
            elif v == "a":
                ok("Selecao encerrada (sem vincular esta).")
                break
            elif v == "ok":
                if a not in atvs:
                    atvs.append(a)
                ok("Selecao encerrada por comando rapido.")
                break
        if not atvs:
            aviso("Nenhuma atividade selecionada para este recurso.")
        else:
            recursos.append(
                {"nome": nome, "prod_ha_h": prod, "custo_h": custo, "atividades": atvs}
            )
            ok(f"Recurso '{nome}': {len(atvs)} atividades, {prod} ha/h, R$ {custo}/h")
        if not confirmar("Adicionar mais um recurso mecanizado?", default=False):
            break

    if recursos and confirmar(
        "Revisar/editar atividades dos recursos mecanizados agora?",
        default=True,
    ):
        recursos = _menu_editar_recurso_mecanizado(recursos, pool_catalogo)

    return recursos







def _catalogo_atividades_completo(atividades_escopo, cfg=None, atividades_catalogo=None):
    """Unifica atividades do escopo atual, catálogo do micro e catálogo da CT/de_para."""
    out = set()

    for a in atividades_escopo or []:
        s = str(a).strip()
        if s:
            out.add(s)

    for a in atividades_catalogo or []:
        s = str(a).strip()
        if s:
            out.add(s)

    if isinstance(cfg, dict):
        tarifas = cfg.get("tarifas", {}) or {}
        for a in tarifas.keys():
            s = str(a).strip()
            if s:
                out.add(s)

        de_para = cfg.get("de_para", {}) or {}
        for k, v in de_para.items():
            if str(k).startswith("_"):
                continue
            ks = _norm_atv(k)
            vs = str(v).strip()
            if ks:
                out.add(ks)
            if vs:
                out.add(vs)

    return sorted(out, key=lambda x: str(x))


def _mostrar_catalogo_atividades(atividades_escopo, atividades_catalogo):
    """Mostra duas tabelas: escopo atual e catálogo completo disponível."""
    escopo = sorted({str(a).strip() for a in atividades_escopo or [] if str(a).strip()}, key=str)
    catalogo = sorted({str(a).strip() for a in atividades_catalogo or [] if str(a).strip()}, key=str)

    print(G + BL + "\n  LISTA 1 — ATIVIDADES NO ESCOPO ATUAL" + RS)
    if escopo:
        for i, a in enumerate(escopo, 1):
            print(G + f"  [{i:2}] " + C + f"{a}" + RS)
    else:
        print(Y + "  (vazio)" + RS)

    print(G + BL + "\n  LISTA 2 — CATALOGO COMPLETO (MICRO + CT + de_para)" + RS)
    if catalogo:
        for i, a in enumerate(catalogo, 1):
            print(G + f"  [{i:2}] " + C + f"{a}" + RS)
    else:
        print(Y + "  (vazio)" + RS)


def menu_vincular_atividades_turma(turma, atividades_reais, atividades_catalogo=None):
    """
    Vincula atividades a uma turma.
    Padrao: percurso S/N atividade-por-atividade.
    Fallback: filtro/lista/paginacao acessiveis via menu auxiliar.
    """
    atv_set = set(turma["atividades"])

    def _catalogo_all():
        return _catalogo_atividades_completo(
            list(atividades_reais) + list(atv_set),
            cfg=None,
            atividades_catalogo=atividades_catalogo,
        )

    def _percurso_sn():
        cur_all = sorted(atividades_reais, key=lambda x: str(x))
        print(
            G
            + BL
            + f"\n  TURMA '{turma['nome']}' — percurso S/N ({len(cur_all)} atividades)"
            + RS
        )
        print(
            DM
            + "  s=vincular  n=desvincular  a=nao e encerrar  ok=sim e encerrar  ENTER=manter atual"
            + RS
            + "\n"
        )
        for i, a in enumerate(cur_all, 1):
            mk = "X" if a in atv_set else " "
            v = prompt(f"[{i}/{len(cur_all)}] [{mk}] '{str(a)[:54]}' (s/n/a/ok)", "")
            v = str(v).strip().lower()
            if v in ("s", "sim", "y", "yes"):
                atv_set.add(a)
                _emitir_monitor_rendimentos(str(a), True)
            elif v in ("n", "nao", "não", "no"):
                atv_set.discard(a)
                _emitir_monitor_rendimentos(str(a), False)
            elif v == "a":
                ok("Percurso encerrado (sem alterar esta atividade).")
                _emitir_monitor_rendimentos("", False)  # Indicates user aborted
                break
            elif v == "ok":
                atv_set.add(a)
                ok("Percurso encerrado por comando rapido.")
                break
        ok(f"Percurso concluido. Vinculadas: {len(atv_set)}")

    def _assistente_sn_vinculos():
        """
        Revisao guiada S/N das atividades da turma:
        - ENTER: manter
        - n: remover
        - t: trocar por outra atividade
        - a: adicionar nova atividade agora
        - ok: encerrar assistente
        """
        while True:
            cur_all = sorted(atividades_reais, key=lambda x: str(x))
            cat_all = _catalogo_all()
            cur_v = sorted(atv_set, key=lambda x: str(x))
            print(G + BL + f"\n  ASSISTENTE S/N — TURMA '{turma['nome']}'" + RS)
            print(
                DM
                + "  ENTER=manter  n=remover  t=trocar  a=adicionar  ok=encerrar"
                + RS
                + "\n"
            )
            for i, a in enumerate(cur_all, 1):
                if a not in atv_set:
                    continue
                v = (
                    prompt(f"[{i}/{len(cur_all)}] '{str(a)[:54]}' (ENTER/n/t/a/ok)", "")
                    .strip()
                    .lower()
                )
                if not v:
                    continue
                if v in ("ok",):
                    ok("Assistente encerrado.")
                    return
                if v in ("n", "nao", "não", "no"):
                    atv_set.discard(a)
                    continue
                if v in ("a",):
                    disp_add = [x for x in cat_all if x not in atv_set]
                    if not disp_add:
                        aviso("Nao ha atividade disponivel para adicionar.")
                        continue
                    idx_add = selecionar_paginado("ADICIONAR ATIVIDADE", disp_add)
                    if idx_add >= 0:
                        atv_set.add(disp_add[idx_add])
                        ok("Adicionada.")
                    continue
                if v in ("t", "trocar"):
                    disp = [x for x in cat_all if x != a]
                    idxd = selecionar_paginado("DESTINO DA TROCA", disp)
                    if idxd >= 0:
                        dest = disp[idxd]
                        atv_set.discard(a)
                        atv_set.add(dest)
                        ok(f"Troca: '{str(a)[:40]}' -> '{str(dest)[:40]}'.")
                    continue
            if not confirmar("Repassar assistente S/N novamente?", default=False):
                return

    _percurso_sn()

    while True:
        cur = sorted(atv_set, key=lambda x: str(x))
        sub()
        print(
            G
            + BL
            + f"  TURMA: {turma['nome']} ({turma['operarios']} ops) — {len(cur)} atividade(s) vinculadas"
            + RS
        )
        print(DM + "  [1] Refazer percurso S/N" + RS)
        print(DM + "  [2] Adicionar por filtro de texto" + RS)
        print(DM + "  [3] Adicionar por lista/indices (fallback)" + RS)
        print(DM + "  [4] Remover por filtro" + RS)
        print(DM + "  [5] Remover UMA (lista)" + RS)
        print(DM + "  [6] Ver vinculadas" + RS)
        print(DM + "  [7] Trocar atividade (substituir 1:1)" + RS)
        print(DM + "  [8] Assistente inteligente S/N (revisao guiada)" + RS)
        print(DM + "  [9] Ver duas listas (escopo x catalogo completo)" + RS)
        print(DM + "  [0] Concluir esta turma" + RS)
        sub()
        op = prompt("Opcao", "0").strip()
        if op == "0":
            turma["atividades"] = sorted(atv_set, key=lambda x: str(x))
            return
        if op == "1":
            _percurso_sn()
        elif op == "2":
            filtro = prompt("Texto no nome (ex: roçada)", "")
            if not str(filtro).strip():
                aviso("Filtro vazio.")
                continue
            matches = filtrar_atividades_por_texto(atividades_reais, filtro)
            if not matches:
                aviso("Nenhuma atividade bateu com o filtro.")
                continue
            print(G + f"\n  {len(matches)} encontrada(s):" + RS)
            for m in matches[:12]:
                print(DM + f"    - {str(m)[:62]}" + RS)
            if len(matches) > 12:
                print(DM + f"    ... +{len(matches) - 12}" + RS)
            if confirmar("Adicionar TODAS ao vinculo desta turma?", default=True):
                for m in matches:
                    atv_set.add(m)
                ok(f"+{len(matches)} atividades.")
            else:
                for i, m in enumerate(matches, 1):
                    if confirmar(f"  [{i}] {str(m)[:55]}", default=False):
                        atv_set.add(m)
        elif op == "3":
            disp = [a for a in _catalogo_all() if a not in atv_set]
            if not disp:
                aviso("Ja estao todas vinculadas ou lista vazia.")
                continue
            print(
                DM
                + f"\n  Indices de 1 a {len(disp)} (ex.: 1,3,5-8). ENTER = lista paginada"
                + RS
            )
            multi = prompt("Indices", "")
            if str(multi).strip():
                idxs = parse_intervalos_escolha(multi, len(disp))
                if not idxs:
                    aviso("Nenhum indice valido.")
                else:
                    for i in idxs:
                        atv_set.add(disp[i])
                    ok(f"+{len(idxs)} atividades.")
                continue
            idx = selecionar_paginado("ADICIONAR ATIVIDADE", disp)
            if idx >= 0:
                atv_set.add(disp[idx])
                ok("Adicionada.")
        elif op == "4":
            filtro = prompt("Remover cujo nome contem", "")
            if not str(filtro).strip():
                aviso("Filtro vazio.")
                continue
            rem = filtrar_atividades_por_texto(list(atv_set), filtro)
            if not rem:
                aviso("Nenhuma vinculada bateu com o filtro.")
                continue
            if confirmar(
                f"Remover {len(rem)} da turma '{turma['nome']}'?", default=True
            ):
                for r in rem:
                    atv_set.discard(r)
                ok("Removidas.")
        elif op == "5":
            cur2 = sorted(atv_set, key=lambda x: str(x))
            if not cur2:
                aviso("Nada vinculado ainda.")
                continue
            idx = selecionar_paginado("REMOVER ATIVIDADE", cur2)
            if idx >= 0:
                atv_set.discard(cur2[idx])
                ok("Removida.")
        elif op == "6":
            cur2 = sorted(atv_set, key=lambda x: str(x))
            print(G + f"\n  Vinculadas ({len(cur2)}): " + RS)
            for x in cur2[:40]:
                print(DM + f"    - {str(x)[:62]}" + RS)
            if len(cur2) > 40:
                print(DM + f"    ... +{len(cur2) - 40}" + RS)
            esperar()
        elif op == "7":
            cur2 = sorted(atv_set, key=lambda x: str(x))
            if not cur2:
                aviso("Nada vinculado para trocar.")
                continue
            old = selecionar_paginado("ATIVIDADE ORIGEM (será removida)", cur2)
            if old < 0:
                continue
            origem = cur2[old]
            disp = sorted([a for a in _catalogo_all() if a != origem], key=lambda x: str(x))
            if not disp:
                aviso("Nao ha atividade destino disponivel.")
                continue
            print(
                DM + "  Dica: ENTER para lista paginada ou use filtro por texto." + RS
            )
            filtro = prompt("Filtro do destino (opcional)", "")
            if str(filtro).strip():
                candidatos = filtrar_atividades_por_texto(disp, filtro)
                if not candidatos:
                    aviso("Nenhum destino bateu com o filtro.")
                    continue
                destino = selecionar("ATIVIDADE DESTINO", candidatos)
            else:
                idxd = selecionar_paginado("ATIVIDADE DESTINO", disp)
                destino = disp[idxd] if idxd >= 0 else None
            if not destino:
                continue
            if confirmar(
                f"Trocar '{str(origem)[:48]}' por '{str(destino)[:48]}'?", default=True
            ):
                atv_set.discard(origem)
                atv_set.add(destino)
                ok("Troca aplicada.")
        elif op == "8":
            _assistente_sn_vinculos()
        elif op == "9":
            _mostrar_catalogo_atividades(sorted(atv_set, key=str), _catalogo_all())
            esperar()
        else:
            aviso("Opcao invalida.")


def resolver_conflitos_e_reatribuir(turmas, atividades_reais):
    """
    Atividades com mais de uma turma: paralelo ou exclusivo.
    Reatribuicao: qualquer atividade -> turma executora (reforco / outra funcao).
    Retorna reatribuicao, paralelo, primaria.
    """
    reatribuicao = {}
    paralelo = {}
    primaria = {}
    conflitos_encontrados = False

    def candidatos(atv):
        return [t["nome"] for t in turmas if atv in t["atividades"]]

    for atv in atividades_reais:
        c = candidatos(atv)
        if len(c) <= 1:
            continue
        conflitos_encontrados = True
        sub()
        print(Y + f" Conflito: '{str(atv)[:58]}'" + RS)
        print(DM + f"  Turmas: {', '.join(c)}" + RS)
        if confirmar(
            "  Varias turmas em PARALELO (dividem a mesma demanda no tempo)?",
            default=True,
        ):
            paralelo[atv] = True
        else:
            paralelo[atv] = False
            p = selecionar("  Turma EXCLUSIVA para esta atividade", c)
            if p:
                primaria[atv] = p

    if confirmar(
        "\n  Reatribuir atividades (reforco: outra turma executa, ex. adubacao faz uma roçada)?",
        default=False,
    ):
        nomes_turmas = [t["nome"] for t in turmas]
        while True:
            idx = selecionar_paginado(
                "REATRIBUIR — escolha a ATIVIDADE", atividades_reais, page_size=6
            )
            if idx < 0:
                break
            atv = atividades_reais[idx]
            print(G + f"\n  Atividade: {str(atv)[:62]}" + RS)
            t_alvo = selecionar(
                "  Turma que EXECUTA (capacidade desta turma)", nomes_turmas
            )
            if t_alvo:
                reatribuicao[atv] = t_alvo
            ok(
                f"Executora: '{t_alvo}' (sobrescreve vinculos anteriores para o cronograma)."
            )

    if not conflitos_encontrados:
        ok("Nenhuma atividade com conflito multi-turma.")

    return reatribuicao, paralelo, primaria


def turmas_que_executam(atv, turmas, reatribuicao, paralelo, primaria):
    """Lista de nomes de turma que trabalham nesta atividade no simulador."""
    if atv in reatribuicao:
        return [reatribuicao[atv]]
    c = [t["nome"] for t in turmas if atv in t["atividades"]]
    if not c:
        return []
    if len(c) == 1:
        return c
    if paralelo.get(atv, True):
        return c
    p = primaria.get(atv)
    return [p] if p else c



_FILTROS_NOME_CANDIDATAS_MECANIZADO = [
    "mecaniz",
    "maquina",
    "máquina",
    "trator",
    "motocovead",
    "motocultor",
    "robo",
    "robô",
    "pulveriz",
    "atomiz",
    "implemento",
    "coveador",
    "solo mec",
    "mec c/",
    "mec s/",
    "esteira",
    "drone",
    "máq",
    "maq.",
]


def atividades_candidatas_mecanizado(atividades_reais, cfg=None):
    """Atividades provavelmente mecanizadas: palavras-chave no nome e/ou tipo HM na tarifa CT."""
    cfg = cfg or {}
    tarifas = cfg.get("tarifas", {}) or {}
    merged = set(
        atividades_por_filtro(atividades_reais, _FILTROS_NOME_CANDIDATAS_MECANIZADO)
    )
    for atv in atividades_reais:
        t_nome = resolver_chave_tarifa(cfg, tarifas, atv)
        row = tarifas.get(t_nome)
        if not isinstance(row, dict):
            continue
        tipo = str(row.get("tipo", "")).lower()
        try:
            hm = float(row.get("rendimento_hm", 0) or 0)
        except (TypeError, ValueError):
            hm = 0.0
        if "mecaniz" in tipo or hm > 0:
            merged.add(atv)
    return sorted(merged, key=str)
