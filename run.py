#!/usr/bin/env python3
"""
Orca - Sistema de Restauracao Florestal
Wrapper fino: delega para a entrada canonica `python -m src.atm.atm_v6_3`.

Uso:
    python run.py                 # CLI interativa (entrada canônica)
    python run.py --version       # Mostra versão
    python run.py --help          # Mostra esta ajuda
"""

import argparse
import subprocess
import sys
from pathlib import Path

__version__ = "6.3"

REPO_ROOT = Path(__file__).resolve().parent
CANONICAL_ENTRY = ["-m", "src.atm.atm_v6_3"]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Wrapper fino: delega para `python -m src.atm.atm_v6_3`.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args, extra = parser.parse_known_args()
    proc = subprocess.run(
        [sys.executable, *CANONICAL_ENTRY, *extra],
        cwd=REPO_ROOT,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
