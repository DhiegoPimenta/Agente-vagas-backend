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
    "embedded", "firmware", "hardware", "fpga", "gnc", "radio", "data link",
    "salesforce", "sap ", "servicenow", "sharepoint",
    "support engineer", "technical support", "solutions engineer", "sales engineer",
    "data analyst", "business analyst", "bi analyst", "system administrator", "network engineer",
    "systems engineer", "business development", "technical writer", "developer relations",
    "developer advocate", "recruiter", "product manager", "project manager", "scrum master",
    "ux designer", "ui designer", "graphic designer",
    "copywriter", "content writer", "content manager", "seo specialist", "marketing manager",
    "account executive", "customer success", "community manager", "virtual assistant",
)

_BR_HINTS = ("brazil", "brasil", "latam", "latin america", "são paulo", "sao paulo")
_GLOBAL_HINTS = ("worldwide", "work from anywhere", "remote anywhere", "anywhere in the world",
                 "fully remote, global", "global remote", "remote - global", "remote, global")
# Remoto mas restrito a outra regiao/pais (Tiago nao consegue pegar do Brasil).
_LOCK_HINTS = (
    "us only", "u.s. only", "usa only", "united states only", "us-based only", "must be based in the us",
    "must reside in the united states", "authorized to work in the united states", "us work authorization",
    "eu only", "europe only", "eu-based only", "must be based in europe", "within the eu",
    "uk only", "must be based in the uk", "right to work in the uk",
    "must be located in", "must be based in germany", "based in canada", "canada only",
)


def _text(job: Job) -> str:
    return " ".join([job.title, job.company, job.location, job.description, " ".join(job.tags)]).lower()


_PLACE_NOISE = ("remote", "remoto", "anywhere", "worldwide", "global", "home office", "homeoffice",
                "home-office", "hybrid", "híbrido", "hibrido", "office", "onsite", "on-site", "job",
                "full-time", "part-time", "position", " - ", "/", ",", ";", "(", ")", "|")


def _names_place(location: str) -> bool:
    """True se o campo 'local' aponta uma cidade/pais concreto (nao so 'Remote')."""
    s = (location or "").lower()
    for w in _PLACE_NOISE:
        s = s.replace(w, " ")
    return len(s.split()) > 0 and len("".join(s.split())) >= 3


