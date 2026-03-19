# Use the official Python slim image as a parent image
# FROM python:3.12-slim
FROM python:3.10-slim

# Set environment variables
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app:/app/vouchervision_main:/app/vouchervision_main/vouchervision:/app/TextCollage"

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends\
    git \
    procps \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgdal-dev \
    gdal-bin \
    libproj-dev \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip "setuptools<70" wheel
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --upgrade "setuptools<70"

# Copy the entire application (including submodules)
COPY . .

# Verify TextCollage was copied correctly
RUN ls -la /app/TextCollage/ || echo "TextCollage not found"
RUN ls -la /app/TextCollage/models/ || echo "models directory not found"
RUN ls -la /app/TextCollage/models/openvino/ || echo "openvino directory not found"

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Use the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]