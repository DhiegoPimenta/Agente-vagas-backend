from __future__ import annotations

import json
import os
import sys
import time

from .models import Job, Scored
from .util import to_float

_JUNIOR = ("junior", "júnior", "jr", "jr.", "trainee", "estágio", "estagio", "intern", "internship", "aprendiz")
_SENIOR = ("senior", "sênior", "sr", "sr.", "staff", "principal", "specialist", "especialista")
_PLENO = ("pleno", "mid-level", "mid level", "midlevel", "mid-senior", "pl.")
_LEAD = ("tech lead", "team lead", "líder", "lider", "manager", "gerente", "head of", "coordenador", "architect", "arquiteto")
_ENG = ("developer", "engineer", "desenvolvedor", "engenheiro", "software", "programador",
        "full stack", "fullstack", "full-stack", "backend", "back-end", "frontend", "front-end", "sre", "devops")

# Titulos claramente fora do alvo (dev fullstack/front/back): penaliza forte.
_OFF_TARGET_TITLE = (
    "test automation", "qa engineer", "quality engineer", "quality assurance", "sdet",
    "data scientist", "data engineer", "machine learning", "ml engineer", "mlops",
    "security engineer", "security analyst", "cybersecurity", "penetration",
    "embedded", "firmware", "hardware", "fpga", "gnc",
    "salesforce", "sap ", "servicenow", "sharepoint",
    "support engineer", "technical support", "solutions engineer", "sales engineer",
    "data analyst", "business analyst", "bi analyst", "system administrator", "network engineer",
)


def _text(job: Job) -> str:
    return " ".join([job.title, job.company, job.location, job.description, " ".join(job.tags)]).lower()


def heuristic_score(job: Job, cand: dict) -> Scored:
    text = _text(job)
    title = job.title.lower()
    reasons: list[str] = []
    flags: list[str] = []
    score = 40

    principal = [s.lower() for s in cand.get("stack_principal", []) if s]
    secundaria = [s.lower() for s in cand.get("stack_secundaria", []) if s]
    hits_p = sorted({s for s in principal if s in text})
    hits_s = sorted({s for s in secundaria if s in text})
    if hits_p:
        score += min(30, 10 * len(hits_p))
        flags.append("stack_match")
        reasons.append(f"Stack principal citada: {', '.join(hits_p)}")
    else:
        score -= 15
        reasons.append("Nenhuma tecnologia da stack principal citada")
    if hits_s:
        score += min(10, 3 * len(hits_s))
        reasons.append(f"Stack secundaria: {', '.join(hits_s)}")

    if any(k in text for k in _ENG):
        score += 8
    else:
        score -= 20
        reasons.append("Nao parece vaga de engenharia de software")

    off = next((k for k in _OFF_TARGET_TITLE if k in title), None)
    if off and not any(k in title for k in ("full stack", "fullstack", "full-stack", "front", "back")):
        score -= 30
        reasons.append(f"Titulo fora do alvo dev ({off.strip()})")

    aceita = [s.lower() for s in cand.get("aceita_senioridades", ["pleno", "senior"])]
    if any(k in title for k in _JUNIOR):
        score -= 35
        reasons.append("Titulo indica junior/estagio (fora do alvo)")
    elif any(k in title for k in _LEAD):
        score -= 12
        reasons.append("Titulo indica lideranca/arquitetura")
    else:
        sen_ok = ("senior" in aceita and any(k in title for k in _SENIOR)) or (
            "pleno" in aceita and any(k in title for k in _PLENO)
        )
        if sen_ok:
            score += 12
            flags.append("senioridade_ok")
            reasons.append("Senioridade compativel (pleno/senior)")
        elif not any(k in title for k in _SENIOR + _PLENO):
            score += 3  # titulo neutro

    modal = [m.lower() for m in cand.get("modalidade", [])]
    is_remote = job.remote is True or any(
        k in text for k in ("remote", "remoto", "anywhere", "home office", "home-office", "trabalho remoto")
    )
    is_hybrid = any(k in text for k in ("hybrid", "híbrido", "hibrido"))
    if "remoto" in modal and is_remote:
        score += 10
        flags.append("modalidade_ok")
        reasons.append("Remoto")
    elif "hibrido" in modal and is_hybrid:
        score += 6
        flags.append("modalidade_ok")
        reasons.append("Hibrido")
    elif modal and not is_remote and not is_hybrid:
        score -= 6
        reasons.append("Modalidade nao confirmada / possivel presencial")

    locs = [l.lower() for l in cand.get("localizacao_preferida", []) if l]
    if any(l in text for l in locs) or any(k in text for k in ("brazil", "brasil", "latam", "latin america")):
        score += 6
        reasons.append("Localizacao/regiao compativel")
    elif is_remote and any(k in text for k in ("worldwide", "global", "anywhere")):
        score += 3

    minimo = to_float(cand.get("faixa_salarial_min"))
    if job.has_salary:
        flags.append("salario_informado")
        if minimo and job.salary_currency == cand.get("moeda", "BRL"):
            if (job.salary_max or job.salary_min or 0) >= minimo:
                score += 6
                flags.append("faixa_salarial_compativel")
            else:
                score -= 10
                reasons.append("Faixa salarial abaixo do minimo")
    else:
        reasons.append("Sem faixa salarial informada")

    for restr in cand.get("restricoes", []):
        rl = str(restr).lower()
        if ("consultoria" in rl or "body shop" in rl or "alocac" in rl) and any(
            k in text for k in ("consultoria", "consulting", "body shop", "bodyshop", "alocação", "alocacao", "outsourcing")
        ):
            score -= 15
            reasons.append("Possivel consultoria/alocacao (restricao do candidato)")

    score = max(0, min(100, score))
    return Scored(job=job, score=int(round(score)), reasons=reasons, flags=sorted(set(flags)))


