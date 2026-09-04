FROM python:3.12-slim AS base

WORKDIR /solution

COPY pyproject.toml ./
COPY text2sql-ai ./text2sql-ai

RUN pip install --no-cache-dir -e ".[dev]"

WORKDIR /solution/text2sql-ai

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
