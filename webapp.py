"""Backend do agente de vagas (FastAPI).

- roda o pipeline em memoria (sem SQLite: o Render free nao tem disco fixo)
  no startup e a cada REFRESH_HOURS;
- serve o relatorio HTML em `/` (com o widget de chat por vaga);
- expoe /api/jobs e /api/chat pro frontend estatico (GitHub Pages).

Variaveis de ambiente (defina no painel do Render, nunca no codigo):
  ANTHROPIC_API_KEY   obrigatoria pro chat e pro score/analise por LLM
  SCORING_MODE        auto (padrao) | heuristic | llm
  REFRESH_HOURS       intervalo entre execucoes do pipeline (padrao 12)
  RUN_TOKEN           protege POST /api/run (o Render pode gerar sozinho)
  CHAT_DAILY_LIMIT    teto de perguntas ao LLM por dia (padrao 200)
  CHAT_PER_IP_HOUR    teto de perguntas por IP por hora (padrao 20)
  CHAT_MODEL          modelo do chat (padrao = scoring.llm_model do config)
  CORS_ORIGINS        origens liberadas, separadas por virgula (padrao *)
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from jobagent.config import load_config
from jobagent.pipeline import build_results
from jobagent.report import build_report

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")
EXAMPLE_PATH = "config.example.yaml"
STATE_FILE = Path(os.getenv("STATE_FILE", "/tmp/agente_vagas_state.json"))
REFRESH_HOURS = float(os.getenv("REFRESH_HOURS", "12"))
RUN_TOKEN = os.getenv("RUN_TOKEN", "")
CHAT_DAILY_LIMIT = int(os.getenv("CHAT_DAILY_LIMIT", "200"))
CHAT_PER_IP_HOUR = int(os.getenv("CHAT_PER_IP_HOUR", "20"))
CHAT_MODEL = os.getenv("CHAT_MODEL", "")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(title="Agente de Vagas - backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.Lock()
_STATE: dict = {"generated_at": None, "html": "", "jobs": [], "summary": {}}
_chat_calls = {"date": "", "count": 0}
_ip_hits: dict[str, list[float]] = {}


# --------------------------------------------------------------------------- #
# pipeline em memoria
# --------------------------------------------------------------------------- #
def _cfg() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        try:
            path.write_text(Path(EXAMPLE_PATH).read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            return load_config(EXAMPLE_PATH)
    return load_config(CONFIG_PATH)


def _job_dict(scored) -> dict:
    j = scored.job
    salary = ""
    if j.has_salary:
        salary = f"{j.salary_min or '?'}-{j.salary_max or '?'} {j.salary_currency}".strip()
    return {
        "uid": j.uid,
        "title": j.title,
        "company": j.company,
        "location": j.location,
        "url": j.url,
        "source": j.source,
        "score": scored.score,
        "salary": salary,
        "reasons": scored.reasons,
        "analysis_html": scored.analysis,
        "description": j.description[:6000],
    }


def _save_state() -> None:
    try:
        STATE_FILE.write_text(json.dumps(_STATE, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_state() -> None:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if data.get("generated_at"):
            _STATE.update(data)
            print(f"[state] carregado de {STATE_FILE} ({data['generated_at']})")
    except (OSError, ValueError):
        pass


def _fresh_enough() -> bool:
    if not _STATE["generated_at"]:
        return False
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(_STATE["generated_at"])).total_seconds()
    return age < REFRESH_HOURS * 3600


def refresh(force: bool = False) -> None:
    with _lock:
        if not force and _fresh_enough():
            return
        try:
            cfg = _cfg()
            result = build_results(cfg, use_store=False)
            html, _ = build_report(
                cfg, result.unique, result.new, result.recommended,
                result.discarded, result.applied,
                write_files=False, chat_api="",
            )
            _STATE.update(
                generated_at=result.generated_at.isoformat(),
                html=html,
                jobs=[_job_dict(s) for s in result.recommended],
                summary={
                    "collected": result.collected,
                    "unique": result.unique,
                    "recommended": len(result.recommended),
                    "discarded": len(result.discarded),
                },
            )
            _save_state()
            print(f"[refresh] ok - {_STATE['summary']}")
        except Exception as exc:  # nao derruba o servico
            print(f"[refresh] ERRO - {exc}")


@app.on_event("startup")
def _startup() -> None:
    _load_state()
    threading.Thread(target=refresh, kwargs={"force": not _fresh_enough()}, daemon=True).start()
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(lambda: refresh(force=True), "interval", hours=REFRESH_HOURS, id="refresh")
    sched.start()


# --------------------------------------------------------------------------- #
# rotas
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not _STATE["html"]:
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:24px'>Preparando as vagas... "
            "recarregue em ~30s.</p>",
            status_code=503,
        )
    return HTMLResponse(_STATE["html"])


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "generated_at": _STATE["generated_at"], **_STATE["summary"]}


@app.get("/api/jobs")
def api_jobs(offset: int = 0, limit: int = 10) -> dict:
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    jobs = _STATE["jobs"]
    return {
        "generated_at": _STATE["generated_at"],
        "total": len(jobs),
        "items": jobs[offset : offset + limit],
        "summary": _STATE["summary"],
    }


@app.get("/api/jobs/{uid}")
def api_job(uid: str) -> dict:
    for j in _STATE["jobs"]:
        if j["uid"] == uid:
            return j
    raise HTTPException(404, "vaga nao encontrada nesta execucao")


@app.post("/api/run")
def api_run(x_run_token: str = Header("")) -> dict:
    if not RUN_TOKEN or x_run_token != RUN_TOKEN:
        raise HTTPException(401, "token invalido")
    threading.Thread(target=refresh, kwargs={"force": True}, daemon=True).start()
    return {"started": True}


class ChatIn(BaseModel):
    uid: str
    question: str
    history: list[dict] = []


@app.post("/api/chat")
def api_chat(body: ChatIn, request: Request) -> dict:
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(400, "pergunta vazia")
    if len(question) > 600:
        raise HTTPException(400, "pergunta muito longa (max 600 caracteres)")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _lock:
        if _chat_calls["date"] != today:
            _chat_calls.update(date=today, count=0)
        if _chat_calls["count"] >= CHAT_DAILY_LIMIT:
            raise HTTPException(429, "limite diario de perguntas atingido, tente amanha")
        _chat_calls["count"] += 1

    ip = request.client.host if request.client else "?"
    now = time.time()
    hits = [t for t in _ip_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= CHAT_PER_IP_HOUR:
        raise HTTPException(429, "muitas perguntas seguidas, aguarde alguns minutos")
    hits.append(now)
    _ip_hits[ip] = hits

    job = next((j for j in _STATE["jobs"] if j["uid"] == body.uid), None)
    if job is None:
        raise HTTPException(404, "vaga nao encontrada nesta execucao")

    try:
        return {"answer": _ask_llm(job, question, body.history[-6:])}
    except Exception as exc:
        raise HTTPException(502, f"o assistente falhou: {exc}")


def _ask_llm(job: dict, question: str, history: list[dict]) -> str:
    import anthropic

    cfg = _cfg()
    model = CHAT_MODEL or cfg.get("scoring", {}).get("llm_model", "claude-sonnet-5")
    cand = cfg.get("candidate", {})
    profile = {
        k: cand.get(k)
        for k in (
            "cargo_alvo", "aceita_senioridades", "stack_principal", "stack_secundaria",
            "modalidade", "localizacao_preferida", "faixa_salarial_min", "moeda", "resumo_curriculo",
        )
    }
    system = (
        "Voce ajuda o candidato a entender ESTA vaga e decidir se aplica. Responda em "
        "portugues, objetivo. Use a descricao da vaga e o perfil abaixo. Sobre a EMPRESA "
        "(se e boa de trabalhar, cultura, estabilidade, reputacao) voce PODE usar seu "
        "conhecimento geral, deixando claro que pode estar desatualizado e sem inventar "
        "notas ou numeros; se nao souber, diga. Para perguntas fora do contexto desta "
        "vaga/empresa, diga que so fala sobre esta vaga. Nao invente requisitos.\n\n"
        f"VAGA:\ntitulo: {job['title']}\nempresa: {job['company']}\nlocal: {job['location']}\n"
        f"salario: {job.get('salary') or 'nao informado'}\nlink: {job['url']}\n"
        f"descricao:\n{job.get('description', '')[:6000]}\n\n"
        f"PERFIL DO CANDIDATO:\n{json.dumps(profile, ensure_ascii=False, indent=2)}"
    )

    clean: list[dict] = []
    for msg in history:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        text = str(msg.get("content", ""))[:2000].strip()
        if not text:
            continue
        if not clean and role != "user":
            continue
        if clean and clean[-1]["role"] == role:
            clean[-1]["content"] += "\n" + text
            continue
        clean.append({"role": role, "content": text})
    if clean and clean[-1]["role"] == "user":
        clean.pop()
    messages = clean + [{"role": "user", "content": question}]

    client = anthropic.Anthropic(timeout=30.0, max_retries=1)
    reply = client.messages.create(model=model, max_tokens=500, system=system, messages=messages)
    return "".join(b.text for b in reply.content if getattr(b, "type", "") == "text").strip()
