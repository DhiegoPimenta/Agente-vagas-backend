from __future__ import annotations

import abc

from ..models import Job

USER_AGENT = "agente-vagas/0.1 (uso pessoal; curadoria de vagas)"
TIMEOUT = 30


class Source(abc.ABC):
    name: str = "base"

    def __init__(self, options: dict | None = None):
        self.options = options or {}

    @abc.abstractmethod
    def fetch(self, lookback_hours: int, limit: int) -> list[Job]:
        """Retorna vagas publicadas nas ultimas `lookback_hours`, no maximo `limit`."""
        raise NotImplementedError
