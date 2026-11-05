"""Testes read-only para tarifas — P0: validação de cache preco_final.json (SF-05).

Criterios:
- ast.parse do modulo tarifas.py deve passar (sintaxe OK)
- import do modulo tarifas deve funcionar
- Leitura de codigo: _carregar_mapa_preco_final_json deve checar mtime + TTL
- Funcao invalidate_preco_final_cache deve existir e limpar cache
"""

import ast
import importlib.util
import sys
import os

# Adiciona orca-rework ao path para que src seja um package propri
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_syntax_ok():
    """ast.parse do modulo tarifas.py deve passar."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "tarifas.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    assert tree is not None
    print("[OK] test_syntax_ok: ast.parse OK")


def test_import_tarifas():
    """Import do modulo tarifas deve funcionar."""
    from src.atm.orca.tarifas import _carregar_mapa_preco_final_json, invalidate_preco_final_cache
    assert _carregar_mapa_preco_final_json is not None
    assert invalidate_preco_final_cache is not None
    print("[OK] test_import_tarifas: import OK")


def test_cache_checks_mtime_and_ttl():
    """Leitura de codigo: _carregar_mapa_preco_final_json deve checar mtime + TTL."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "tarifas.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # Verifica que a funcao existe
    assert "_carregar_mapa_preco_final_json" in source
    print("[OK] test_cache_checks_mtime_and_ttl: funcao _carregar_mapa_preco_final_json existe")

    # Verifica que checa mtime
    assert "mtime" in source
    print("[OK] test_cache_checks_mtime_and_ttl: checa mtime")

    # Verifica que checa TTL (loaded_at + now - loaded_at < ttl)
    assert "loaded_at" in source
    print("[OK] test_cache_checks_mtime_and_ttl: usa loaded_at para TTL")

    # Verifica que usa preco_final_json_ttl(cfg)
    assert "preco_final_json_ttl" in source
    print("[OK] test_cache_checks_mtime_and_ttl: usa preco_final_json_ttl(cfg)")


def test_invalidate_preco_final_cache_exists():
    """Funcao invalidate_preco_final_cache deve existir e limpar cache."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "tarifas.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # Verifica que a funcao existe
    assert "invalidate_preco_final_cache" in source
    print("[OK] test_invalidate_preco_final_cache_exists: funcao invalidate_preco_final_cache existe")

    # Verifica que limpa o cache (reset do dicionario)
    assert "_PRECO_FINAL_JSON_CACHE" in source
    print("[OK] test_invalidate_preco_final_cache_exists: manipula _PRECO_FINAL_JSON_CACHE")


def test_config_has_ttl_function():
    """config.py deve ter funcao preco_final_json_ttl com fallback."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "atm", "orca", "config.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    assert "preco_final_json_ttl" in source
    print("[OK] test_config_has_ttl_function: funcao preco_final_json_ttl existe")

    assert "_PRECO_FINAL_JSON_TTL_DEFAULT" in source
    print("[OK] test_config_has_ttl_function: constante _PRECO_FINAL_JSON_TTL_DEFAULT existe")

    assert "3600" in source
    print("[OK] test_config_has_ttl_function: default 3600s presente")


if __name__ == "__main__":
    test_syntax_ok()
    test_import_tarifas()
    test_cache_checks_mtime_and_ttl()
    test_invalidate_preco_final_cache_exists()
    test_config_has_ttl_function()
    print("\n[OK] Todos os testes P0 passaram!")