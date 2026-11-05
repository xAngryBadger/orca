"""File I/O — data loading, file selection, column mapping, demo reconstruction."""

import os

import pandas as pd

from .config import (
    CT_REAL_FILENAME,
    INPUT_DIR,
    KNOWN_COLUMNS,
    STG_FILENAME,
    salvar_config,
)
from .errors import OrcaValidationError
from .territorio import _indice_fazendas_ct, fazendas_unicas_micro
from .text_utils import normalizar_chave, remover_acentos
from .ui import (
    BL,
    DM,
    RS,
    C,
    G,
    R,
    aviso,
    confirmar,
    erro,
    ok,
    selecionar,
    selecionar_paginado,
    sub,
    subcabecalho,
)


def encontrar_coluna(cols, campo, modo_auto=False, arquivo=None, aba=None):
    """Try KNOWN_COLUMNS exact matches first, then fuzzy fallback.

    In modo_auto (batch), raises OrcaValidationError if required column not found.
    In interactive mode, returns None and caller handles manual selection.
    """
    known = KNOWN_COLUMNS.get(campo, [])
    for k in known:
        if k in cols:
            return k
    # Fuzzy fallback
    cn_map = {remover_acentos(c): c for c in cols}
    for k in known:
        kn = remover_acentos(k)
        for cn, original in cn_map.items():
            if kn in cn or cn in kn:
                return original
    # Not found
    if modo_auto:
        available = ", ".join(cols) if cols else "(nenhuma)"
        msg = (
            f"Coluna obrigatória '{campo}' não encontrada"
        )
        if arquivo:
            msg += f" no arquivo '{os.path.basename(arquivo)}'"
        if aba:
            msg += f", aba '{aba}'"
        msg += f". Colunas disponíveis: {available}"
        raise OrcaValidationError(
            msg,
            column=campo,
            file=arquivo,
            sheet=aba,
            available_columns=list(cols),
        )
    return None


def buscar_arquivos_excel():
    if not os.path.isdir(INPUT_DIR):
        os.makedirs(INPUT_DIR, exist_ok=True)
        return []
    return [
        f
        for f in os.listdir(INPUT_DIR)
        if not f.startswith("~")
        and any(f.endswith(e) for e in [".xlsx", ".xls", ".csv", ".xlsm"])
    ]


def _find_default_micro_path(cfg=None):
    """
    Prioridade: config.arquivo_micro (se existir no disco) > lista fixa > primeiro .xlsx com
    'inovesa'/'consolidado'/'exame'/'micro' no nome.
    """
    if cfg:
        pref = cfg.get("arquivo_micro")
        if pref and isinstance(pref, str):
            p = os.path.join(INPUT_DIR, pref.strip())
            if os.path.exists(p):
                return p
        candidatos = [
            "MICROPLANEJAMENTO_CONSOLIDADO_INOVESA 1.xlsx",
            "exame.xlsx",
            "EXAME.xlsx",
            "Exame.xlsx",
            "microplanejamento.xlsx",
            "MICROPLANEJAMENTO.xlsx",
        ]
        for c in candidatos:
            p = os.path.join(INPUT_DIR, c)
            if os.path.exists(p):
                return p
    for f in buscar_arquivos_excel():
        n = remover_acentos(f)
        if "micro" in n:
            return os.path.join(INPUT_DIR, f)
    for f in buscar_arquivos_excel():
        n = remover_acentos(f)
        if "inovesa" in n or "consolidado" in n:
            return os.path.join(INPUT_DIR, f)
    for f in buscar_arquivos_excel():
        n = remover_acentos(f)
        if "exame" in n:
            return os.path.join(INPUT_DIR, f)
    return None


def _prefer_micro_sheet(abas):
    skip_prefixes = ("planilha", "previs")
    for a in abas:
        if "microplanejamento_abril_junho" in remover_acentos(a).replace(" ", ""):
            return a
    for a in abas:
        na = remover_acentos(a).lower()
        if any(na.startswith(p) for p in skip_prefixes):
            continue
        if "micropl" in na and "_v5" in na:
            return a
    for a in abas:
        na = remover_acentos(a).lower()
        if any(na.startswith(p) for p in skip_prefixes):
            continue
        if "micropl" in na and "impl" in na and ("_v3" in na or "_v4" in na):
            continue
        if "microplanejamento" in na:
            return a
    for a in abas:
        if "inovesa" in remover_acentos(a) or "consolidado" in remover_acentos(a):
            return a
    for a in abas:
        na = remover_acentos(a).lower()
        if any(na.startswith(p) for p in skip_prefixes):
            continue
        if "micropl" in na:
            return a
    return abas[0] if abas else None


