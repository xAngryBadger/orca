"""Application entry point — main menu, startup, and session cleanup."""

import atexit
import os

from .app import (
    _aplicar_filtro_empresa_e_escopo,
    _aplicar_filtro_regiao,
    _executar_scheduler_fazenda_interativo,
)
from .commands import executar_comando
from .config import (
    DIR,
    INPUT_DIR,
    STG_FILENAME,
    _is_beta_mode,
    _is_legacy_mode,
    carregar_config,
    modo_somente_hh,
    salvar_config,
)
from .context import contexto_sessao, dashboard_header
from .de_para import aplicar_depara_padrao_exame
from .io import (
    _find_default_ct_path,
    _find_default_micro_path,
    carregar_planilha_microplanejamento,
    garantir_fazendas_micro_no_ct,
    selecionar_arquivo,
)
from .monitor import _abrir_monitor_janela, init_monitor
from .scheduler_core import (
    _executar_lote_fazendas,
    _executar_multi_equipes,
)
from .tarifas import (
    carregar_stg_tarifas,
    normalizar_ct313,
)
from .territorio import (
    aviso_fazendas_micro_sem_cadastro_ct,
)
from .ui import (
    BL,
    DM,
    RS,
    C,
    G,
    Y,
    aviso,
    cabecalho,
    esperar,
    ok,
    prompt,
    selecionar,
    sub,
    subcabecalho,
)


def _is_demo_micro_path(nome_arquivo_micro):
    """Verifica se e micro demo (caminho padrao)."""
    if not nome_arquivo_micro:
        return False
    nome = str(nome_arquivo_micro).lower()
    return "demo" in nome or "exemplo" in nome

