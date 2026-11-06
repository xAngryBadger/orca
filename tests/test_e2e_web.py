"""E2E do painel web NOBO — FastAPI em ``src/atm/web``.

Cobre o app real (``src.atm.web.app``) via ``fastapi.testclient.TestClient``:
painel, ciclo de dados (micro/tarifas/validar), simulações (grade padrão,
grade personalizada, cenário único), página de resultado e limpeza de sessão.

Regras do teste:
- unittest puro (sem pytest);
- fixtures mínimas em diretório temporário (``tempfile``) — nunca depende de
  ``data/planilhas`` real e não deixa arquivo no repo;
- os path finders do bridge são redirecionados para as fixtures via patch
  (os loaders NÃO leem ``ORCA_DATA_DIR``: os paths são constantes de módulo);
- o ``session_id`` usado nos forms sai do cookie ``orca_session``.
"""

from __future__ import annotations

import gc
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Estado de módulo (preenchido em setUpModule) ─────────────────

_APP: dict = {}     # app FastAPI + módulo bridge + cwd original
_FIX: dict = {}     # caminhos das fixtures em tmp
_TMP: dict = {}     # diretório temporário
_PATCHES: list = []


def _importar_fixtures_com_espera():
    """Importa as fixtures mínimas; se ainda não existirem, espera 60s e tenta de novo."""
    try:
        from tests.fixtures.create_minimal_fixture import (
            create_minimal_config_json,
            create_minimal_microplanejamento,
            create_minimal_stg_tarifas,
        )
    except ModuleNotFoundError:
        # Outro agente pode estar commitando tests/fixtures agora.
        time.sleep(60)
        from tests.fixtures.create_minimal_fixture import (
            create_minimal_config_json,
            create_minimal_microplanejamento,
            create_minimal_stg_tarifas,
        )
    return (
        create_minimal_microplanejamento,
        create_minimal_config_json,
        create_minimal_stg_tarifas,
    )


def setUpModule():
    """Sobe o app, cria fixtures em tmp e isola os path finders do bridge."""
    _APP["orig_cwd"] = os.getcwd()
    os.chdir(ROOT)  # Jinja2Templates usa directory relativo: src/atm/web/templates

    from fastapi.testclient import TestClient
    from src.atm.web.app import app as fastapi_app
    from src.atm.web import bridge as web_bridge

    _APP["app"] = fastapi_app
    _APP["bridge"] = web_bridge
    _APP["TestClient"] = TestClient

    (
        criar_micro,
        criar_config_json,
        criar_stg,
    ) = _importar_fixtures_com_espera()

    tmp = tempfile.mkdtemp(prefix="orca_e2e_web_")
    _TMP["dir"] = tmp
    _FIX["micro"] = criar_micro(str(Path(tmp) / "microplanejamento.xlsx"))
    _FIX["stg"] = criar_stg(str(Path(tmp) / "stg_tarifas.xlsx"))
    criar_config_json(str(Path(tmp) / "config.json"))

    # Os loaders buscam arquivos por caminhos default (config.json / data/planilhas).
    # Para o teste usar as fixtures sem tocar em dados reais, redireciona a busca.
    for nome, caminho in (
        ("_encontrar_micro_path", _FIX["micro"]),
        ("_encontrar_ct_path", _FIX["stg"]),
    ):
        patcher = mock.patch.object(web_bridge, nome, return_value=caminho)
        patcher.start()
        _PATCHES.append(patcher)


def tearDownModule():
    """Desfaz patches, limpa sessões, remove o tmp e devolve o cwd original."""
    for patcher in _PATCHES:
        patcher.stop()
    _PATCHES.clear()

    bridge = _APP.get("bridge")
    if bridge is not None:
        bridge._sessions.clear()

    tmp = _TMP.get("dir")
    if tmp and os.path.isdir(tmp):
        # no Windows o handle do .xlsx pode demorar a soltar (WinError 32) — retenta
        for _ in range(5):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                gc.collect()
                time.sleep(0.3)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    orig = _APP.get("orig_cwd")
    if orig:
        os.chdir(orig)