def _find_default_ct_path():
    import re
    preferido = os.path.join(INPUT_DIR, CT_REAL_FILENAME)
    if os.path.exists(preferido):
        return preferido

    for f in buscar_arquivos_excel():
        if f == STG_FILENAME:
            continue
        n = remover_acentos(f)
        if "ct317" in n or ("ct" in n and "317" in n):
            return os.path.join(INPUT_DIR, f)

    for f in buscar_arquivos_excel():
        if f == STG_FILENAME:
            continue
        n = remover_acentos(f)
        if "ct_313" in n or ("ct" in n and "313" in n):
            return os.path.join(INPUT_DIR, f)

    _ct_re = re.compile(r'ct[\s_]*\d{2,4}', re.IGNORECASE)
    for f in buscar_arquivos_excel():
        if f == STG_FILENAME:
            continue
        if _ct_re.search(remover_acentos(f)):
            return os.path.join(INPUT_DIR, f)
    return None


def selecionar_arquivo(titulo="Selecione um Arquivo"):
    """
    Seletor com navegacao de pastas.
    - [DIR] .. : sobe um nivel
    - [DIR] nome: entra na pasta
    - [ARQ] nome: seleciona arquivo
    """
    exts = (".xlsx", ".xls", ".xlsm", ".csv")
    cwd = INPUT_DIR
    while True:
        try:
            nomes = sorted(os.listdir(cwd), key=lambda s: normalizar_chave(str(s)))
        except Exception as ex:
            erro(f"Nao foi possivel abrir pasta: {ex}")
            return None

        entries = []
        parent = os.path.dirname(cwd.rstrip("\\/"))
        if parent and parent != cwd:
            entries.append(("dir_up", "..", parent))

        for n in nomes:
            p = os.path.join(cwd, n)
            if os.path.isdir(p):
                if n.startswith("."):
                    continue
                entries.append(("dir", n, p))
        for n in nomes:
            p = os.path.join(cwd, n)
            if os.path.isfile(p):
                ln = n.lower()
                if n.startswith("~") or n.startswith("~$"):
                    continue
                if ln.endswith(exts):
                    entries.append(("file", n, p))

        if not entries:
            aviso(f"Nada encontrado em: {cwd}")
            if cwd == INPUT_DIR:
                return None
            cwd = parent if parent else INPUT_DIR
            continue

        labels = []
        for kind, name, _ in entries:
            if kind == "dir_up":
                labels.append("[DIR] ..")
            elif kind == "dir":
                labels.append(f"[DIR] {name}")
            else:
                labels.append(f"[ARQ] {name}")

        subcabecalho(titulo)
        print(DM + f"  Pasta atual: {cwd}" + RS)
        sub()
        idx = selecionar_paginado(titulo, labels, page_size=12, zero_label="Cancelar")
        if idx < 0:
            return None
        kind, name, path = entries[idx]
        if kind in ("dir_up", "dir"):
            cwd = path
            continue
        return path


