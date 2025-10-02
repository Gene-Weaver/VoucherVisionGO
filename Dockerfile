# # syntax=docker/dockerfile:1.7
# FROM python:3.12.6-slim

# ENV PORT=8080 \
#     PYTHONUNBUFFERED=1 \
#     PYTHONPATH="/app:/app/vouchervision_main:/app/vouchervision_main/vouchervision:/app/TextCollage" \
#     PIP_DISABLE_PIP_VERSION_CHECK=1 \
#     PYTHONDONTWRITEBYTECODE=1 \
#     PIP_ROOT_USER_ACTION=ignore

# WORKDIR /app

# # --- System deps (cached) ---
# RUN --mount=type=cache,target=/var/cache/apt \
#     --mount=type=cache,target=/var/lib/apt/lists \
#     apt-get update && apt-get install -y --no-install-recommends \
#       git procps libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
#     && rm -rf /var/lib/apt/lists/*

# # --- Python deps (cached) ---
# COPY requirements.txt requirements.txt
# RUN --mount=type=cache,target=/root/.cache/pip \
#     python -m pip install --upgrade pip \
#  && pip install -r requirements.txt

# # --- App code (changes often; fast layer) ---
# COPY . .

# # Sanity checks
# RUN ls -la /app/TextCollage/ || echo "TextCollage not found" \
#  && ls -la /app/TextCollage/models/ || echo "models directory not found" \
#  && ls -la /app/TextCollage/models/openvino/ || echo "openvino directory not found"

# RUN chmod +x /app/entrypoint.sh
# ENTRYPOINT ["/app/entrypoint.sh"]

# syntax=docker/dockerfile:1.7
# Allow PROJECT_ID to be passed at build time so we can pull the base from Artifact Registry.
ARG PROJECT_ID
FROM us-central1-docker.pkg.dev/${PROJECT_ID}/bases/vv-base:latest

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app:/app/vouchervision_main:/app/vouchervision_main/vouchervision:/app/TextCollage"

WORKDIR /app

# --- App code (changes often; fast to rebuild) ---
COPY . .

# Optional sanity checks you had
RUN ls -la /app/TextCollage/ || echo "TextCollage not found" \
 && ls -la /app/TextCollage/models/ || echo "models directory not found" \
 && ls -la /app/TextCollage/models/openvino/ || echo "openvino directory not found"

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
