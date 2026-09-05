from __future__ import annotations

from .adzuna import Adzuna
from .arbeitnow import Arbeitnow
from .base import Source
from .remoteok import RemoteOK

REGISTRY: dict[str, type[Source]] = {
    "remoteok": RemoteOK,
    "arbeitnow": Arbeitnow,
    "adzuna": Adzuna,
}

# Nunca automatizar coleta/aplicacao nessas fontes (ToS).
BLOCKED = {"linkedin", "indeed"}


def build_sources(cfg: dict) -> list[Source]:
    out: list[Source] = []
    for name, opts in (cfg.get("sources") or {}).items():
        if not isinstance(opts, dict) or not opts.get("enabled"):
            continue
        if name in BLOCKED:
            raise RuntimeError(f"Fonte bloqueada por politica: {name}")
        cls = REGISTRY.get(name)
        if cls is None:
            raise RuntimeError(f"Fonte desconhecida no config: {name}")
        out.append(cls(opts))
    if not out:
        raise RuntimeError("Nenhuma fonte habilitada no config (sources.*.enabled).")
    return out