def carregar_planilha_microplanejamento(cfg, caminho=None, modo_auto=False):
    if not caminho:
        caminho = selecionar_arquivo("MICROPLANEJAMENTO (ex. exame.xlsx)")
    if not caminho:
        return None
    try:
        xls = pd.ExcelFile(caminho)
        abas = xls.sheet_names
        if len(abas) == 1:
            aba = abas[0]
        else:
            if modo_auto:
                aba = _prefer_micro_sheet(abas)
            else:
                aba = selecionar("SELECIONE A ABA", abas)
                if aba is None:
                    return None

        df = ExcelReader.read(caminho, sheet_name=aba, header=0)
        cols = df.columns.tolist()

        # Mapear com KNOWN_COLUMNS primeiro
        faz_col = encontrar_coluna(cols, "fazenda", modo_auto, caminho, aba)
        chv_col = encontrar_coluna(cols, "chave", modo_auto, caminho, aba)
        area_col = encontrar_coluna(cols, "area", modo_auto, caminho, aba)
        atv_col = encontrar_coluna(cols, "atividade", modo_auto, caminho, aba)
        mun_col = encontrar_coluna(cols, "municipio", modo_auto, caminho, aba)
        est_col = encontrar_coluna(cols, "estado", modo_auto, caminho, aba)

        # BETA: planilhas de testes podem nao ter CHAVE POLIGONO; usar NUCLEO como fallback automatico.
        if modo_auto and not chv_col:
            for c in cols:
                if "nucleo" in normalizar_chave(c):
                    chv_col = c
                    break

        # Se algum nao bateu, pedir manual
        mapeados = {
            "Fazenda": faz_col,
            "Talhao": chv_col,
            "Area(ha)": area_col,
            "Atividade": atv_col,
        }
        todos_ok = all(v is not None for v in mapeados.values())

        sub()
        print(G + BL + "  MAPEAMENTO AUTOMATICO:" + RS)
        for label, val in mapeados.items():
            cor = G if val else R
            print(cor + f"  {label:12}: " + C + f"{val or '??? NAO ENCONTRADO'}" + RS)
        sub()

        if todos_ok and (modo_auto or confirmar("Usar este mapeamento?", default=True)):
            pass  # tudo certo
        else:
            if modo_auto:
                erro("Nao foi possivel mapear colunas do micro automaticamente.")
                return None
            print(G + "\n  Selecione manualmente cada coluna:\n" + RS)
            if not faz_col:
                idx = selecionar_paginado("COLUNA DA FAZENDA", cols)
                faz_col = cols[idx] if idx >= 0 else cols[0]
            if not chv_col:
                idx = selecionar_paginado("COLUNA DO TALHAO/CHAVE", cols)
                chv_col = cols[idx] if idx >= 0 else cols[1]
            if not area_col:
                idx = selecionar_paginado("COLUNA DA AREA (HECTARES)", cols)
                area_col = cols[idx] if idx >= 0 else cols[2]
            if not atv_col:
                idx = selecionar_paginado("COLUNA DA ATIVIDADE", cols)
                atv_col = cols[idx] if idx >= 0 else cols[3]

        sel_cols = [faz_col, chv_col, area_col, atv_col]
        sel_names = ["fazenda", "chave", "area_ha", "atividade"]

        equipe_col = None
        for c in cols:
            if normalizar_chave(c) in ("equipe", "nome equipe", "empresa"):
                equipe_col = c
                break
        if equipe_col:
            sel_cols.append(equipe_col)
            sel_names.append("equipe")
            print(G + " Coluna EQUIPE detectada: " + C + f"{equipe_col}" + RS)

        if mun_col:
            sel_cols.append(mun_col)
            sel_names.append("municipio")
            print(G + " Coluna MUNICIPIO detectada: " + C + f"{mun_col}" + RS)
        if est_col:
            sel_cols.append(est_col)
            sel_names.append("estado")
            print(G + " Coluna ESTADO detectada: " + C + f"{est_col}" + RS)

        metodologia_col = None
        pref_metodologia = str(cfg.get("coluna_metodologia_micro", "") or "").strip()
        if pref_metodologia and pref_metodologia in cols:
            metodologia_col = pref_metodologia
        metodologia_labels = {
            "metodologia",
            "tipo metodologia",
            "tipo de metodologia",
            "metodologia talhao",
            "metodologia atividade",
            "metodo",
        }
        if not metodologia_col:
            for c in cols:
                nc = normalizar_chave(c)
                if not nc:
                    continue
                if nc in metodologia_labels or "metodolog" in nc:
                    metodologia_col = c
                    break

        if not metodologia_col:
            # Fallback heuristico: coluna textual com poucos valores e termos de metodologia.
            chaves_metodo = (
                "implant",
                "conduc",
                "manut",
                "adapt",
                "adap",
                "restaur",
                "passiv",
            )
            for c in cols:
                if c in sel_cols:
                    continue
                serie = df[c].dropna()
                if serie.empty:
                    continue
                amostra = serie.astype(str).str.strip()
                amostra = amostra[~amostra.str.lower().isin(["nan", "none", ""])]
                if amostra.empty:
                    continue
                unicos = sorted(
                    {
                        normalizar_chave(v)
                        for v in amostra.tolist()
                        if normalizar_chave(v)
                    }
                )
                if not unicos or len(unicos) > 30:
                    continue
                hits = sum(
                    1 for v in unicos if any(k in v for k in chaves_metodo)
                )
                if hits >= max(1, len(unicos) // 5):
                    metodologia_col = c
                    break

        if not metodologia_col and not modo_auto:
            if confirmar(
                "Nao detectei a coluna de METODOLOGIA automaticamente. Selecionar manualmente?",
                default=False,
            ):
                cols_disp = [c for c in cols if c not in sel_cols]
                if cols_disp:
                    idx = selecionar_paginado("COLUNA DA METODOLOGIA", cols_disp)
                    if idx >= 0:
                        metodologia_col = cols_disp[idx]

        if metodologia_col:
            sel_cols.append(metodologia_col)
            sel_names.append("metodologia")
            cfg["coluna_metodologia_micro"] = metodologia_col
            salvar_config(cfg)
            print(
                G + "  Coluna METODOLOGIA detectada: " + C + f"{metodologia_col}" + RS
            )

        df_filtro = df[sel_cols].copy()
        df_filtro.columns = sel_names
        for c_txt in ("fazenda", "chave", "atividade", "equipe", "metodologia", "municipio", "estado"):
            if c_txt in df_filtro.columns:
                df_filtro[c_txt] = (
                    df_filtro[c_txt]
                    .astype(str)
                    .str.replace(r"\s+", " ", regex=True)
                    .str.strip()
                )
                df_filtro.loc[
                    df_filtro[c_txt].str.lower().isin(["nan", "none", ""]), c_txt
                ] = None
        df_filtro = df_filtro.dropna(subset=["atividade", "area_ha"])
        df_filtro["area_ha"] = df_filtro["area_ha"].apply(
            lambda x: _to_float_br(x, default=0.0)
        )

        validos = df_filtro[df_filtro["area_ha"] > 0]

        equipe_vazia = (
            "equipe" not in validos.columns
            or validos["equipe"].dropna().str.strip().replace("", None).dropna().empty
        )
        if equipe_vazia:
            try:
                xls_eq = pd.ExcelFile(caminho)
                eq_sheet = None
                for s in xls_eq.sheet_names:
                    if normalizar_chave(s).startswith("planilha7") or (
                        "logistic" in normalizar_chave(s)
                    ):
                        eq_sheet = s
                        break
                if not eq_sheet:
                    for s in xls_eq.sheet_names:
                        sh = ExcelReader.read(xls_eq, sheet_name=s, nrows=2)
                        cols_s = [normalizar_chave(c) for c in sh.columns]
                        if any("equipe" in c for c in cols_s):
                            has_faz = any("fazenda" in c for c in cols_s)
                            if has_faz and len(sh.columns) <= 20:
                                eq_sheet = s
                                break
                if eq_sheet:
                    df_eq = ExcelReader.read(xls_eq, sheet_name=eq_sheet)
                    eq_col = None
                    fz_col = None
                    for c in df_eq.columns:
                        if "equipe" in normalizar_chave(c) and not eq_col:
                            eq_col = c
                        if "fazenda" in normalizar_chave(c) and not fz_col:
                            fz_col = c
                    if eq_col and fz_col:
                        map_eq = dict(
                            zip(
                                df_eq[fz_col].astype(str).str.strip(),
                                df_eq[eq_col].astype(str).str.strip(),
                            )
                        )
                        map_eq = {k: v for k, v in map_eq.items() if v and v.lower() not in ("nan", "none", "")}
                        if map_eq:
                            def _match_equipe(faz_name, mapping):
                                fn = str(faz_name).strip()
                                if fn in mapping:
                                    return mapping[fn]
                                fn_n = remover_acentos(fn).lower()
                                for k, v in mapping.items():
                                    if remover_acentos(k).lower() == fn_n:
                                        return v
                                for k, v in mapping.items():
                                    if remover_acentos(k).lower() in fn_n or fn_n in remover_acentos(k).lower():
                                        return v
                                return None

                            if "equipe" not in validos.columns:
                                validos = validos.copy()
                                validos["equipe"] = validos["fazenda"].apply(
                                    lambda f: _match_equipe(f, map_eq)
                                )
                            else:
                                mask_empty = validos["equipe"].isna() | (validos["equipe"].str.strip() == "")
                        validos.loc[mask_empty, "equipe"] = validos.loc[mask_empty, "fazenda"].apply(
                            lambda f: _match_equipe(f, map_eq)
                        )
                n_assigned = validos["equipe"].notna().sum()
                if n_assigned > 0:
                    ok(f"EQUIPE enriquecida a partir de '{eq_sheet}': {n_assigned} registros atribuidos")
            except (OSError, ValueError, KeyError):
                pass

        ok(f"Carregadas {len(validos)} atividades validas.")
        return validos
    except Exception as e:
        erro(f"Erro ao ler microplanejamento: {e}")
        return None


def _to_float_br(v, default=0.0):
    """Converte numero em formato BR/EN para float de forma tolerante."""
    try:
        if v is None:
            return float(default)
        if isinstance(v, (int, float)) and not pd.isna(v):
            return float(v)
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return float(default)
        s = s.replace(" ", "")
        if "," in s and "." in s:
            # Assume separador de milhar + decimal (pt-BR): 1.234,56
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except Exception:
        return float(default)


def garantir_fazendas_micro_no_ct(cfg, df):
    """
    Acrescenta em fazendas_ct todas as fazendas presentes no micro
    que ainda nao estao cadastradas, para o aviso micro-vs-CT nao bloquear.
    Retorna quantos nomes novos foram adicionados.
    """
    idx = _indice_fazendas_ct(cfg)
    ad = 0
    for f in fazendas_unicas_micro(df):
        nk = normalizar_chave(f)
        if not nk:
            continue
        if nk not in idx:
            cfg.setdefault("fazendas_ct", []).append(f)
            idx[nk] = f
            ad += 1
    return ad


class ExcelReader:
    """Thin adapter around pd.read_excel for testability."""
    @staticmethod
    def read(caminho, sheet_name=None, **kwargs):
        return pd.read_excel(caminho, sheet_name=sheet_name, **kwargs)