def heuristic_score(job: Job, cand: dict) -> Scored:
    text = _text(job)
    title = job.title.lower()
    reasons: list[str] = []
    flags: list[str] = []
    region = "br"
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
    if off and not any(
        k in title for k in ("full stack", "fullstack", "full-stack", "front", "back", "software developer", "software engineer")
    ):
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

    is_remote = job.remote is True or any(
        k in text for k in ("remote", "remoto", "anywhere", "home office", "home-office", "homeoffice", "trabalho remoto")
    )
    is_hybrid = any(k in text for k in ("hybrid", "híbrido", "hibrido"))
    worldwide = any(k in text for k in _GLOBAL_HINTS)
    region_locked = is_remote and any(k in text for k in _LOCK_HINTS) and not worldwide

    # A regiao vem sobretudo do LOCAL da vaga (mais confiavel que palavra na descricao):
    # muitas vagas europeias vem marcadas "remote" mas o local diz Londres/Berlim ->
    # na pratica sao remoto regional, que Tiago nao consegue pegar do Brasil.
    loc = job.location.lower()
    loc_br = any(k in loc for k in _BR_HINTS)
    loc_global = any(k in loc for k in ("worldwide", "anywhere", "global", "fully remote", "no location"))
    place = _names_place(job.location) and not loc_br and not loc_global

    if loc_br and (is_remote or is_hybrid):
        score += 12
        flags.append("modalidade_ok")
        region = "br"
        reasons.append("Remoto/hibrido no Brasil")
    elif loc_br:
        score += 4
        region = "br"
        reasons.append("Presencial no Brasil")
    elif loc_global and not region_locked:
        # o LOCAL diz worldwide/anywhere -> vale mesmo que cite outra cidade
        score += 12
        flags.append("modalidade_ok")
        region = "global"
        reasons.append("Remoto worldwide")
    elif place:
        # local aponta cidade/pais estrangeiro -> na pratica exige presenca ou e
        # remoto regional; Tiago nao consegue pegar do Brasil.
        score -= 18
        region = "exterior"
        reasons.append(f"Vaga atrelada a {job.location.strip()[:40]}")
    elif region_locked:
        score -= 18
        region = "exterior"
        reasons.append("Remoto travado em outro pais/regiao")
    elif is_remote:
        score += 12 if worldwide else 8
        flags.append("modalidade_ok")
        region = "global"
        reasons.append("Remoto worldwide" if worldwide else "Remoto (sem local fixo)")
    else:
        score -= 22
        region = "exterior"
        reasons.append("Presencial no exterior (fora do alvo)")

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
    return Scored(
        job=job, score=int(round(score)), reasons=reasons, flags=sorted(set(flags)), region=region
    )


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
    O RANKING e sempre heuristico (rapido, estavel, previsivel).

    Se o LLM estiver ativo, ele so ENRIQUECE as razoes das vagas melhor
    ranqueadas (troca os bullets templados por uma leitura do modelo) e
    ajusta o score levemente (blend 70/30) — nunca o substitui, pra uma
    vaga bem ranqueada nao afundar so porque o LLM foi mais rigoroso ou
    porque a chamada falhou.
    """
    sc = cfg.get("scoring", {})
    mode = str(sc.get("mode", "auto")).lower()
    model = sc.get("llm_model", "claude-sonnet-5")
    use_llm = mode in ("llm", "auto") and llm_available()

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
            llm = llm_score(jobs[i], cand, model)
            if llm.reasons:
                scored[i].reasons = llm.reasons
            scored[i].flags = sorted(set(scored[i].flags) | set(llm.flags))
            scored[i].score = max(
                0, min(100, round(0.7 * scored[i].score + 0.3 * llm.score))
            )
            refined += 1
        except Exception as exc:  # rede, parsing, quota... mantem a heuristica pura
            print(f"    [llm_score] {jobs[i].uid}: {exc}", file=sys.stderr)
    print(f"    LLM enriqueceu {refined}/{len(candidates)} vagas do topo")
    return scored


# ---------------------------------------------------------------------------
# Analise "Saber mais" por vaga (pre-gerada no run diario)
# ---------------------------------------------------------------------------

def _analysis_html(data: dict) -> str:
    import html as _html

    def _ul(items) -> str:
        lis = "".join(f"<li>{_html.escape(str(x))}</li>" for x in (items or [])[:4])
        return f"<ul style='margin:4px 0 8px 18px;padding:0'>{lis}</ul>" if lis else ""

    parts: list[str] = []

    empresa = str(data.get("empresa", "")).strip()
    if empresa:
        parts.append(
            "<b style='font-size:12px'>Sobre a empresa</b>"
            f"<p style='margin:4px 0 8px'>{_html.escape(empresa)} "
            "<span style='color:#999'>(conhecimento geral do modelo, pode estar desatualizado)</span></p>"
        )

    fit = str(data.get("fit", "")).strip()
    if fit:
        parts.append(
            f"<b style='font-size:12px'>Encaixe</b><p style='margin:4px 0 8px'>{_html.escape(fit)}</p>"
        )

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
        "Com base no PERFIL, na VAGA e no seu conhecimento geral, gere uma analise "
        "curta em portugues para o candidato decidir se aplica.\n"
        'Responda APENAS o objeto JSON, sem texto antes/depois e sem crases: '
        '{"empresa": <str>, "fit": <str>, "atencao": [<str>], "revisar": [<str>], '
        '"perguntas_recrutador": [<str>]}.\n'
        "empresa: 2-4 frases sobre a empresa citada na VAGA -- setor, porte e o que se "
        "sabe sobre ser um bom lugar para trabalhar (pontos fortes e fracos conhecidos: "
        "cultura, estabilidade, reputacao, remuneracao). Se for pouco conhecida ou voce "
        "nao tiver informacao confiavel, diga isso claramente. Use seu conhecimento de "
        "treino (pode estar desatualizado); NAO invente fatos, notas nem numeros.\n"
        "fit: 2-3 frases sobre o encaixe. Cada lista: no maximo 4 itens curtos.\n"
        "Se o perfil nao tiver resumo de experiencia, foque em cargos-alvo e stacks; "
        "nao invente experiencia.\n"
        "O candidato mora no Brasil, quer trabalho REMOTO (do Brasil ou worldwide) e "
        "tem curriculo em portugues E em ingles. Em 'atencao', diga qual curriculo usar "
        "(PT ou EN, pelo idioma do anuncio/pais da empresa) e, se a vaga exigir presenca "
        "no exterior ou for remota travada em outro pais, avise que provavelmente nao da.\n\n"
        f"PERFIL:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
        "VAGA:\n"
        f"titulo: {job.title}\nempresa: {job.company}\nlocal: {job.location}\n"
        f"descricao: {job.description[:4000]}\n"
    )
    return _analysis_html(_llm_json(model, prompt, max_tokens=1400))


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
