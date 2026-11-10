FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 recall
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# SEMANTIC=1 adds the local embedding model (about 420 MB more) and bakes it into the image,
# so the read-only container never downloads anything at runtime.
ARG SEMANTIC=0
ENV RECALL_MODEL_CACHE=/app/models
RUN if [ "$SEMANTIC" = "1" ]; then \
      uv sync --frozen --no-dev --extra semantic \
      && RECALL_EMBEDDER=semantic .venv/bin/python -c "from recall_kit.embed import FastEmbedEmbedder; FastEmbedEmbedder().embed('warm up')"; \
    else uv sync --frozen --no-dev; fi \
    && mkdir -p /data /app/models && chown -R recall /app /data

USER recall
ENV RECALL_HOME=/data/store \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz')"
CMD ["rk", "serve", "--http", "--host", "0.0.0.0", "--port", "8765"]
