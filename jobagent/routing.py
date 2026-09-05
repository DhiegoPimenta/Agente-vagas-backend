from __future__ import annotations

from .models import Scored


def route(scored: Scored, cfg: dict) -> Scored:
    sc = cfg.get("scoring", {})
    safety = cfg.get("safety", {})
    min_recommend = int(sc.get("min_score_recommend", 55))
    auto_threshold = int(sc.get("auto_apply_threshold", 90))
    auto_enabled = bool(safety.get("auto_apply_enabled", False))

    if auto_enabled and scored.form_complexity == "simples" and scored.score >= auto_threshold:
        scored.route = "auto_apply"
    elif scored.score >= min_recommend:
        scored.route = "recomendada"
    else:
        scored.route = "descartada"
    return scored