# ---------------------------------------------------------------------------
# Score por LLM (opcional)
# ---------------------------------------------------------------------------

def llm_available() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"resposta do LLM sem JSON: {text[:200]!r}")
    return json.loads(text[start : end + 1])


_CLIENT = None


def _client():
    """Cliente anthropic unico, com timeout folgado e retry (CPU do free tier e lento)."""
    global _CLIENT
    if _CLIENT is None:
        import anthropic

        _CLIENT = anthropic.Anthropic(timeout=60.0, max_retries=5)
    return _CLIENT


def _llm_json(model: str, prompt: str, max_tokens: int, system: str | None = None) -> dict:
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    msg = _client().messages.create(**kwargs)
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _extract_json(text)


def llm_score(job: Job, cand: dict, model: str) -> Scored:
    profile = {
        k: cand.get(k)
        for k in (
            "cargo_alvo", "aceita_senioridades", "stack_principal", "stack_secundaria",
            "modalidade", "localizacao_preferida", "faixa_salarial_min", "moeda",
            "resumo_curriculo", "restricoes",
        )
    }
    prompt = (
        "Voce avalia o fit entre uma vaga e o perfil de um candidato.\n"
        'Responda APENAS o objeto JSON, sem texto antes/depois e sem crases: '
        '{"score": <int 0-100>, "reasons": [<str>], "flags": [<str>]}.\n'
        "reasons: no maximo 3 itens, cada um com no maximo 12 palavras.\n"
        "flags validas: stack_match, senioridade_ok, modalidade_ok, faixa_salarial_compativel, salario_informado.\n"
        "Nao invente dados que nao estejam no perfil ou na vaga.\n"
        "Se o perfil nao trouxer resumo de experiencia, avalie o fit apenas pelos cargos-alvo, "
        "stacks e preferencias -- NAO penalize por experiencia desconhecida.\n"
        "Rubrica do score: 70-100 = stack e senioridade batem e a modalidade e compativel; "
        "40-69 = batem em parte; 0-39 = area, stack ou senioridade claramente fora do alvo.\n\n"
        f"PERFIL:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
        "VAGA:\n"
        f"titulo: {job.title}\nempresa: {job.company}\nlocal: {job.location}\nremoto: {job.remote}\n"
        f"salario: {job.salary_min}-{job.salary_max} {job.salary_currency}\n"
        f"descricao: {job.description[:4000]}\n"
    )
    data = _llm_json(model, prompt, max_tokens=1500)
    return Scored(
        job=job,
        score=int(max(0, min(100, int(data.get("score", 0))))),
        reasons=[str(r) for r in data.get("reasons", [])][:6],
        flags=sorted({str(f) for f in data.get("flags", [])}),
    )


def score_job(job: Job, cand: dict, cfg: dict) -> Scored:
    """Score de uma vaga isolada (usado em testes / uso pontual)."""
    return score_all([job], cand, cfg)[0]


