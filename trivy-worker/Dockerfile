# Containerized, pinned Trivy scanner with a minimal private HTTP adapter.
# No Trivy executable or database is installed in the pyTMBot container.
FROM aquasec/trivy:0.76.2

RUN apk add --no-cache python3 && \
    addgroup -S -g 10001 trivyworker && \
    adduser -S -D -H -u 10001 -G trivyworker trivyworker

COPY --chmod=0444 server.py /opt/trivy-worker/server.py

USER 10001:10001
WORKDIR /
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8090
ENTRYPOINT ["python3", "-I", "/opt/trivy-worker/server.py"]
