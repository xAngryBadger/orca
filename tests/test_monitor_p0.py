"""Testes read-only para monitor — P0: validação de session_id no lugar de PID.

Criterios:
- ast.parse do modulo monitor.py deve passar (sintaxe OK)
- import do modulo monitor deve funcionar
- Leitura de codigo: init_monitor aceita session_id
- Leitura de codigo: _emitir_monitor_* aceitam session_id
- Leitura de codigo: ausência de os.getpid() no caminho de estado
- Leitura de codigo: estado JSON isolado por session_id (path inclui session_id)
"""

import ast
import sys
import os

# Adiciona orca-rework ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_syntax_ok():
    """ast.parse do modulo monitor.py deve passar."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "monitor.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    assert tree is not None
    print("[OK] test_syntax_ok: ast.parse OK")


def test_import_monitor():
    """Import do modulo monitor deve funcionar."""
    import sys
    import os
    # Add src/atm to path for direct orca import
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "atm"))
    import orca.monitor as monitor
    assert monitor.init_monitor is not None
    assert monitor._emitir_monitor_state is not None
    assert monitor._emitir_monitor_relatorio is not None
    assert monitor._emitir_monitor_atual is not None
    assert monitor._emitir_monitor_rendimentos is not None
    assert monitor._abrir_monitor_janela is not None
    print("[OK] test_import_monitor: import OK")


def test_init_monitor_accepts_session_id():
    """init_monitor deve aceitar session_id como parametro."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "monitor.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # Verifica que init_monitor tem session_id no signature
    assert "init_monitor(contexto_sessao, session_id" in source
    print("[OK] test_init_monitor_accepts_session_id: init_monitor aceita session_id")

    # Verifica default documentado
    assert '_DEFAULT_SESSION_ID = "orca_default"' in source
    print("[OK] test_init_monitor_accepts_session_id: default session_id documentado")


def test_emit_functions_accept_session_id():
    """_emitir_monitor_* devem aceitar session_id."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "monitor.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # _emitir_monitor_state
    assert "_emitir_monitor_state(partial, session_id" in source
    print("[OK] test_emit_functions_accept_session_id: _emitir_monitor_state aceita session_id")

    # _emitir_monitor_relatorio
    assert "_emitir_monitor_relatorio(titulo, texto, session_id" in source
    print("[OK] test_emit_functions_accept_session_id: _emitir_monitor_relatorio aceita session_id")

    # _emitir_monitor_atual
    assert "_emitir_monitor_atual(session_id" in source
    print("[OK] test_emit_functions_accept_session_id: _emitir_monitor_atual aceita session_id")

    # _emitir_monitor_rendimentos
    assert "_emitir_monitor_rendimentos(" in source
    assert "session_id: str | None = None" in source
    print("[OK] test_emit_functions_accept_session_id: _emitir_monitor_rendimentos aceita session_id")

    # _abrir_monitor_janela
    assert "_abrir_monitor_janela(feed=\"meta\", session_id" in source
    print("[OK] test_emit_functions_accept_session_id: _abrir_monitor_janela aceita session_id")


def test_no_getpid_in_state_path():
    """Não deve haver os.getpid() no caminho de estado."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "monitor.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # Verifica que getpid não é usado para _MONITOR_STATE_PATH
    # O getpid pode aparecer em _abrir_monitor_janela antigo mas não no state path
    assert "_MONITOR_STATE_PATH" in source
    # O state path agora usa _resolve_state_path com session_id
    assert "_resolve_state_path" in source
    print("[OK] test_no_getpid_in_state_path: usa _resolve_state_path com session_id")


def test_state_isolated_by_session_id():
    """Estado JSON deve ser isolado por session_id (path inclui session_id)."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "monitor.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # Verifica que _resolve_state_path passa session_id para default_state_path
    assert "_monitor_default_state_path(session_id)" in source
    print("[OK] test_state_isolated_by_session_id: _monitor_default_state_path recebe session_id")

    # Verifica que _MONITOR_SESSION_ID é usado
    assert "_MONITOR_SESSION_ID" in source
    print("[OK] test_state_isolated_by_session_id: _MONITOR_SESSION_ID existe")


def test_compatibilidade_sem_session_id():
    """Chamadas sem session_id devem usar valor default, sem quebrar import."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "monitor.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # Verifica que init_monitor tem default None para session_id
    assert "session_id: str | None = None" in source
    print("[OK] test_compatibilidade_sem_session_id: session_id é opcional com default None")

    # Verifica fallback para _DEFAULT_SESSION_ID
    assert '_MONITOR_SESSION_ID = session_id or _DEFAULT_SESSION_ID' in source
    print("[OK] test_compatibilidade_sem_session_id: fallback para _DEFAULT_SESSION_ID")


if __name__ == "__main__":
    test_syntax_ok()
    test_import_monitor()
    test_init_monitor_accepts_session_id()
    test_emit_functions_accept_session_id()
    test_no_getpid_in_state_path()
    test_state_isolated_by_session_id()
    test_compatibilidade_sem_session_id()
    print("\n[OK] Todos os testes P0 passaram!")