def score_all(jobs: list[Job], cand: dict, cfg: dict) -> list[Scored]:
    """
    Duas fases:
      1. heuristica em TODAS as vagas (rapido, sem custo);
      2. se o LLM estiver ativo, refina apenas as mais promissoras
         (heuristica >= llm_min_heuristic), no maximo llm_max_jobs.

    Isso evita ~200 chamadas de LLM por execucao — o LLM entra so onde a
    decisao de recomendar/descartar e de fato apertada.
    """
    sc = cfg.get("scoring", {})
    mode = str(sc.get("mode", "auto")).lower()
    model = sc.get("llm_model", "claude-sonnet-5")
    use_llm = mode == "llm" or (mode == "auto" and llm_available())

    scored = [heuristic_score(job, cand) for job in jobs]
    if not use_llm or not scored:
        return scored

    max_jobs = int(sc.get("llm_max_jobs", 60))
    min_heur = int(sc.get("llm_min_heuristic", 40))
    candidates = sorted(
        (i for i, s in enumerate(scored) if s.score >= min_heur),
        key=lambda i: scored[i].score,
        reverse=True,
    )[:max_jobs]

    refined = 0
    for n, i in enumerate(candidates):
        if n:
            time.sleep(0.4)  # espaca as chamadas pra nao tomar rate limit
        try:
            new = llm_score(jobs[i], cand, model)
            if not new.reasons:
                new.reasons.append("Avaliado por LLM")
            scored[i] = new
            refined += 1
        except Exception as exc:  # rede, parsing, quota... mantem a heuristica (silencioso pro usuario)
            print(f"    [llm_score] {jobs[i].uid}: {exc}", file=sys.stderr)
    print(f"    LLM refinou {refined}/{len(candidates)} vagas (heuristica >= {min_heur})")
    return scored


# ---------------------------------------------------------------------------
# Analise "Saber mais" por vaga (pre-gerada no run diario)
# ---------------------------------------------------------------------------

def _analysis_html(data: dict) -> str:
    import html as _html

    def _ul(items) -> str:
        lis = "".join(f"<li>{_html.escape(str(x))}</li>" for x in (items or [])[:4])
        return f"<ul style='margin:4px 0 8px 18px;padding:0'>{lis}</ul>" if lis else ""

    parts = [f"<p style='margin:6px 0'>{_html.escape(str(data.get('fit', '')))}</p>"]
    for key, label in (
        ("atencao", "Pontos de atencao"),
        ("revisar", "Revisar antes"),
        ("perguntas_recrutador", "Provavel na entrevista"),
    ):
        if data.get(key):
            parts.append(f"<b style='font-size:12px'>{label}</b>{_ul(data.get(key))}")
    return "".join(parts)


def analyze_job(job: Job, cand: dict, model: str) -> str:
    """Gera a analise da vaga como HTML seguro (texto do modelo ja escapado)."""
    profile = {
        k: cand.get(k)
        for k in (
            "cargo_alvo", "aceita_senioridades", "stack_principal",
            "stack_secundaria", "modalidade", "localizacao_preferida", "resumo_curriculo",
        )
    }
    prompt = (
        "Com base no PERFIL e na VAGA, gere uma analise curta em portugues para o "
        "candidato decidir se aplica.\n"
        'Responda APENAS o objeto JSON, sem texto antes/depois e sem crases: '
        '{"fit": <str>, "atencao": [<str>], "revisar": [<str>], "perguntas_recrutador": [<str>]}.\n'
        "fit: 2-3 frases sobre o encaixe. Cada lista: no maximo 4 itens curtos.\n"
        "Se o perfil nao tiver resumo de experiencia, foque em cargos-alvo e stacks; "
        "nao invente experiencia.\n\n"
        f"PERFIL:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
        "VAGA:\n"
        f"titulo: {job.title}\nempresa: {job.company}\nlocal: {job.location}\n"
        f"descricao: {job.description[:4000]}\n"
    )
    return _analysis_html(_llm_json(model, prompt, max_tokens=1100))


def maybe_analyze(recommended: list[Scored], cand: dict, cfg: dict) -> None:
    """
    Preenche s.analysis nas primeiras N recomendadas.

    Independente de scoring.mode: a analise "Saber mais" roda sempre que
    analysis.enabled e houver ANTHROPIC_API_KEY -- mesmo com o ranking em
    heuristica (que e mais rapido e confiavel). So nao roda em mode=heuristic
    se a chave nao existir.
    """
    acfg = cfg.get("analysis", {})
    if not acfg.get("enabled", True) or not llm_available():
        return
    model = cfg.get("scoring", {}).get("llm_model", "claude-sonnet-5")
    limit = int(acfg.get("max_jobs", 15))

    done = 0
    for n, s in enumerate(recommended[:limit]):
        if n:
            time.sleep(0.4)
        try:
            s.analysis = analyze_job(s.job, cand, model)
            done += 1
        except Exception as exc:  # nao derruba o run nem polui o card do usuario
            print(f"    [analyze] {s.job.uid}: {exc}", file=sys.stderr)
    print(f"    analise pre-gerada em {done}/{min(limit, len(recommended))} vagas")
