"""Testes do monitor headless — nenhum spawn de terminal."""

import ast
import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_RAIZ, os.path.join(_RAIZ, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atm.orca import monitor  # noqa: E402

_CAMINHO_MONITOR = os.path.join(_RAIZ, "src", "atm", "orca", "monitor.py")


class TestMonitorHeadless(unittest.TestCase):
    def test_nenhum_subprocess_no_monitor(self):
        """A versão antiga spawnava terminal; agora não pode existir."""
        src = open(_CAMINHO_MONITOR, encoding="utf-8").read()
        arvore = ast.parse(src)
        proibidos = []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import) and any(
                a.name.split(".")[0] == "subprocess" for a in no.names
            ):
                proibidos.append(f"import subprocess (linha {no.lineno})")
            if isinstance(no, ast.ImportFrom) and (no.module or "").split(".")[0] == "subprocess":
                proibidos.append(f"from subprocess (linha {no.lineno})")
            if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name):
                if no.value.id == "subprocess":
                    proibidos.append(f"subprocess.{no.attr} (linha {no.lineno})")
        self.assertEqual(proibidos, [], f"spawn encontrado: {proibidos}")

    def test_nenhum_terminal_hardcoded(self):
        """Terminais não podem aparecer no CÓDIGO. Docstrings que explicam a
        remoção são permitidas — por isso varremos apenas linhas de código."""
        with open(_CAMINHO_MONITOR, encoding="utf-8") as f:
            linhas = f.readlines()
        arvore = ast.parse("".join(linhas))
        linhas_docstring = set()
        for no in ast.walk(arvore):
            if isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(no, clean=False)
                if doc:
                    for n in range(no.body[0].lineno, no.body[0].end_lineno + 1):
                        linhas_docstring.add(n)
        src_codigo = "".join(
            l for i, l in enumerate(linhas, start=1) if i not in linhas_docstring
        )
        for terminal in ("kitty", "wezterm", "alacritty", "gnome-terminal", "xterm", "cmd /k", "wt.exe", "xfce4-terminal"):
            self.assertNotIn(
                terminal, src_codigo,
                f"terminal '{terminal}' ainda no código — não é headless",
            )

    def test_abrir_monitor_nao_cria_processo(self):
        """Chamar _abrir_monitor_janela não pode criar subprocesso nenhum."""
        import subprocess

        criados = []

        def vigia(*a, **k):
            criados.append(a)
            raise AssertionError("subprocess.Popen chamado!")

        original = subprocess.Popen
        subprocess.Popen = vigia
        try:
            monitor.init_monitor(None, session_id="teste_headless")
            resultado = monitor._abrir_monitor_janela(feed="meta", session_id="teste_headless")
        finally:
            subprocess.Popen = original

        self.assertEqual(criados, [], "subprocess foi chamado")
        self.assertFalse(resultado, "sem orca_monitor_state deve devolver False (degradação limpa)")

    def test_estado_por_sessao(self):
        monitor.init_monitor(None, session_id="sessao_a")
        self.assertEqual(monitor._MONITOR_SESSION_ID, "sessao_a")
        monitor.init_monitor(None, session_id="sessao_b")
        self.assertEqual(monitor._MONITOR_SESSION_ID, "sessao_b")
        self.assertNotEqual(monitor._MONITOR_SESSION_ID, "sessao_a")

    def test_default_sem_session_id(self):
        monitor.init_monitor(None)
        self.assertEqual(monitor._MONITOR_SESSION_ID, "orca_default")

    def test_emissores_aceitam_session_id(self):
        """API dos emissores precisa de session_id para isolar estado."""
        for fn in (
            monitor._emitir_monitor_state,
            monitor._emitir_monitor_relatorio,
            monitor._emitir_monitor_atual,
            monitor._emitir_monitor_rendimentos,
        ):
            params = list(__import__("inspect").signature(fn).parameters)
            self.assertIn("session_id", params, f"{fn.__name__} não aceita session_id")

    def test_sem_getpid_no_estado(self):
        """PID nunca mais isola estado (quebrava web mode)."""
        src = open(_CAMINHO_MONITOR, encoding="utf-8").read()
        self.assertNotIn("os.getpid()", src)
        self.assertNotIn("getpid", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
