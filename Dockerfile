# Use Python 3.12 as the base image (to match the error log Python version)
FROM python:3.12-slim

# Set workdir to root directory 
WORKDIR /app

# Install system dependencies including OpenCV dependencies
RUN apt-get update && apt-get install -y \
    git \
    procps \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install git and debugging tools
RUN apt-get update && apt-get install -y git procps

# Pre-generate the Matplotlib font cache to avoid runtime initialization
RUN python -c "import matplotlib.pyplot as plt; plt.figure(); plt.close()"

# Copy application code
COPY . .

# Check if vouchervision_main exists, if not clone it
RUN if [ ! -d "/vouchervision_main" ]; then \
        echo "vouchervision_main directory not found, attempting to clone"; \
        if [ -f .gitmodules ]; then \
            git submodule update --init --recursive --remote; \
        fi; \
    fi

# Initialize and update the submodule
RUN git submodule update --init --recursive --remote

# Create symbolic links to ensure Python can find the modules both ways
RUN ln -sf /vouchervision_main/vouchervision /vouchervision || echo "Could not create symlink to vouchervision"

# Create symbolic links for modules
RUN ln -sf /app/vouchervision_main/vouchervision /app/vouchervision

# Make sure the entrypoint script is executable
RUN chmod +x /app/entrypoint.sh

# Environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
# ENV PYTHONPATH="/app:/app/vouchervision_main"
ENV PYTHONPATH="/app:/app/vouchervision_main:/app/vouchervision_main/vouchervision"

# Run the application
ENTRYPOINT ["/app/entrypoint.sh"]