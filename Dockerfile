# syntax=docker/dockerfile:1.7
# One image for MatchMind: the built web app served by the API (REST, WebSocket, agents, match-intel MCP).

# ---------------------------------------------------------------- web build
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MM_HOST=0.0.0.0 \
    MM_PORT=8000
WORKDIR /app
RUN useradd --create-home --uid 10001 matchmind

# dependencies first, so code changes don't reinstall them
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
        > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# the code stays in place (editable install): it finds its calibration, models and web build by relative path
COPY README.md LICENSE ./
COPY calibration/params_wyscout_pl1718.json calibration/
COPY schema schema
COPY contracts contracts
COPY generator generator
COPY intel intel
COPY mcp_server mcp_server
COPY agents agents
COPY api api
COPY --from=web /web/dist web/dist
RUN pip install --no-deps -e . && chown -R matchmind /app

USER matchmind
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "api"]
