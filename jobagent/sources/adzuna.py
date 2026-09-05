from __future__ import annotations

import requests

from ..models import Job
from ..util import parse_iso, strip_html, to_float
from .base import TIMEOUT, USER_AGENT, Source

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class Adzuna(Source):
    name = "adzuna"

    def fetch(self, lookback_hours: int, limit: int) -> list[Job]:
        app_id = self.options.get("app_id")
        app_key = self.options.get("app_key")
        if not app_id or not app_key:
            raise RuntimeError(
                "Adzuna habilitada mas sem credenciais. "
                "Preencha sources.adzuna.app_id/app_key ou use ADZUNA_APP_ID / ADZUNA_APP_KEY."
            )
        country = self.options.get("country", "br")
        rpp = int(self.options.get("results_per_page", 50))
        max_pages = int(self.options.get("max_pages", 2))
        max_days = max(1, round(lookback_hours / 24))
        queries = self.options.get("queries") or ["software engineer"]

        seen: set[str] = set()
        jobs: list[Job] = []
        for query in queries:
            for page in range(1, max_pages + 1):
                resp = requests.get(
                    BASE.format(country=country, page=page),
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "results_per_page": rpp,
                        "what": query,
                        "max_days_old": max_days,
                        "content-type": "application/json",
                    },
                    headers={"User-Agent": USER_AGENT},
                    timeout=TIMEOUT,
                )
                if resp.status_code in (401, 403):
                    raise RuntimeError(f"Adzuna {resp.status_code}: verifique as credenciais.")
                resp.raise_for_status()
                results = resp.json().get("results") or []
                if not results:
                    break
                for item in results:
                    ext = str(item.get("id"))
                    if ext in seen:
                        continue
                    seen.add(ext)
                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=ext,
                            title=item.get("title") or "",
                            company=(item.get("company") or {}).get("display_name") or "",
                            location=(item.get("location") or {}).get("display_name") or "",
                            url=item.get("redirect_url") or "",
                            description=strip_html(item.get("description") or ""),
                            remote=None,
                            salary_min=to_float(item.get("salary_min")),
                            salary_max=to_float(item.get("salary_max")),
                            salary_currency="BRL" if country == "br" else country.upper(),
                            posted_at=parse_iso(item.get("created")),
                            raw=item,
                        )
                    )
                    if len(jobs) >= limit:
                        return jobs
        return jobs
