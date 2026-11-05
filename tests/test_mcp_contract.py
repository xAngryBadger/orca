"""Contrato do servidor MCP — teste end-to-end por subprocess stdio.

Simula um cliente MCP real: initialize → tools/list → tools/call →
resources/list → resources/read. Roda o servidor como subprocess
(Popen com pipes), que é exatamente como um cliente MCP o usa.

O servidor é `src/atm/mcp_server.py`: JSON-RPC 2.0 sobre stdio, sem
dependência externa. Nenhuma tool calcula por conta própria — todas
delegam ao motor real (engine_pkg, comparativo_real).
"""

import json
import os
import subprocess
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVIDOR = os.path.join(_RAIZ, "src", "atm", "mcp_server.py")
_PLANILHA = os.path.join(_RAIZ, "data", "planilhas", "mcp_contrato.xlsx")


def _criar_planilha():
    import pandas as pd

    os.makedirs(os.path.dirname(_PLANILHA), exist_ok=True)
    linhas = []
    for i, t in enumerate(["T1", "T2", "T3", "T4"]):
        # nomes EXATOS do catálogo CT317 (data/ct317_hardcode_hh_base.yaml):
        # a cobertura do PipelineConfig bate por igualdade estrita, então a
        # roçada precisa da cedilha — "ROCADA" (sem Ç) não casa e gera BARROU.
        for a in [
            "ROÇADA MANUAL Impl. CD APP/RL I",
            "COMBATE A FORMIGAS Impl. CD APP/RL",
            "PLANTIO MANUAL APP/RL",
            "IRRIGACAO INICIAL MAN APP/RL",
        ]:
            linhas.append(
                {
                    "NOME FAZENDA": "FAZ_CONTRATO",
                    "CHAVE POLIGONO": t,
                    "AREA POLIGONO (HECTARE)": 10.0 + i,
                    "ATIVIDADES": a,
                }
            )
    pd.DataFrame(linhas).to_excel(_PLANILHA, index=False)
    return _PLANILHA


def _extrair_jsonrpc(texto):
    """Extrai um objeto JSON-RPC de `texto`.

    O servidor MCP é um CLI cujo motor REAL imprime banners legíveis em
    stdout (orc/io.py, scheduler_core.py, engine.py usam print()). Como o
    stdout É o canal do protocolo, essas linhas de banner se misturam às
    respostas JSON-RPC. O cliente precisa descartar o ruído e achar a
    resposta: uma linha que seja, ou contenha, um objeto com "jsonrpc".
    Também tolera progresso do scheduler gravado com end="\\r" colado na
    frente da resposta (mesma linha física, sem \\n entre os dois).
    """
    dec = json.JSONDecoder()
    limpo = texto.strip()
    if limpo:
        try:
            obj = json.loads(limpo)
            if isinstance(obj, dict) and "jsonrpc" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    i = texto.find("{")
    while i != -1:
        try:
            obj, _fim = dec.raw_decode(texto, i)
            if isinstance(obj, dict) and "jsonrpc" in obj:
                return obj
        except json.JSONDecodeError:
            pass
        i = texto.find("{", i + 1)
    return None


