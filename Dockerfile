# syntax=docker/dockerfile:1
# slxt share – Frontend (Vite) + API (FastAPI). Läuft als Nicht-root, Dateisystem nur lesbar außer /daten.

FROM --platform=$BUILDPLATFORM node:22.23.5-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY web/ ./
RUN npm run build

FROM python:3.14.10-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS basis
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --root-user-action=ignore -r requirements.txt
COPY app ./app
COPY --from=web /web/dist ./web/dist

# Tests: docker build --target test -t share:test . && docker run --rm share:test
FROM basis AS test
COPY requirements-test.txt .
RUN pip install --root-user-action=ignore -r requirements-test.txt
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]

FROM basis AS laufzeit
# pip samt mitgelieferter Bibliotheken wird zur Laufzeit nicht gebraucht
RUN python -m pip uninstall -y --root-user-action=ignore pip setuptools 2>/dev/null; rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip*
ENV SHARE_DATEN=/daten SHARE_WEB=/srv/web/dist
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/gesund', timeout=4).status == 200 else 1)"]
# Ein Prozess: Begrenzer + Hintergrund-Aufräumen liegen im Speicher dieses Prozesses
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-server-header", "--timeout-keep-alive", "15"]
