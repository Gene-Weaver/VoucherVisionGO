# gunicorn.conf.py
import os

# Bind to the port provided by Cloud Run
bind = f"0.0.0.0:{os.environ.get('PORT', 8080)}"

# Worker configuration - adjust based on your needs
# workers = int(os.environ.get('GUNICORN_WORKERS', 2))
workers = 1
# worker_class = "gthread"
worker_class = "sync"
worker_connections = 1000
threads = int(os.environ.get('GUNICORN_THREADS', 8))

# Timeout settings - important for Cloud Run
timeout = 300  # 5 minutes
keepalive = 5
max_requests = 1000
max_requests_jitter = 20

# Logging configuration for Cloud Run
loglevel = os.environ.get('LOG_LEVEL', 'info').lower()
accesslog = '-'  # Log to stdout
errorlog = '-'   # Log to stderr
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sμs'

# Preload the application
preload_app = False

# Process naming
proc_name = 'vouchervision-api'

# For Cloud Run, ensure proper signal handling
worker_tmp_dir = '/dev/shm'  # Use shared memory for worker heartbeat