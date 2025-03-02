#!/bin/bash

# Debug information
echo "Current directory: $(pwd)"
echo "Listing root directory:"
ls -la /
echo "Checking for vouchervision_main:"
ls -la /vouchervision_main 2>/dev/null || echo "vouchervision_main not found"
echo "Python path: $PYTHONPATH"
echo "Checking Python import paths:"
python3 -c "import sys; print(sys.path)"

# Start Gunicorn server
exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app