from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from ..models import Job
from ..util import parse_iso, strip_html
from .base import TIMEOUT, USER_AGENT, Source

API = "https://remotive.com/api/remote-jobs"


class Remotive(Source):
    name = "remotive"

    def fetch(self, lookback_hours: int, limit: int) -> list[Job]:
        params = {
            "category": self.options.get("category", "software-dev"),
            "limit": min(limit, 200),
        }
        resp = requests.get(
            API,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json().get("jobs") or []
        # Remotive lista "vagas remotas abertas agora" (nao um feed por data);
        # janela maior por padrao pra nao filtrar tudo.
        lb = int(self.options.get("lookback_hours", max(lookback_hours, 336)))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lb)

        jobs: list[Job] = []
        for item in rows:
            posted = parse_iso(item.get("publication_date"))
            if posted and posted < cutoff:
                continue
            # candidate_required_location: "Worldwide", "USA Only", "Brazil", "EMEA"...
            location = (item.get("candidate_required_location") or "Remote").strip() or "Remote"
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(item.get("id")),
                    title=item.get("title") or "",
                    company=item.get("company_name") or "",
                    location=location,
                    url=item.get("url") or "",
                    description=strip_html(item.get("description") or ""),
                    remote=True,
                    salary_currency="",
                    posted_at=posted,
                    tags=[t for t in (item.get("tags") or []) if isinstance(t, str)],
                    raw=item,
                )
            )
            if len(jobs) >= limit:
                break
        return jobs
