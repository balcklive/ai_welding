# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS frontend-builder
WORKDIR /build

COPY .npmrc package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig*.json tailwind.config.js postcss.config.js eslint.config.js ./
COPY src ./src
RUN npm run build

FROM python:3.12-slim-bookworm AS backend-dependencies
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/
WORKDIR /opt/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev \
    && test -x /opt/backend/.venv/bin/uvicorn

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/opt/backend/.venv/bin:$PATH"
WORKDIR /app

# Keep the original virtualenv path because console-script shebangs point to it.
COPY --from=backend-dependencies /opt/backend/.venv /opt/backend/.venv
COPY backend/app ./app
COPY --from=frontend-builder /build/dist ./dist

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
