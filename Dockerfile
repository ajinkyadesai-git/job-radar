# Job Radar API image. The same image runs on a laptop (docker run) and on AWS Lambda:
# the Lambda Web Adapter turns Lambda events into normal HTTP calls to uvicorn.
FROM python:3.12-slim

# Lambda Web Adapter: only active when running inside Lambda; ignored by docker run.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/health

WORKDIR /app

# Install dependencies first (this layer is cached until pyproject.toml changes).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[api]"

# Run as a normal user, not root.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1

# Secrets (JOBRADAR_API_KEY, DATABRICKS_*, ANTHROPIC_API_KEY) come from the environment at
# run time: --env-file locally, Lambda settings in the cloud. Never baked into the image.
CMD ["sh", "-c", "uvicorn jobradar.api.app:app --host 0.0.0.0 --port ${PORT}"]