def menu_principal(cfg, df, nome_arquivo_micro=""):
    opcoes = [
        ("1", "Smart Scheduler (Operacional HH/HM)"),
        ("2", "Importar Tarifas (CT real/manual)"),
        ("3", "Normalizar CT317/CT -> STG (auto)"),
        ("4", "Mapeamentos de_para (micro -> tarifa)"),
        ("5", "Trocar planilha de microplanejamento (.xlsx)"),
        ("6", "Fazendas micro vs CT (lista fazendas_ct)"),
        ("7", "Alternar modo custo (Somente HH / HH + R$)"),
        ("8", "Importar Precos Contrato (PRECO_FINAL + CD/CI)"),
        ("9", "Importar Custos Globais Brutos (CD/CI direto)"),
        ("M", "Abrir Monitor em Janela Separada"),
        ("0", "Sair"),
    ]
    while True:
        dashboard_header()
        subcabecalho()
        contexto_sessao.atualizar_configuracoes(cfg)
        nf = df["fazenda"].nunique()
        nu = df["chave"].nunique()
        na = df["atividade"].nunique()
        stg_existe = os.path.exists(os.path.join(INPUT_DIR, STG_FILENAME))
        nt = len(cfg.get("tarifas", {}))
        print(
            G
            + "  Base: "
            + C
            + f"{nf} fazendas  |  {nu} talhoes  |  {na} atividades"
            + RS
        )
        print(
            G
            + "  Tarifas: "
            + C
            + f"{nt} carregadas"
            + G
            + "  |  STG: "
            + C
            + f"{'Sim' if stg_existe else 'Nao'}"
            + RS
        )
        print(
            G
            + " Orcamento estrito: "
            + C
            + ("Sim" if cfg.get("orcamento_estrito", True) else "Nao")
            + RS
        )
        hh_mode = modo_somente_hh(cfg)
        print(
            G
            + " Modo custo: "
            + C
            + ("Somente HH" if hh_mode else "HH + R$")
            + RS
        )
        if "equipe" in df.columns:
            eq_list = sorted(df["equipe"].dropna().unique().tolist(), key=str)
            print(
                G
                + "  Empresas (EQUIPE): "
                + C
                + f"{len(eq_list)} ({', '.join(str(e)[:20] for e in eq_list[:5])}{'...' if len(eq_list) > 5 else ''})"
                + RS
            )
        if nome_arquivo_micro:
            print(
                G
                + "  Microplanejamento: "
                + C
                + os.path.basename(nome_arquivo_micro)
                + RS
            )
        if _is_demo_micro_path(nome_arquivo_micro):
            print(
                Y
                + "   DEMO: opcao [1] = maior fazenda do micro (municipio Ulianopolis), tarifas = CT 313."
                + RS
            )
        sub()
        for cod, desc in opcoes:
            print(G + f"  [{cod}] " + C + desc + RS)
        sub()
        v = prompt("Opcao").strip()
        if v == "1":
            contexto_sessao.atualizar_modo("single")
            df_scope, regiao_info = _aplicar_filtro_regiao(df)
            if df_scope is None or df_scope.empty:
                aviso("Nenhum dado apos filtro de regiao.")
                continue
            df_scope, empresa_filtro = _aplicar_filtro_empresa_e_escopo(df_scope)
            if df_scope is None or df_scope.empty:
                aviso("Nenhum dado apos filtros.")
                continue
                catalogo_scope = sorted(
                    {
                        str(x).strip()
                        for x in df_scope["atividade"].dropna().unique().tolist()
                        if str(x).strip()
                    },
                    key=str,
                )
                fazendas = sorted(df_scope["fazenda"].unique().tolist())
                if len(fazendas) == 1:
                    faz = fazendas[0]
                    ok(f"Fazenda unica no escopo: {faz}")
                    _executar_scheduler_fazenda_interativo(
                        cfg,
                        df_scope,
                        faz,
                        catalogo_scope,
                    )
                else:
                    op_faz = [
                        "TODAS AS FAZENDAS (equipe unica)",
                        "MULTI-EQUIPES (carteiras separadas)",
                    ] + fazendas
                    faz = selecionar("SELECIONE A FAZENDA OU MODO", op_faz)
                    if faz == "TODAS AS FAZENDAS (equipe unica)":
                        contexto_sessao.atualizar_modo("lote")
                        _executar_lote_fazendas(
                            cfg,
                            df_scope,
                            fazendas,
                            empresa_filtro=empresa_filtro,
                            nome_arquivo_micro=nome_arquivo_micro,
                        )
                    elif faz == "MULTI-EQUIPES (carteiras separadas)":
                        contexto_sessao.atualizar_modo("multi_equipes")
                        _executar_multi_equipes(
                            cfg,
                            df_scope,
                            fazendas,
                            empresa_filtro=empresa_filtro,
                            nome_arquivo_micro=nome_arquivo_micro,
                        )
                    elif faz:
                        _executar_scheduler_fazenda_interativo(
                            cfg,
                            df_scope,
                            faz,
                            catalogo_scope,
                        )
        elif v == "2":
            executar_comando("2", cfg)
        elif v == "3":
            executar_comando("3", cfg)
        elif v == "4":
            modulo_mapeamentos_de_para(cfg, df)
        elif v == "5":
            p = selecionar_arquivo("NOVO MICROPLANEJAMENTO (.xlsx)")
            if p:
                ndf = carregar_planilha_microplanejamento(
                    cfg, caminho=p, modo_auto=True
                )
                if ndf is None:
                    aviso(
                        "Nao foi possivel carregar automaticamente. Tente de novo sem modo_auto (o app pedira colunas)."
                    )
                    ndf = carregar_planilha_microplanejamento(
                        cfg, caminho=p, modo_auto=False
                    )
                if ndf is not None:
                    df = ndf
                    nome_arquivo_micro = p
                    cfg["arquivo_micro"] = os.path.basename(p)
                    salvar_config(cfg)
                    atividades_reais = sorted(
                        str(x).strip()
                        for x in df["atividade"].dropna().unique()
                        if str(x).strip()
                    )
                    novos = aplicar_depara_padrao_exame(cfg, atividades_reais)
            ok(
                f"Micro atualizado: {os.path.basename(p)} | {len(df)} registros | "
                f"{df['fazenda'].nunique()} fazendas | de_para +{novos} novos mapeamentos."
            )
            n_faz = garantir_fazendas_micro_no_ct(cfg, df)
            if n_faz:
                salvar_config(cfg)
                ok(f"+{n_faz} fazenda(s) em fazendas_ct (a partir do micro).")
            aviso_fazendas_micro_sem_cadastro_ct(cfg, df)
            ct_padrao = _find_default_ct_path()
            if ct_padrao:
                try:
                    stg_path, n, custo_h = normalizar_ct313(ct_padrao)
                    if stg_path and n > 0:
                        cfg["tarifas"] = carregar_stg_tarifas(stg_path)
                        cfg["custo_hora_tf"] = round(custo_h, 4)
                        salvar_config(cfg)
                        ok(
                            f"CT re-carregado: {os.path.basename(ct_padrao)} -> {n} atividades"
                        )
                except Exception as ex:
                    aviso(f"Falha ao re-carregar CT: {ex}")
            esperar()
        elif v == "6":
            executar_comando("6", cfg, df)
        elif v == "7":
            atual = modo_somente_hh(cfg)
            cfg["modo_somente_hh"] = not atual
            salvar_config(cfg)
            novo = "Somente HH" if not atual else "HH + R$"
            ok(f"Modo custo alterado para: {novo}")
            esperar("ENTER para voltar")
        elif v == "8":
            executar_comando("8", cfg)
        elif v == "9":
            executar_comando("9", cfg)
        elif v.upper() == "M":
            dashboard_header()
            subcabecalho("ABRIR MONITOR EXTERNO")
            print(G + BL + " Tipo de Feed:" + RS)
            print(DM + " [1] meta - Operacao e metas" + RS)
            print(DM + " [2] rendimentos - HH/ha por atividade" + RS)
            print(DM + " [3] relatorios - Buffer de relatorios" + RS)
            sub()
            feed_op = prompt("Opcao", "1").strip()
            feed_map = {"1": "meta", "2": "rendimentos", "3": "relatorios"}
            feed_escolhido = feed_map.get(feed_op, "meta")
            ok(f"Abrindo monitor com feed '{feed_escolhido}'...")
            _abrir_monitor_janela(feed=feed_escolhido)
            esperar("ENTER para voltar")
        elif v == "0":
            print(G + "\n Sistema encerrado.\n" + RS)
            break
        else:
            aviso("Opcao invalida.")


