from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from ..models import Job
from ..util import parse_iso, strip_html, to_float
from .base import TIMEOUT, USER_AGENT, Source

API = "https://remoteok.com/api"


class RemoteOK(Source):
    name = "remoteok"

    def fetch(self, lookback_hours: int, limit: int) -> list[Job]:
        resp = requests.get(
            API,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        jobs: list[Job] = []
        for item in data:
            if not isinstance(item, dict) or "id" not in item or item.get("legal"):
                continue
            posted = parse_iso(item.get("date") or item.get("epoch"))
            if posted and posted < cutoff:
                continue
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(item.get("id")),
                    title=item.get("position") or item.get("title") or "",
                    company=item.get("company") or "",
                    location=item.get("location") or "Remoto",
                    url=item.get("url") or item.get("apply_url") or "",
                    description=strip_html(item.get("description") or ""),
                    remote=True,
                    salary_min=to_float(item.get("salary_min")),
                    salary_max=to_float(item.get("salary_max")),
                    salary_currency="USD",
                    posted_at=posted,
                    tags=[t for t in (item.get("tags") or []) if isinstance(t, str)],
                    raw=item,
                )
            )
            if len(jobs) >= limit:
                break
        return jobs
