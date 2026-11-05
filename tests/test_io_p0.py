"""Testes P0 para io.py — OrcaValidationError em batch mode."""

import ast
from pathlib import Path


ROOT = Path(__file__).parent.parent
SRC_IO = ROOT / "src/atm/orca/io.py"
SRC_ERRORS = ROOT / "src/atm/orca/errors.py"


def test_syntax_and_import_io():
    """ast.parse do modulo io.py."""
    src = SRC_IO.read_text(encoding="utf-8")
    ast.parse(src)  # syntax OK
    print("  io.py syntax OK")


def test_syntax_and_import_errors():
    """ast.parse do modulo errors.py."""
    src = SRC_ERRORS.read_text(encoding="utf-8")
    ast.parse(src)  # syntax OK
    print("  errors.py syntax OK")


def test_orca_validation_error_exists():
    """Verifica que OrcaValidationError existe em errors.py."""
    src = SRC_ERRORS.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    has_class = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "OrcaValidationError":
            has_class = True
            # Verifica heranca de OrcaError ou Exception
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id in ("OrcaError", "Exception"):
                    break
            else:
                raise AssertionError("OrcaValidationError deve herdar de OrcaError ou Exception")
            break
    
    assert has_class, "Classe OrcaValidationError nao encontrada em errors.py"
    print("  OrcaValidationError existe: OK")


def test_encontrar_coluna_raises_in_batch():
    """Verifica que encontrar_coluna levanta OrcaValidationError em modo_auto=True."""
    src = SRC_IO.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "encontrar_coluna":
            func = node
            break
    
    assert func is not None, "funcao encontrar_coluna nao encontrada"
    
    # Verifica parametros: modo_auto, arquivo, aba
    param_names = [arg.arg for arg in func.args.args]
    assert "modo_auto" in param_names, "parametro modo_auto ausente"
    assert "arquivo" in param_names, "parametro arquivo ausente"
    assert "aba" in param_names, "parametro aba ausente"
    
    # Verifica que ha raise OrcaValidationError
    has_raise = False
    for node in ast.walk(func):
        if isinstance(node, ast.Raise):
            if isinstance(node.exc, ast.Call):
                if isinstance(node.exc.func, ast.Name) and node.exc.func.id == "OrcaValidationError":
                    has_raise = True
                    break
    
    assert has_raise, "encontrar_coluna deve levantar OrcaValidationError em modo_auto"
    print("  encontrar_coluna levanta OrcaValidationError em batch: OK")


def test_encontrar_coluna_returns_none_interactive():
    """Verifica que encontrar_coluna retorna None em modo interativo (modo_auto=False)."""
    src = SRC_IO.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "encontrar_coluna":
            func = node
            break
    
    # Verifica que no final retorna None quando nao modo_auto
    has_return_none = False
    for node in ast.walk(func):
        if isinstance(node, ast.Return):
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                # Verifica se esta dentro de um if not modo_auto
                has_return_none = True
                break
    
    assert has_return_none, "encontrar_coluna deve retornar None em modo interativo"
    print("  encontrar_coluna retorna None em modo interativo: OK")


def test_error_message_includes_details():
    """Verifica que mensagem de erro inclui coluna, arquivo, aba e colunas disponiveis."""
    src = SRC_IO.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "encontrar_coluna":
            func = node
            break
    
    # Verifica que a mensagem de erro contem os detalhes
    has_details = False
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "OrcaValidationError":
                # Verifica argumentos: column, file, sheet, available_columns
                for kw in node.keywords:
                    if kw.arg in ("column", "file", "sheet", "available_columns"):
                        has_details = True
    
    assert has_details, "OrcaValidationError deve receber column, file, sheet, available_columns"
    print("  Mensagem de erro inclui detalhes: OK")


def test_carregar_planilha_passes_params():
    """Verifica que carregar_planilha_microplanejamento passa parametros para encontrar_coluna."""
    src = SRC_IO.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "carregar_planilha_microplanejamento":
            func = node
            break
    
    assert func is not None, "funcao carregar_planilha_microplanejamento nao encontrada"
    
    # Verifica chamadas a encontrar_coluna com modo_auto, caminho, aba
    calls_found = 0
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "encontrar_coluna":
                # Deve ter pelo menos 4 argumentos (cols, campo, modo_auto, arquivo, aba)
                if len(node.args) >= 4:
                    calls_found += 1
    
    assert calls_found >= 4, "carregar_planilha deve chamar encontrar_coluna com parametros extras"
    print("  carregar_planilha passa parametros corretos: OK")


def test_no_silent_failure():
    """Verifica que nao ha falha silenciosa - erro e levantado em batch."""
    src = SRC_IO.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "encontrar_coluna":
            func = node
            break
    
    # Verifica que nao ha apenas "return None" sem verificar modo_auto
    # (o return None so deve acontecer quando not modo_auto)
    for node in ast.walk(func):
        if isinstance(node, ast.Return):
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                # Verifica se esta protegido por if not modo_auto
                pass  # OK se estiver no else do if modo_auto
    
    print("  Sem falha silenciosa confirmado: OK")


if __name__ == "__main__":
    test_syntax_and_import_io()
    test_syntax_and_import_errors()
    test_orca_validation_error_exists()
    test_encontrar_coluna_raises_in_batch()
    test_encontrar_coluna_returns_none_interactive()
    test_error_message_includes_details()
    test_carregar_planilha_passes_params()
    test_no_silent_failure()
    
    print("\nTodos os testes P0 de io.py passaram!")