def main():
    init_monitor(contexto_sessao)
    beta = _is_beta_mode()
    legacy = _is_legacy_mode()
    sub_titulo = ""
    cfg = carregar_config()
    if modo_somente_hh(cfg):
        sub_titulo = (sub_titulo + " | " if sub_titulo else "") + "MODO SOMENTE HH"
    if beta:
        if sub_titulo:
            sub_titulo += " | PADRAO"
        else:
            sub_titulo = "PADRAO - carga robusta micro + comparativos operacionais"
    if legacy:
        if sub_titulo:
            sub_titulo += " | LEGACY"
        else:
            sub_titulo = "LEGACY - comportamento anterior sem comparativos padrao"
    cabecalho(sub_titulo)
    print(DM + " Inicializando sistema...\n" + RS)
    salvar_config(cfg)

    micro_padrao = _find_default_micro_path(cfg)
    ct_padrao = _find_default_ct_path()
    if ct_padrao:
        try:
            stg_path, n, custo_h = normalizar_ct313(ct_padrao)
            if stg_path and n > 0:
                cfg["tarifas"] = carregar_stg_tarifas(stg_path)
                cfg["custo_hora_tf"] = round(custo_h, 4)
                salvar_config(cfg)
                ok(
                    f"CT auto: {os.path.basename(ct_padrao)} -> {n} atividades (modo operacional)"
                )
        except Exception as ex:
            aviso(f"Falha no auto-carregamento CT: {ex}")

    if micro_padrao:
        df = carregar_planilha_microplanejamento(
            cfg, caminho=micro_padrao, modo_auto=True
        )
        if df is None:
            aviso("Falha no auto-carregamento do micro padrao; abrindo modo manual.")
            df = carregar_planilha_microplanejamento(cfg)
    else:
        df = carregar_planilha_microplanejamento(cfg)

    if df is not None:
        if micro_padrao:
            cfg["arquivo_micro"] = os.path.basename(micro_padrao)
            salvar_config(cfg)
        atividades_reais = sorted(
            str(x).strip() for x in df["atividade"].dropna().unique() if str(x).strip()
        )
        novos = aplicar_depara_padrao_exame(cfg, atividades_reais)
        n_faz = garantir_fazendas_micro_no_ct(cfg, df)
        if n_faz:
            salvar_config(cfg)
            ok(f"+{n_faz} fazenda(s) em fazendas_ct (a partir do micro).")
        aviso_fazendas_micro_sem_cadastro_ct(cfg, df)
        dp = {
            k: v
            for k, v in cfg.get("de_para", {}).items()
            if not str(k).startswith("_")
        }
        ok(
            f"{len(df)} registros | "
            f"{df['fazenda'].nunique()} fazendas | {df['chave'].nunique()} talhoes | "
            f"{len(dp)} de_para mapeados ({novos} novos)"
        )
        esperar("ENTER para continuar")
        menu_principal(cfg, df, micro_padrao or "")
    else:
        aviso("Nenhuma planilha selecionada.")


def _cleanup_estado_sessao():
    """Remove arquivos estado_sessao_*.json antigos ao sair."""
    try:
        import glob

        pattern = os.path.join(DIR, "estado_sessao_*.json")
        files = glob.glob(pattern)
        removed = 0
        for f in files:
            try:
                os.remove(f)
                removed += 1
            except Exception:
                pass
        if removed > 0:
            print(DM + f" [Limpo: {removed} arquivo(s) de estado removidos]" + RS)
    except Exception:
        pass


# Registrar cleanup ao sair
atexit.register(_cleanup_estado_sessao)
