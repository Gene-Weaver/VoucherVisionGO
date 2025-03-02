# Use Python 3.12 as the base image
FROM python:3.12-slim

# Set workdir to root directory
WORKDIR /

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Install git to handle submodules if needed
RUN apt-get update && apt-get install -y git

# Initialize and update submodules if vouchervision_main is a git submodule
RUN if [ -f .gitmodules ]; then git submodule update --init --recursive; fi

# Make sure the entrypoint script is executable
RUN chmod +x ./entrypoint.sh

# Environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
# Set PYTHONPATH to include the root and vouchervision_main
ENV PYTHONPATH="/:/vouchervision_main"

# Run the application
ENTRYPOINT ["./entrypoint.sh"]