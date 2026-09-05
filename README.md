# Agente de vagas — backend

API + serviço que roda a curadoria de vagas do Tiago em memória e expõe:

| rota | o que faz |
|---|---|
| `GET /` | o relatório HTML completo (com o widget de "Perguntar sobre a vaga") |
| `GET /healthz` | status + resumo da última execução (health check do Render) |
| `GET /api/jobs?offset=0&limit=10` | vagas recomendadas em JSON (paginado) |
| `GET /api/jobs/{uid}` | uma vaga (com descrição e análise) |
| `POST /api/chat` | `{uid, question, history?}` → `{answer}` — chat com LLM sobre a vaga |
| `POST /api/run` | header `X-Run-Token: <RUN_TOKEN>` → força uma nova execução |

O pipeline (coleta → score → análise) está em `jobagent/` — mesmo código do
repo [`Agente-vagas`](https://github.com/DhiegoPimenta/Agente-vagas). Aqui ele roda
**sem SQLite** (o Render free não tem disco fixo): tudo fica em memória e é
regravado num cache em `/tmp` pra sobreviver a reinícios rápidos.

## Deploy no Render (Blueprint)

1. No Render: **New + → Blueprint** e escolha o repo `Agente-vagas-backend`.
   Ele lê o `render.yaml` e cria o serviço `agente-vagas-backend` (plano free).
2. O Render vai pedir o valor de **`ANTHROPIC_API_KEY`** (marcado `sync:false`).
   Cole uma **chave nova** da Anthropic. `RUN_TOKEN` ele gera sozinho.
3. Deploy. Quando ficar verde, a URL é algo como
   `https://agente-vagas-backend.onrender.com`.
4. Primeira abertura do dia é lenta (~50s): o free tier dorme e o serviço ainda
   roda o pipeline no startup. Depois fica rápido.

### Variáveis de ambiente

| var | padrão | pra quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **obrigatória** pro chat e pro score/análise por LLM |
| `SCORING_MODE` | `auto` | `heuristic` zera o custo de LLM no ranking (o chat continua com LLM) |
| `REFRESH_HOURS` | `12` | de quanto em quanto tempo o pipeline roda de novo |
| `RUN_TOKEN` | (gerado) | protege `POST /api/run` |
| `CHAT_DAILY_LIMIT` | `200` | teto de perguntas ao LLM por dia (trava de custo) |
| `CHAT_PER_IP_HOUR` | `20` | teto por IP por hora |
| `CHAT_MODEL` | = `scoring.llm_model` | modelo usado no chat |
| `CORS_ORIGINS` | `*` | origens liberadas (ex: `https://dhiegopimenta.github.io`) |

## Rodar local

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...        # ou $env:ANTHROPIC_API_KEY no PowerShell
uvicorn webapp:app --reload
```

Abre em http://127.0.0.1:8000 . Sem a chave, o ranking cai na heurística e o
chat responde erro 502.

## Custo (ordem de grandeza)

Por execução do pipeline: ~10–15 chamadas de score + ~15 de análise. Com
`REFRESH_HOURS=12` são ~2 execuções/dia + eventuais no cold start. O chat é
limitado por `CHAT_DAILY_LIMIT`. Para cortar tudo menos o chat:
`SCORING_MODE=heuristic` e `analysis.enabled: false` no `config.example.yaml`.

## Segurança

- A chave da Anthropic fica **só** como env var no Render, nunca no repo.
- `/api/chat` é público (o frontend é estático). As travas são
  `CHAT_DAILY_LIMIT` + `CHAT_PER_IP_HOUR` + `max_tokens=500` + prompt preso ao
  contexto da vaga. Ajuste os limites se precisar.
- LinkedIn e Indeed continuam bloqueados no código do pipeline.

## Frontend

O `GET /` já entrega tudo. Se quiser uma página no GitHub Pages consumindo esta
API: `fetch(BACKEND_URL + "/api/jobs")` para listar e
`fetch(BACKEND_URL + "/api/chat", {method:"POST", ...})` para o chat.
