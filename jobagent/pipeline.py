from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import load_config
from .emailer import send_email
from .forms import classify_form
from .models import Job, Scored
from .report import build_report
from .routing import route
from .scoring import maybe_analyze, score_all
from .sources import BLOCKED, build_sources
from .store import Store


def _dedupe(jobs: list[Job]) -> list[Job]:
    """Remove duplicatas por (empresa + titulo + local), mantendo a primeira ocorrencia."""
    seen: dict[str, Job] = {}
    for job in jobs:
        key = " | ".join(part.strip().lower() for part in (job.company, job.title, job.location))
        seen.setdefault(key, job)
    return list(seen.values())


@dataclass
class RunResult:
    collected: int
    unique: int
    new: int
    recommended: list[Scored] = field(default_factory=list)
    discarded: list[Scored] = field(default_factory=list)
    applied: list[Scored] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def build_results(cfg: dict, *, use_store: bool = True) -> RunResult:
    """
    Executa coleta -> score -> roteamento -> analise e devolve os dados em memoria.

    use_store=True usa o SQLite para nao reprocessar vagas ja vistas (CLI / cron).
    use_store=False ignora o banco e trata tudo como novo (backend sem disco fixo).
    """
    cand = cfg.get("candidate", {})
    coll = cfg.get("collection", {})
    lookback = int(coll.get("lookback_hours", 48))
    cap = int(coll.get("max_jobs_per_source", 200))

    print(f"[1] Coleta (ultimas {lookback}h)")
    collected: list[Job] = []
    for source in build_sources(cfg):
        try:
            got = source.fetch(lookback, cap)
            print(f"    {source.name}: {len(got)} vagas")
            collected.extend(got)
        except Exception as exc:  # uma fonte quebrada nao derruba o resto
            print(f"    {source.name}: ERRO - {exc}", file=sys.stderr)

    collected = [j for j in collected if j.source not in BLOCKED]
    deduped = _dedupe(collected)

    store = None
    if use_store:
        store = Store(cfg.get("output", {}).get("db_path", "data/jobagent.sqlite3"))
        already = store.known([j.uid for j in deduped])
        fresh = [j for j in deduped if j.uid not in already]
    else:
        fresh = deduped
    print(f"[2] {len(collected)} coletadas - {len(deduped)} unicas - {len(fresh)} novas")

    print("[3] Score + roteamento")
    scored: list[Scored] = score_all(fresh, cand, cfg)
    for s in scored:
        s.form_complexity = classify_form(s.job)
        route(s, cfg)

    recommended = sorted((s for s in scored if s.route == "recomendada"), key=lambda s: s.score, reverse=True)
    discarded = sorted((s for s in scored if s.route == "descartada"), key=lambda s: s.score, reverse=True)
    applied = [s for s in scored if s.route == "auto_apply"]  # sempre vazio nesta versao

    print("[4] Analise das recomendadas")
    maybe_analyze(recommended, cand, cfg)

    if store is not None:
        for s in scored:
            store.upsert(s)
        store.record_run(len(deduped), len(fresh), len(recommended), len(discarded))
        store.close()

    return RunResult(
        collected=len(collected),
        unique=len(deduped),
        new=len(fresh),
        recommended=recommended,
        discarded=discarded,
        applied=applied,
    )


def run(config_path: str, dry_run: bool = False) -> int:
    """Fluxo de linha de comando: gera o relatorio e (se ligado) manda e-mail."""
    cfg = load_config(config_path)
    result = build_results(cfg, use_store=not dry_run)

    html, path = build_report(
        cfg, result.unique, result.new, result.recommended, result.discarded, result.applied
    )
    print(f"[5] Relatorio: {path}  ({len(result.recommended)} recomendadas, {len(result.discarded)} descartadas)")

    if dry_run:
        print("[6] dry-run: e-mail nao enviado.")
        return 0

    print(f"[6] {send_email(cfg, html)}")
    return 0
