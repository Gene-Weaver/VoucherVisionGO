# Use Python 3.9 as the base image (to match the error log Python version)
FROM python:3.9-slim

# Set workdir to root directory 
WORKDIR /

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install git and debugging tools
RUN apt-get update && apt-get install -y git procps

# Copy application code
COPY . .

# Check if vouchervision_main exists, if not clone it
RUN if [ ! -d "/vouchervision_main" ]; then \
        echo "vouchervision_main directory not found, attempting to clone"; \
        if [ -f .gitmodules ]; then \
            git submodule update --init --recursive; \
        fi; \
    fi

# Create symbolic links to ensure Python can find the modules both ways
RUN ln -sf /vouchervision_main/vouchervision /vouchervision || echo "Could not create symlink to vouchervision"

# Make sure the entrypoint script is executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/:/vouchervision_main:/app"

# Run the application
ENTRYPOINT ["/entrypoint.sh"]