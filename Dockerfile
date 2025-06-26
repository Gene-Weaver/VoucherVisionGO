# Use the official Python slim image as a parent image
FROM python:3.12-slim

# Step 1: Add ARG and LABEL to enable intelligent cache busting from cloudbuild.yaml
ARG VCS_REF
LABEL REPO_COMMIT_REF=$VCS_REF

# Set the working directory in the container
WORKDIR /app

# Install system-level dependencies required by OpenCV and other libraries
# Consolidate all apt-get installs into a single RUN layer for efficiency
RUN apt-get update && apt-get install -y \
    git \
    procps \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    # Clean up apt-get lists to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies from the requirements file
RUN pip install --no-cache-dir -r requirements.txt

# Pre-generate the Matplotlib font cache to prevent slow first-time startup
RUN python -c "import matplotlib.pyplot as plt; plt.figure(); plt.close()"

# Copy Git configuration files first (needed for submodule operations)
COPY .git .git
COPY .gitmodules .gitmodules

# Initialize and update submodules inside the Docker container
RUN git submodule update --init --recursive --force

# Copy the rest of the application code
COPY . .

# Verify submodule content was properly initialized (debug step)
RUN ls -la vouchervision_main/ && \
    ls -la vouchervision_main/vouchervision/ || echo "Submodule content check failed"

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Set environment variables for the container
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
# Set the PYTHONPATH to ensure all modules are discoverable
ENV PYTHONPATH="/app:/app/vouchervision_main:/app/vouchervision_main/vouchervision"

# Specify the entrypoint for the container
ENTRYPOINT ["/app/entrypoint.sh"]