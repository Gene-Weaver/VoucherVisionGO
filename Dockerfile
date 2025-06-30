# Use the official Python slim image as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app:/app/vouchervision_main:/app/vouchervision_main/vouchervision:/app/TextCollage"

# Set the working directory
WORKDIR /app

# Install system dependencies. This layer will be cached.
RUN apt-get update && apt-get install -y \
    git \
    procps \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements.txt first. This layer is cached unless the file changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application source code from the build context.
# The `cloudbuild.yaml` has already ensured the submodule is present and correct.
COPY . .

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Run the application
ENTRYPOINT ["/app/entrypoint.sh"]