#!/bin/bash
# Start Gunicorn server
exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app