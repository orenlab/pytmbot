# Containerized, pinned Trivy scanner with a minimal private HTTP adapter.
# No Trivy executable or database is installed in the pyTMBot container.
FROM aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb

RUN apk add --no-cache python3 && \
    addgroup -S -g 10001 trivyworker && \
    adduser -S -D -H -u 10001 -G trivyworker trivyworker && \
    mkdir -p /opt/trivy-worker && \
    chmod 0755 /opt/trivy-worker

COPY --chown=10001:10001 --chmod=0444 server.py /opt/trivy-worker/server.py

USER 10001:10001
WORKDIR /
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8090
ENTRYPOINT ["python3", "-I", "/opt/trivy-worker/server.py"]
