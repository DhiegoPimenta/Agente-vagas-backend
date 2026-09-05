from __future__ import annotations

from .models import Job


def classify_form(job: Job) -> str:
    """
    Classifica a complexidade do formulario de candidatura.

    Sem abrir a pagina do ATS nao da para inspecionar o formulario com seguranca,
    entao aplicamos o fail-safe da spec: na duvida, "complexo".

    Auto-apply esta DESLIGADO nesta versao, entao isto sempre devolve "complexo".
    Quando/se o auto-apply for implementado, este e o ponto de extensao:
      - abrir a URL (respeitando robots.txt / ToS da fonte)
      - contar campos obrigatorios e perguntas abertas
      - "simples" apenas se: contato + upload de curriculo + no maximo 1 pergunta objetiva
    """
    return "complexo"
