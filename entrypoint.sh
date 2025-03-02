#!/bin/bash

# Debug information
echo "Current directory: $(pwd)"
echo "Listing directory contents:"
ls -la
echo "Python path: $PYTHONPATH"

# Debug vouchervision import
python3 -c "import sys; print(sys.path); import os; print(os.listdir('/app')); print(os.listdir('/app/vouchervision_main') if os.path.exists('/app/vouchervision_main') else 'Not found')"

# Start Gunicorn server
exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app