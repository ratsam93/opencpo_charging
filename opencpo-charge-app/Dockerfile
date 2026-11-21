FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

RUN useradd --system --no-create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8003

ENV APP_HOST=0.0.0.0
ENV PORT=8003

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import os,urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8003'), timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8003}"]
