FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /bin/


WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

RUN mkdir -p /app/data

ENV PATH="/app/.venv/bin:$PATH"

VOLUME ["/app/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
