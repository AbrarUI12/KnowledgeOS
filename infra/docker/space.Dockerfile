# syntax=docker/dockerfile:1.7
#
# All-in-one backend for the free Hugging Face Docker Space (ADR-008, DV-001, S32): the API on
# port 7860 plus both Celery workers, the outbox dispatcher, beat, Redis and clamd, all under
# supervisord as uid 1000. Model weights are baked in because free Spaces have no persistent disk.
#
#   make space-build            # = the worker image, then this one
#   docker build -f infra/docker/space.Dockerfile --build-arg BACKEND_IMAGE=<worker image> .
# Build context: repository root.

ARG BACKEND_IMAGE=knowledgeos-worker:local
FROM ${BACKEND_IMAGE}

USER root
# Redis (ephemeral queue, DV-006), ClamAV (malware scanning is required on staging), supervisord.
# clamd listens on 127.0.0.1:3310 only and runs in the foreground as uid 1000.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      redis-server clamav clamav-daemon clamav-freshclam supervisor \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/lib/clamav /run/clamav /models/docling /app/scripts \
 && sed -i \
      -e 's|^LocalSocket |# LocalSocket |' \
      -e 's|^Foreground .*|Foreground true|' \
      -e 's|^User |# User |' \
      -e 's|^LogFile |# LogFile |' \
      /etc/clamav/clamd.conf \
 && printf 'TCPSocket 3310\nTCPAddr 127.0.0.1\nStreamMaxLength 60M\nLogSyslog false\n' \
      >> /etc/clamav/clamd.conf \
 && sed -i \
      -e 's|^DatabaseOwner .*|DatabaseOwner app|' \
      -e 's|^UpdateLogFile |# UpdateLogFile |' \
      /etc/clamav/freshclam.conf \
 && chown -R app:app /var/lib/clamav /run/clamav /models /app/scripts

COPY --chown=app:app scripts/download_models.py scripts/download_docling_models.py /app/scripts/
COPY --chown=app:app infra/docker/space/supervisord.conf /etc/knowledgeos/supervisord.conf
COPY --chown=app:app --chmod=755 infra/docker/space/entrypoint.sh /usr/local/bin/kos-entrypoint

USER app
# Signatures and model weights at build time, so a cold start doesn't re-download gigabytes.
# Reranker: the same bge-reranker-v2-m3, already exported to int8 ONNX by onnx-community
# (exporting it during the build needs more memory than Docker/CI runners have).
RUN freshclam --foreground --stdout
RUN python /app/scripts/download_models.py --output-dir /models/hf/hub \
 && python /app/scripts/download_docling_models.py --output-dir /models/docling
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('onnx-community/bge-reranker-v2-m3-ONNX', cache_dir='/models/hf/hub', allow_patterns=['*.json', '*.txt', '*.model', 'onnx/model_int8.onnx'])"

# Space defaults; secrets and account-specific values come from Space variables and secrets
# (infra/space/staging.env.example lists them).
ENV ENVIRONMENT=staging \
    HF_HUB_OFFLINE=1 \
    REDIS_URL=redis://127.0.0.1:6379/0 \
    MALWARE_SCANNER=clamav \
    CLAMAV_HOST=127.0.0.1 \
    CLAMAV_PORT=3310 \
    EMBEDDING_PROVIDER=sentence_transformers \
    EMBEDDING_DEVICE=cpu \
    RERANKER_MODEL=onnx-community/bge-reranker-v2-m3-ONNX \
    RERANKER_BACKEND=onnx \
    RERANKER_ONNX_FILE=onnx/model_int8.onnx \
    DOCLING_ARTIFACTS_PATH=/models/docling \
    DOCLING_OCR=false

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/health/live', timeout=3).status == 200 else 1)"]
ENTRYPOINT ["/usr/local/bin/kos-entrypoint"]
