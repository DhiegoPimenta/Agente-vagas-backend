#!/usr/bin/env python3
"""Ponto de entrada do agente de curadoria de vagas.

Uso:
  python run.py --init        cria config.yaml a partir do exemplo
  python run.py               roda a coleta + score + relatorio (e e-mail, se ligado)
  python run.py --dry-run     roda sem gravar no banco nem enviar e-mail
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Agente de curadoria de vagas (curadoria-only).")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"), help="caminho do config.yaml")
    parser.add_argument("--init", action="store_true", help="cria config.yaml a partir de config.example.yaml")
    parser.add_argument("--dry-run", action="store_true", help="nao grava no banco nem envia e-mail")
    args = parser.parse_args()

    if args.init:
        dst = Path(args.config)
        if dst.exists():
            print(f"{dst} ja existe - nao sobrescrevi.")
            return 1
        shutil.copy(ROOT / "config.example.yaml", dst)
        print(f"Criado {dst}\nEdite os dados do candidato e rode: python run.py")
        return 0

    from jobagent.pipeline import run

    return run(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
