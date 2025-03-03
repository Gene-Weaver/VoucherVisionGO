# Use Python 3.12 as the base image
FROM python:3.12-slim

# Set environment variables early to ensure they're in a stable layer
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app:/app/vouchervision_main"

# Set workdir to root directory 
WORKDIR /app

# Install system dependencies - keep in a single layer to reduce image size
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

# Copy only requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies (will be cached if requirements.txt doesn't change)
RUN pip install --no-cache-dir -r requirements.txt

# Copy git-related files for submodule handling
COPY .gitmodules* ./ 
COPY .git* ./

# Clone submodules if needed - this runs only if the git files change
RUN if [ -f .gitmodules ]; then \
        git submodule update --init --recursive || echo "Could not update submodules"; \
    fi

# Now copy the application code (this layer changes most frequently)
# First, copy entrypoint to ensure it's executable before other files
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

# Copy the rest of the application code
COPY . .

# Create symbolic links for modules (only if needed and after code is copied)
RUN ln -sf /app/vouchervision_main/vouchervision /app/vouchervision || echo "Could not create symlink - check if directories exist"

# Run the application
ENTRYPOINT ["/app/entrypoint.sh"]