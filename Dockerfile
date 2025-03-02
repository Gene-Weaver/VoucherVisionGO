# Use Python 3.12 as the base image
FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make sure the entrypoint script is executable
RUN chmod +x ./entrypoint.sh

# Environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Run the application
ENTRYPOINT ["./entrypoint.sh"]