class TestE2EWeb(unittest.TestCase):
    """E2E do painel FastAPI — rotas, contexto dos templates e cookie de sessão."""

    def setUp(self):
        # isola estado entre testes: sessões são globais no bridge
        self.bridge = _APP["bridge"]
        self.bridge._sessions.clear()
        self._client_ctx = _APP["TestClient"](_APP["app"])
        self.client = self._client_ctx.__enter__()
        self.addCleanup(self._client_ctx.__exit__, None, None, None)

    # ── helpers ────────────────────────────────────────────────

    def _session_id(self) -> str:
        """Lê o session_id do cookie ``orca_session`` mantido pelo TestClient."""
        sid = self.client.cookies.get("orca_session")
        self.assertIsNotNone(
            sid, "cookie orca_session deveria existir após a primeira resposta HTML"
        )
        self.assertRegex(
            sid, r"^[0-9a-f]{8}$", f"session_id inesperado no cookie: {sid!r}"
        )
        return sid

    def _fatia_grade_completa(self, html: str) -> str:
        """Fatia do HTML da seção 'Grade completa' (até 'Por jornada')."""
        ini = html.find("Grade completa")
        self.assertGreaterEqual(
            ini, 0, "seção 'Grade completa' não encontrada no resultado"
        )
        fim = html.find("Por jornada", ini)
        self.assertGreater(
            fim, ini, "seção 'Por jornada' não encontrada após a grade completa"
        )
        return html[ini:fim]

    def _n_cenarios_executados(self, html: str) -> int:
        """Extrai o contador 'N cenários executados' do resultado.html."""
        m = re.search(r"(\d+)\s*cenários executados", html)
        self.assertIsNotNone(
            m, "contador 'N cenários executados' não encontrado no resultado"
        )
        return int(m.group(1))

    def _abrir_painel(self) -> str:
        """GET / e devolve o session_id do cookie."""
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200, f"GET / deveria responder 200: {r.text[:300]}")
        return self._session_id()

    def _carregar_dados(self) -> str:
        """Carrega micro + tarifas mínimos e valida; devolve o session_id."""
        sid = self._abrir_painel()

        r = self.client.post("/carregar-micro", data={"session_id": sid})
        self.assertEqual(
            r.status_code, 200, f"/carregar-micro deveria responder 200: {r.text[:300]}"
        )
        self.assertIn("badge-ok", r.text, "micro carregado deveria exibir badge ok")
        self.assertIn("talhões", r.text, "badge do micro deveria contar talhões")
        state = self.bridge.obter_estado(sid)
        self.assertTrue(
            state.micro_rows, f"micro_rows vazio após /carregar-micro — erro: {state.erro}"
        )
        self.assertIsNone(state.erro, f"/carregar-micro não deveria deixar erro: {state.erro}")

        r = self.client.post("/carregar-tarifas", data={"session_id": sid})
        self.assertEqual(
            r.status_code, 200, f"/carregar-tarifas deveria responder 200: {r.text[:300]}"
        )
        self.assertIn("badge-ok", r.text, "tarifas carregadas deveriam exibir badge ok")
        self.assertIn("atividades", r.text, "badge das tarifas deveria contar atividades")
        state = self.bridge.obter_estado(sid)
        self.assertTrue(
            state.tarifas, f"tarifas vazias após /carregar-tarifas — erro: {state.erro}"
        )

        r = self.client.post("/validar", data={"session_id": sid})
        self.assertEqual(r.status_code, 200, f"/validar deveria responder 200: {r.text[:300]}")
        self.assertNotIn(
            "border-err/30", r.text, "/validar não deveria exibir caixa de erro"
        )
        return sid

    # ── casos ──────────────────────────────────────────────────

    def test_01_painel_inicial(self):
        """GET / -> 200 HTML com cookie de sessão e botão da grade desabilitado."""
        r = self.client.get("/")

        self.assertEqual(r.status_code, 200, f"GET / deveria responder 200: {r.text[:300]}")
        self.assertTrue(
            r.headers.get("content-type", "").startswith("text/html"),
            f"GET / deveria devolver HTML, veio: {r.headers.get('content-type')!r}",
        )
        self.assertIn("Orca", r.text, "painel deveria conter a marca 'Orca'")
        self.assertIn(
            "orca_session",
            r.headers.get("set-cookie", ""),
            "toda resposta HTML deveria setar o cookie orca_session",
        )

        sid = self._session_id()
        self.assertIsNotNone(sid, "cookie de sessão deveria ser criado no GET /")

        self.assertIn(
            'hx-post="/comparar-grade"',
            r.text,
            "painel deveria ter o form da grade padrão (hx-post=/comparar-grade)",
        )
        self.assertIn(
            "Simular grade padrão", r.text, "botão da grade padrão não encontrado"
        )
        self.assertIn(
            "aguardando", r.text, "badges de dados deveriam estar 'aguardando' sem dados"
        )

        # sem micro/tarifas o botão nasce desabilitado
        ini = r.text.find('hx-post="/comparar-grade"')
        fim = r.text.find("</form>", ini)
        self.assertGreater(fim, ini, "form da grade padrão não encontrado")
        self.assertIn(
            "disabled",
            r.text[ini:fim],
            "botão 'Simular grade padrão' deveria estar desabilitado sem dados",
        )

    def test_02_fluxo_completo(self):
        """Fluxo feliz: carregar micro/tarifas, validar, grade padrão e resultado."""
        sid = self._carregar_dados()

        r = self.client.post("/comparar-grade", data={"session_id": sid})
        self.assertEqual(
            r.status_code, 200, f"/comparar-grade deveria responder 200: {r.text[:300]}"
        )
        state = self.bridge.obter_estado(sid)
        self.assertEqual(
            len(state.cenarios),
            12,
            f"grade padrão deveria gerar 12 cenários (3 jornadas x 4 equipes), "
            f"gerou {len(state.cenarios)} — erro: {state.erro}",
        )
        self.assertIsNone(state.erro, f"simulação não deveria deixar erro: {state.erro}")

        # painel: seção de resultados + badge com contagem dos 12 cenários
        # (o comentário "Passo 3 · Resultados" é estático; estoura o conteúdo do bloco)
        self.assertIn(
            ">12 cenários<",
            r.text,
            "badge do painel deveria contar os 12 cenários",
        )
        self.assertIn(
            "Resultados completos",
            r.text,
            "link 'Resultados completos' deveria aparecer no painel com cenários",
        )
        self.assertIn("Uso%", r.text, "tabela do painel deveria ter coluna Uso%")

        r = self.client.get(f"/resultado?session_id={sid}")
        self.assertEqual(
            r.status_code, 200, f"/resultado deveria responder 200: {r.text[:300]}"
        )
        self.assertTrue(
            r.headers.get("content-type", "").startswith("text/html"),
            f"/resultado deveria devolver HTML, veio: {r.headers.get('content-type')!r}",
        )
        self.assertIn(
            "orca_session",
            r.headers.get("set-cookie", ""),
            "/resultado também deveria setar o cookie de sessão",
        )
        self.assertIn("Resumo", r.text, "resultado deveria ter a seção 'Resumo'")
        self.assertEqual(
            self._n_cenarios_executados(r.text),
            12,
            "resultado deveria contabilizar 12 cenários executados",
        )
        self.assertEqual(
            self._fatia_grade_completa(r.text).count("<tr>"),
            13,
            "grade completa deveria ter 12 linhas de cenário (13 <tr> com o cabeçalho)",
        )

    def test_03_grade_personalizada(self):
        """/simular com jornadas=4.6,6.0 e equipes=4,9 -> 4 cenários."""
        sid = self._carregar_dados()

        r = self.client.post(
            "/simular",
            data={
                "session_id": sid,
                "jornadas": "4.6,6.0",
                "equipes": "4,9",
                "executores_base": 9,
                "jornada_base": 4.6,
            },
        )
        self.assertEqual(
            r.status_code, 200, f"/simular deveria responder 200: {r.text[:300]}"
        )
        state = self.bridge.obter_estado(sid)
        self.assertEqual(
            len(state.cenarios),
            4,
            f"grade 2x2 deveria gerar 4 cenários, gerou {len(state.cenarios)} — "
            f"erro: {state.erro}",
        )
        self.assertIsNone(state.erro, f"/simular não deveria deixar erro: {state.erro}")

        r = self.client.get(f"/resultado?session_id={sid}")
        self.assertEqual(r.status_code, 200, "/resultado deveria responder 200")
        self.assertEqual(
            self._n_cenarios_executados(r.text), 4, "resultado deveria ter 4 cenários"
        )
        self.assertEqual(
            self._fatia_grade_completa(r.text).count("<tr>"),
            5,
            "grade completa deveria ter 4 linhas de cenário (5 <tr> com o cabeçalho)",
        )

    def test_04_jornadas_invalidas(self):
        """/simular com jornadas='abc' -> 200 com mensagem de erro, sem 500."""
        sid = self._carregar_dados()

        # primeiro uma simulação válida, para provar que o erro preserva o estado
        r = self.client.post("/comparar-grade", data={"session_id": sid})
        self.assertEqual(r.status_code, 200, "grade padrão deveria responder 200")

        r = self.client.post(
            "/simular",
            data={
                "session_id": sid,
                "jornadas": "abc",
                "equipes": "4,9",
                "executores_base": 9,
                "jornada_base": 4.6,
            },
        )
        self.assertEqual(
            r.status_code,
            200,
            "jornadas inválidas deveriam voltar ao painel com 200, não estourar: "
            f"{r.text[:300]}",
        )
        self.assertIn(
            "inválidos", r.text, "resposta deveria conter a mensagem de erro 'inválidos'"
        )
        self.assertIn(
            'hx-post="/comparar-grade"',
            r.text,
            "estado deveria voltar para o painel (form da grade padrão presente)",
        )
        state = self.bridge.obter_estado(sid)
        self.assertEqual(
            len(state.cenarios),
            12,
            "simulação inválida não deveria alterar os cenários já existentes",
        )

    def test_05_cenario_unico(self):
        """/simular-unico com jornada=6 e equipe=9 -> 1 cenário."""
        sid = self._carregar_dados()

        r = self.client.post(
            "/simular-unico",
            data={"session_id": sid, "jornada": 6, "equipe": 9},
        )
        self.assertEqual(
            r.status_code, 200, f"/simular-unico deveria responder 200: {r.text[:300]}"
        )
        state = self.bridge.obter_estado(sid)
        self.assertEqual(
            len(state.cenarios),
            1,
            f"cenário único deveria gerar 1 cenário, gerou {len(state.cenarios)} — "
            f"erro: {state.erro}",
        )
        self.assertEqual(
            state.cenarios[0]["executores"], 9, "cenário único deveria usar 9 operários"
        )
        self.assertEqual(
            state.cenarios[0]["jornada"], 6.0, "cenário único deveria usar jornada 6h"
        )

        r = self.client.get(f"/resultado?session_id={sid}")
        self.assertEqual(r.status_code, 200, "/resultado deveria responder 200")
        self.assertEqual(
            self._n_cenarios_executados(r.text), 1, "resultado deveria ter 1 cenário"
        )
        self.assertEqual(
            self._fatia_grade_completa(r.text).count("<tr>"),
            2,
            "grade completa deveria ter 1 linha de cenário (2 <tr> com o cabeçalho)",
        )

    def test_06_limpar(self):
        """/limpar -> 200, badges 'aguardando' de volta e sessão vazia."""
        sid = self._carregar_dados()
        r = self.client.post("/comparar-grade", data={"session_id": sid})
        self.assertEqual(r.status_code, 200, "grade padrão deveria responder 200 antes de limpar")

        r = self.client.post("/limpar", data={"session_id": sid})
        self.assertEqual(
            r.status_code, 200, f"/limpar deveria responder 200: {r.text[:300]}"
        )
        self.assertGreaterEqual(
            r.text.count("aguardando"),
            2,
            "badges de micro e tarifas deveriam voltar para 'aguardando'",
        )
        self.assertNotIn(
            "Resultados completos",
            r.text,
            "bloco de resultados deveria desaparecer após limpar",
        )
        state = self.bridge.obter_estado(sid)
        self.assertEqual(state.micro_rows, [], "sessão limpa não deveria ter micro_rows")
        self.assertEqual(state.tarifas, {}, "sessão limpa não deveria ter tarifas")
        self.assertEqual(state.cenarios, [], "sessão limpa não deveria ter cenários")

    def test_07_resultado_sessao_desconhecida(self):
        """/resultado com session_id desconhecida -> 200 com empty state."""
        r = self.client.get("/resultado?session_id=zzzzzzzz")

        self.assertEqual(
            r.status_code, 200, f"/resultado deveria responder 200: {r.text[:300]}"
        )
        self.assertTrue(
            r.headers.get("content-type", "").startswith("text/html"),
            f"/resultado deveria devolver HTML, veio: {r.headers.get('content-type')!r}",
        )
        self.assertIn(
            "Nenhum cenário simulado",
            r.text,
            "sessão sem cenários deveria mostrar o empty state",
        )
        self.assertNotIn("Resumo", r.text, "empty state não deveria ter a seção 'Resumo'")
        self.assertEqual(
            self._n_cenarios_executados(
                r.text
            ),
            0,
            "sessão desconhecida deveria contabilizar 0 cenários",
        )


if __name__ == "__main__":
    unittest.main()