class ClienteMCP:
    """Cliente MCP mínimo sobre stdio."""

    def __init__(self):
        # bufsize default (block-buffered): bufsize=1 não ajuda — a causa do
        # lixo é o print() do motor em stdout, não buffering.
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", _SERVIDOR],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=_RAIZ,
        )
        self._id = 0

    def _ler_resposta(self):
        """Lê linhas de stdout até achar uma resposta JSON-RPC, descartando
        as linhas de banner que o motor imprime no mesmo stream."""
        while True:
            linha = self.proc.stdout.readline()
            if linha == "":
                erro = "(stderr vazio)"
                try:
                    if self.proc.poll() is not None:
                        erro = self.proc.stderr.read() or erro
                except Exception:
                    pass
                raise AssertionError(
                    f"servidor encerrou o stdout sem responder: {erro[:600]}"
                )
            resposta = _extrair_jsonrpc(linha)
            if resposta is not None:
                return resposta
            # linha de ruído (banner/progresso do motor) — segue o baile

    def chamar(self, metodo, params=None):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": metodo}
        if params is not None:
            req["params"] = params
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        return self._ler_resposta()

    def tool(self, nome, argumentos=None):
        r = self.chamar("tools/call", {"name": nome, "arguments": argumentos or {}})
        if "error" in r:
            raise AssertionError(f"{nome} devolveu erro: {r['error']}")
        return json.loads(r["result"]["content"][0]["text"])

    def fechar(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class TestContratoMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caminho = _criar_planilha()
        cls.cli = ClienteMCP()
        # Aquece o _SESSAO do servidor: orca_comparar_cenarios/orca_metricas
        # exigem micro carregado, e o unittest roda os métodos em ordem
        # alfabética — test_comparar_cenarios viria ANTES de test_fluxo_completo
        # (que carrega o micro). Aquecer aqui deixa a suíte independente da ordem.
        cls.cli.tool("orca_carregar_tarifas", {})
        cls.cli.tool("orca_carregar_micro", {"caminho": cls.caminho})

    @classmethod
    def tearDownClass(cls):
        cls.cli.fechar()

    def test_initialize_declara_servidor(self):
        r = self.cli.chamar("initialize", {"protocolVersion": "2024-11-05"})
        info = r["result"]["serverInfo"]
        self.assertEqual(info["name"], "orca-mcp")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertIn("resources", r["result"]["capabilities"])

    def test_resposta_eco_id_da_requisicao(self):
        """JSON-RPC 2.0: a resposta deve ecoar o id da requisição."""
        self.cli._id = 0
        r = self.cli.chamar("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(r["id"], 1, "resposta deve ecoar o id da requisição")
        self.assertEqual(r["jsonrpc"], "2.0")
        self.assertIn("result", r)

    def test_tools_list_expoe_as_7_ferramentas(self):
        r = self.cli.chamar("tools/call" if False else "tools/list")
        nomes = sorted(t["name"] for t in r["result"]["tools"])
        self.assertEqual(
            nomes,
            sorted(
                [
                    "orca_carregar_micro",
                    "orca_carregar_tarifas",
                    "orca_comparar_cenarios",
                    "orca_listar_fazendas",
                    "orca_metricas",
                    "orca_simular_cenario",
                    "orca_validar_pipeline",
                ]
            ),
        )
        for t in r["result"]["tools"]:
            self.assertTrue(t.get("description"), t["name"])
            self.assertEqual(t["inputSchema"]["type"], "object", t["name"])

    def test_resources_list_expoe_baseline_e_schemas(self):
        r = self.cli.chamar("resources/list")
        uris = sorted(x["uri"] for x in r["result"]["resources"])
        self.assertEqual(uris, ["orca://baseline", "orca://schemas"])

    def test_fluxo_completo_carregar_validar_simular(self):
        """O fluxo que um agente de IA usaria, ponta a ponta."""
        tarifas = self.cli.tool("orca_carregar_tarifas", {})
        self.assertEqual(tarifas["fonte"].split()[0], "CT317_HARDCODE_HH_BASE")
        self.assertEqual(tarifas["tarifas"], 107)

        micro = self.cli.tool("orca_carregar_micro", {"caminho": self.caminho})
        self.assertEqual(micro["linhas"], 16)
        self.assertEqual(micro["talhoes"], 4)
        self.assertEqual(len(micro["atividades"]), 4)

        val = self.cli.tool("orca_validar_pipeline", {})
        self.assertEqual(val["veredicto"], "PASSOU")
        self.assertEqual(val["cobertura"]["cobertura_pct"], 100.0)

        fazendas = self.cli.tool("orca_listar_fazendas", {})
        self.assertEqual(len(fazendas["fazendas"]), 1)
        self.assertEqual(fazendas["fazendas"][0]["fazenda"], "FAZ_CONTRATO")

        cenario = self.cli.tool(
            "orca_simular_cenario", {"executores": 9, "jornada": 6.5}
        )
        self.assertGreater(cenario["dias_simulados"], 0)
        self.assertEqual(cenario["veredicto"], "COMPLETO")
        self.assertEqual(cenario["talhoes"], 4)

        metricas = self.cli.tool("orca_metricas", {})
        self.assertEqual(metricas["dias_simulados"], cenario["dias_simulados"])

    def test_comparar_cenarios_usa_scheduler_real(self):
        r = self.cli.tool(
            "orca_comparar_cenarios", {"jornadas": [4.3, 6.5], "equipes": [6, 12]}
        )
        self.assertEqual(len(r["cenarios"]), 4)
        self.assertEqual(r["nota"].split()[0], "dias")
        melhor = r["melhor"]
        self.assertLessEqual(melhor["executores"], 12)
        self.assertGreater(melhor["dias_simulados"], 0)
        # grade monotônica: 12 ops não pode ser pior que 6 ops na mesma jornada
        por_jornada = {}
        for c in r["cenarios"]:
            por_jornada.setdefault(c["jornada"], {})[c["executores"]] = c["dias_simulados"]
        for jornada, por_equipe in por_jornada.items():
            self.assertLessEqual(
                por_equipe[12], por_equipe[6],
                f"jornada {jornada}: 12 ops deveria ser <= 6 ops",
            )

    def test_recurso_baseline_traz_head_e_modulos(self):
        r = self.cli.chamar("resources/read", {"uri": "orca://baseline"})
        base = json.loads(r["result"]["contents"][0]["text"])
        self.assertTrue(base["head"])
        self.assertGreaterEqual(len(base["modulos_orca"]), 20)
        self.assertEqual(base["tarifas_ct317"], 107)

    def test_recurso_schemas_traz_json_schema(self):
        r = self.cli.chamar("resources/read", {"uri": "orca://schemas"})
        sch = json.loads(r["result"]["contents"][0]["text"])
        self.assertIn("MicroRow", sch)
        self.assertIn("properties", sch["MicroRow"])
        self.assertEqual(sch["regra_hh_hm"], "rendimento_hh > 0 implica rendimento_hm = 0")

    def test_ferramenta_inexistente_devolve_erro(self):
        r = self.cli.chamar("tools/call", {"name": "orca_nao_existe", "arguments": {}})
        self.assertIn("error", r)
        self.assertIn("desconhecida", r["error"]["message"])

    def test_metodo_inexistente_devolve_erro(self):
        r = self.cli.chamar("metipo/que.nao.existe")
        self.assertIn("error", r)
        self.assertEqual(r["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main(verbosity=2)
