# ─── Build stage ─────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime stage ───────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY . .

ENV HOST=0.0.0.0
ENV FARM_UI_PORT=8087
ENV OCPP16_URL=ws://localhost:9100/ocpp
ENV OCPP201_URL=ws://localhost:9201/ocpp

EXPOSE 8087

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % (os.environ.get('FARM_UI_PORT') or os.environ.get('PORT') or '8087'), timeout=3)" || exit 1

ENTRYPOINT ["python", "-u", "control.py"]
