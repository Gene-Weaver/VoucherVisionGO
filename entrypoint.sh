#!/bin/bash

# Print runtime environment info for debugging
echo "Starting VoucherVision GO service..."
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"
echo "Python path: $PYTHONPATH"
echo "Files in current directory:"
ls -la

# Debug vouchervision import
python3 -c "import sys; print(sys.path); import os; print(os.listdir('/app')); print(os.listdir('/app/vouchervision_main') if os.path.exists('/app/vouchervision_main') else 'Not found')"

# Start Gunicorn server
exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app