# InternProMax server image. See docs/DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IPM_DATA_DIR=/data \
    IPM_HOST=0.0.0.0 \
    IPM_PORT=8420

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY internpromax ./internpromax

RUN useradd --system --uid 10001 --home-dir /data ipm && mkdir -p /data && chown ipm:ipm /data
USER ipm
VOLUME /data
EXPOSE 8420
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/api/health')" || exit 1

# Needs IPM_PASSWORD (it refuses to listen on 0.0.0.0 without one).
CMD ["python", "-m", "internpromax", "serve", "--no-browser"]
