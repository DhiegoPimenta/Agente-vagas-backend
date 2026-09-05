from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Job:
    source: str
    external_id: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    remote: Optional[bool] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    posted_at: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.external_id}"

    @property
    def has_salary(self) -> bool:
        return bool(self.salary_min or self.salary_max)


@dataclass
class Scored:
    job: Job
    score: int
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    form_complexity: str = "complexo"
    route: str = "descartada"  # recomendada | descartada | auto_apply
    analysis: str = ""  # HTML seguro com a analise pre-gerada (so nas recomendadas exibidas)
