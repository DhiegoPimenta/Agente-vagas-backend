from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from ..models import Job
from ..util import parse_iso, strip_html
from .base import TIMEOUT, Source

BASE = "https://weworkremotely.com/categories/{cat}.rss"
DEFAULT_CATS = (
    "remote-full-stack-programming-jobs",
    "remote-back-end-programming-jobs",
    "remote-front-end-programming-jobs",
)
# WWR bloqueia User-Agent "de robo"; usa um de navegador.
_UA = "Mozilla/5.0 (compatible; agente-vagas/0.1; curadoria pessoal de vagas)"


class WeWorkRemotely(Source):
    name = "weworkremotely"

    def fetch(self, lookback_hours: int, limit: int) -> list[Job]:
        cats = self.options.get("categories") or list(DEFAULT_CATS)
        lb = int(self.options.get("lookback_hours", max(lookback_hours, 168)))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lb)
        seen: set[str] = set()
        jobs: list[Job] = []

        for cat in cats:
            try:
                resp = requests.get(
                    BASE.format(cat=cat), headers={"User-Agent": _UA}, timeout=TIMEOUT
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except (requests.RequestException, ET.ParseError):
                continue

            for it in root.iterfind(".//item"):
                link = (it.findtext("link") or "").strip()
                if not link or link in seen:
                    continue
                seen.add(link)

                posted = parse_iso(it.findtext("pubDate"))
                if posted and posted < cutoff:
                    continue

                raw_title = (it.findtext("title") or "").strip()
                company, sep, role = raw_title.partition(":")
                if sep:
                    company, title = company.strip(), role.strip()
                else:
                    company, title = "", raw_title
                region = (it.findtext("region") or "").strip()

                jobs.append(
                    Job(
                        source=self.name,
                        external_id=link.rstrip("/").split("/")[-1] or link,
                        title=title,
                        company=company,
                        location=region or "Remote",
                        url=link,
                        description=strip_html(it.findtext("description") or ""),
                        remote=True,
                        posted_at=posted,
                        raw={"title": raw_title, "region": region},
                    )
                )
                if len(jobs) >= limit:
                    return jobs
        return jobs
