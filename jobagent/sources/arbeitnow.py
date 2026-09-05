from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from ..models import Job
from ..util import parse_iso, strip_html
from .base import TIMEOUT, USER_AGENT, Source

API = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 5


class Arbeitnow(Source):
    name = "arbeitnow"

    def fetch(self, lookback_hours: int, limit: int) -> list[Job]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        jobs: list[Job] = []
        page = 1
        while len(jobs) < limit and page <= MAX_PAGES:
            resp = requests.get(
                API,
                params={"page": page},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            rows = resp.json().get("data") or []
            if not rows:
                break

            older_seen = False
            for item in rows:
                posted = parse_iso(item.get("created_at"))
                if posted and posted < cutoff:
                    older_seen = True
                    continue
                jobs.append(
                    Job(
                        source=self.name,
                        external_id=str(item.get("slug")),
                        title=item.get("title") or "",
                        company=item.get("company_name") or "",
                        location=item.get("location") or "",
                        url=item.get("url") or "",
                        description=strip_html(item.get("description") or ""),
                        remote=bool(item.get("remote")),
                        posted_at=posted,
                        tags=[
                            *(item.get("tags") or []),
                            *(item.get("job_types") or []),
                        ],
                        raw=item,
                    )
                )
                if len(jobs) >= limit:
                    break

            # Feed vem ordenado por mais recente; se ja apareceram vagas velhas, para.
            if older_seen:
                break
            page += 1
        return jobs
