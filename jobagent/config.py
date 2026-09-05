from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_NAME = "config.yaml"


def load_config(path: str | os.PathLike) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Config nao encontrado: {p}\n"
            f"Rode `python run.py --init` e edite {DEFAULT_CONFIG_NAME} com os dados do candidato."
        )
    with p.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    _apply_env_overrides(cfg)
    return cfg


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    """Credenciais e caminhos podem vir de variaveis de ambiente em vez do arquivo."""
    adz = (cfg.get("sources") or {}).get("adzuna")
    if isinstance(adz, dict):
        if os.getenv("ADZUNA_APP_ID"):
            adz["app_id"] = os.environ["ADZUNA_APP_ID"]
        if os.getenv("ADZUNA_APP_KEY"):
            adz["app_key"] = os.environ["ADZUNA_APP_KEY"]

    if os.getenv("PAGES_DIR"):
        cfg.setdefault("output", {})["pages_dir"] = os.environ["PAGES_DIR"]
    if os.getenv("SCORING_MODE"):
        cfg.setdefault("scoring", {})["mode"] = os.environ["SCORING_MODE"]
    if os.getenv("MAX_JOBS_PER_SOURCE"):
        try:
            cfg.setdefault("collection", {})["max_jobs_per_source"] = int(os.environ["MAX_JOBS_PER_SOURCE"])
        except ValueError:
            pass
    if os.getenv("ANALYSIS_ENABLED"):
        cfg.setdefault("analysis", {})["enabled"] = (
            os.environ["ANALYSIS_ENABLED"].strip().lower() in ("1", "true", "yes", "on")
        )
