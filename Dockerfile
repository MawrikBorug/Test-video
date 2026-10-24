# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
# Optional CA mount is only used by the managed development environment.
# Render builds use the normal public trust store. No CA is baked into layers.
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/system_ca; fi; \
    npm ci --ignore-scripts
COPY . .
ARG RENDER_GIT_COMMIT=unknown
RUN printf '{"sha":"%s"}' "$RENDER_GIT_COMMIT" > source-info.json && \
    SKIP_BUNDLED_FFMPEG=1 npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY web/catalog.json ./web/catalog.json
COPY --from=frontend /app/dist ./dist
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh","-c","exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
