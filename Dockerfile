FROM python:3.12-slim

ARG APP_VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG PIP_VERSION=26.1.2
LABEL org.opencontainers.image.title="deployment-tracker" \
      org.opencontainers.image.description="Secure DevSecOps Deployment Tracker API" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"\
      org.opencontainers.image.source="https://github.com/iiismailtriki/devsecops-deployment-tracker"
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade \
        bsdutils \
        libblkid1 \
        liblastlog2-2 \
        libmount1 \
        libsmartcols1 \
        libuuid1 \
        login \
        mount \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN addgroup --system --gid 10001 appgroup \
    && adduser --system --uid 10001 --ingroup appgroup --no-create-home appuser

COPY requirements.txt .

RUN python -m pip install --no-cache-dir --upgrade "pip==${PIP_VERSION}" \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY VERSION ./VERSION

RUN chown -R appuser:appgroup /app

USER 10001:10001

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000

HEALTHCHECK \
    --interval=30s \
    --timeout=3s \
    --start-period=10s \
    --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "app.main:app"]
