FROM python:3.12-slim

WORKDIR /solution

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"
COPY text2sql-ai ./text2sql-ai

WORKDIR /solution/text2sql-ai

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
