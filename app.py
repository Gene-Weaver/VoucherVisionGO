import os
import sys
import json
import datetime
import tempfile
import threading
import math
import io
import time
import base64
import uuid
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="You are using a Python version")
import requests

APP_USER_AGENT = "VoucherVisionGO/1.0 (University of Michigan; vouchervision.api@gmail.com) python-requests/2.32.5"
from io import BytesIO
from werkzeug.datastructures import FileStorage
from PIL import Image
from flask import Flask, request, jsonify, redirect, make_response, render_template
from flask_cors import CORS
import logging
from werkzeug.utils import secure_filename
from collections import OrderedDict
from pathlib import Path
import yaml
import re
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import textwrap
from tabulate import tabulate
import shutil
import fitz  # PyMuPDF - PDF to image conversion
from pillow_heif import register_heif_opener
register_heif_opener()

import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.cloud import firestore as _gc_firestore

from url_name_parser import extract_filename_from_url
from impact import estimate_impact
from anti_bot_fetch import smart_fetch_image_as_filestorage

'''
### TO UPDATE FROM MAIN VV REPO
git submodule update --init --recursive --remote

good example url: https://medialib.naturalis.nl/file/id/L.3800382/format/large
'''

# Setup paths and imports
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

submodule_path = os.path.join(project_root, "vouchervision_main")
sys.path.insert(0, submodule_path)

vouchervision_path = os.path.join(submodule_path, "vouchervision")
sys.path.insert(0, vouchervision_path)

component_detector_path = os.path.join(vouchervision_path, "component_detector")
sys.path.insert(0, component_detector_path)

text_collage_path = os.path.join(project_root, "TextCollage")
sys.path.insert(0, text_collage_path)


def setup_cloud_logging():
    """Setup structured logging for Google Cloud Run"""
    import json
    import sys

    class CloudFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                'timestamp': self.formatTime(record, self.datefmt),
                'severity': record.levelname,
                'message': record.getMessage(),
                'logger': record.name,
                'module': record.module,
                'function': record.funcName,
                'line': record.lineno
            }
            if hasattr(record, 'user_id'):
                log_entry['user_id'] = record.user_id
            if hasattr(record, 'request_id'):
                log_entry['request_id'] = record.request_id
            return json.dumps(log_entry)

    # Configure root logger — clear ALL existing handlers first to prevent
    # duplicate log lines from gunicorn/flask/root all writing to stdout.
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if os.environ.get('ENV') == 'production':
        handler.setFormatter(CloudFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Silence noisy third-party loggers
    for noisy_logger in [
        'urllib3', 'requests', 'chardet', 'charset_normalizer',
        'google.api_core', 'google.auth', 'google.cloud',
        'numexpr', 'numexpr.utils',
        'matplotlib', 'matplotlib.font_manager',
        'streamlit', 'streamlit.runtime',
        'PIL', 'pillow_heif',
        'grpc', 'grpc._cython',
        'werkzeug',
        'firebase_admin',
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
def get_logger(name):
    """Get a logger with appropriate configuration for the environment"""
    logger = logging.getLogger(name)
    if logger.level == 0:
        logger.setLevel(logging.INFO)
    return logger
setup_cloud_logging()
logger = get_logger(__name__)


vouchervision_main_path = os.path.join(project_root, "vouchervision_main")
if os.path.exists(vouchervision_main_path):
    sys.path.insert(0, vouchervision_main_path)
    
    vouchervision_path = os.path.join(vouchervision_main_path, "vouchervision")
    if os.path.exists(vouchervision_path):
        sys.path.insert(0, vouchervision_path)

# Import VoucherVision modules
try:
    from vouchervision.OCR_Gemini import OCRGeminiProVision # type: ignore
    from vouchervision.OCR_sanitize import strip_headers, sanitize_for_storage, sanitize_excel_record, markdown_to_simple_text # type: ignore
    from vouchervision.vouchervision_main import load_custom_cfg # type: ignore
    from vouchervision.utils_VoucherVision import VoucherVision # type: ignore
    from vouchervision.LLM_GoogleGemini import GoogleGeminiHandler # type: ignore
    from vouchervision.model_maps import ModelMaps # type: ignore
    from vouchervision.general_utils import calculate_cost # type: ignore
    from TextCollage.CollageEngine import CollageEngine # type: ignore
except Exception as e:
    logger.error(f"Import ERROR: {e}")
    from vouchervision_main.vouchervision.OCR_Gemini import OCRGeminiProVision
    from vouchervision_main.vouchervision.OCR_sanitize import strip_headers, sanitize_for_storage, sanitize_excel_record, markdown_to_simple_text
    from vouchervision_main.vouchervision.vouchervision_main import load_custom_cfg
    from vouchervision_main.vouchervision.utils_VoucherVision import VoucherVision
    from vouchervision_main.vouchervision.LLM_GoogleGemini import GoogleGeminiHandler
    from vouchervision_main.vouchervision.model_maps import ModelMaps
    from vouchervision_main.vouchervision.general_utils import calculate_cost
    from TextCollage.CollageEngine import CollageEngine

from wfo_local_lookup import WFOLocalLookup

    

def get_firebase_config():
    """Get Firebase configuration for client-side use from Secret Manager"""
    # Default configuration values
    config = {
        "apiKey": "",
        "authDomain": "",
        "projectId": "vouchervision-387816",
        "storageBucket": "",
        "messagingSenderId": "",
        "appId": ""
    }
    
    # Try to get web configuration from Secret Manager
    firebase_web_config = os.environ.get('firebase-web-config')
    if firebase_web_config:
        try:
            web_config = json.loads(firebase_web_config)
            # Update config with values from the secret
            config.update(web_config)
            logger.info("Retrieved Firebase web config from Secret Manager")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse firebase-web-config JSON: {e}")
    else:
        logger.warning("Could not retrieve firebase-web-config from Secret Manager, using defaults")
        
        # Try to get project ID from admin key as fallback
        firebase_admin_key = os.environ.get('firebase-admin-key')
        if firebase_admin_key:
            try:
                admin_key_dict = json.loads(firebase_admin_key)
                config["projectId"] = admin_key_dict.get("project_id", config["projectId"])
                logger.info(f"Extracted project ID from admin key: {config['projectId']}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse firebase-admin-key JSON: {e}")
    
    # Ensure authDomain is set if projectId is available
    if not config["authDomain"] and config["projectId"]:
        config["authDomain"] = f"{config['projectId']}.firebaseapp.com"
    
    return config



# Initialize Firebase Admin SDK with service account key
try:
    # Load service account credentials from Secret Manager
    cred_json = os.environ.get('firebase-admin-key')
    if cred_json:
        cred_dict = json.loads(cred_json)
        creds = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(credential=creds)
        logger.info("Firebase Admin SDK initialized with service account credentials")
    else:
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "vouchervision-387816")
        firebase_admin.initialize_app(options={"projectId": project_id})
        logger.info(f"Firebase Admin SDK initialized for project: {project_id}")
except ValueError:
    pass  # Already initialized
except Exception as e:
    logger.error(f"Failed to initialize Firebase Admin SDK: {e}")

# Initialize Firestore client
db = firestore.client()

def get_maintenance_status():
    """Get current maintenance status from Firestore"""
    try:
        maintenance_doc = db.collection('system_config').document('maintenance').get()
        if maintenance_doc.exists:
            data = maintenance_doc.to_dict()
            return data.get('enabled', False)
        else:
            # If document doesn't exist, create it with default value
            db.collection('system_config').document('maintenance').set({
                'enabled': False,
                'last_updated': firestore.SERVER_TIMESTAMP,
                'updated_by': 'System'
            })
            return False
    except Exception as e:
        logger.error(f"Error getting maintenance status from Firestore: {str(e)}")
        # Default to False if there's an error
        return False

def set_maintenance_status(enabled, updated_by='System'):
    """Set maintenance status in Firestore"""
    try:
        maintenance_data = {
            'enabled': enabled,
            'last_updated': firestore.SERVER_TIMESTAMP,
            'updated_by': updated_by
        }
        
        db.collection('system_config').document('maintenance').set(maintenance_data)
        logger.info(f"Maintenance mode {'enabled' if enabled else 'disabled'} by {updated_by}")
        return True
    except Exception as e:
        logger.error(f"Error setting maintenance status in Firestore: {str(e)}")
        return False

def maintenance_mode_middleware(f):
    """Decorator to check maintenance mode before executing route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip maintenance check for admin routes, health checks, and maintenance status endpoints
        if (request.endpoint and 
            (request.endpoint.startswith('admin') or 
             request.endpoint in ['health_check', 'get_maintenance_status_endpoint', 'set_maintenance_mode_endpoint'])):
            return f(*args, **kwargs)
        
        # Check if maintenance mode is enabled (now from Firestore)
        if get_maintenance_status():
            response = jsonify({
                'error': 'VoucherVisionGO API Temporarily Unavailable',
                'message': 'The API is temporarily down for maintenance, please try again later. Visit https://leafmachine.org/vouchervisiongo/ for more information.'
            })
            response.status_code = 503
            # Ensure CORS headers are added to maintenance responses
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key,Accept')
            response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS,PUT,DELETE')
            return response
        
        return f(*args, **kwargs)
    return decorated_function

def validate_api_key(api_key):
    """Validate an API key against the Firestore database """
    try:
        # Check if the API key exists
        api_key_doc = db.collection('api_keys').document(api_key).get()
        
        if api_key_doc.exists:
            # Check if the key is active and not expired
            key_data = api_key_doc.to_dict()
            
            if not key_data.get('active', False):
                logger.warning(f"Inactive API key used: {api_key[:8]}...")
                return False
            
            # Check expiration if set
            if 'expires_at' in key_data:
                import datetime
                from datetime import timezone
                
                # Create timezone-aware current datetime
                now = datetime.datetime.now(timezone.utc)
                
                # Get expiration time and ensure it's timezone-aware
                expires_at = key_data['expires_at']
                
                # If expires_at is a Firestore timestamp, convert it to datetime
                if hasattr(expires_at, '_seconds'):
                    # Convert Firestore timestamp to datetime with UTC timezone
                    expires_at = datetime.datetime.fromtimestamp(expires_at._seconds, timezone.utc)
                # If it's already a datetime but has no timezone, add UTC
                elif isinstance(expires_at, datetime.datetime) and expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                
                # Now both datetimes have timezone information for safe comparison
                if now > expires_at:
                    logger.warning(f"Expired API key used: {api_key[:8]}...")
                    return False
            
            # Log API key usage (optional)
            db.collection('api_key_usage').add({
                'api_key_id': api_key,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'ip_address': request.remote_addr,
                'endpoint': request.path
            })
            
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error validating API key: {str(e)}")
        return False


# ── Gemini Pro rate-limiting helpers ─────────────────────────────────────

GEMINI_PRO_DEFAULT_LIMIT = 100

def is_gemini_pro_model(model_name: str | None) -> bool:
    """Return True if *model_name* is a Gemini Pro model."""
    return model_name is not None and "pro" in model_name.lower()


def is_pro_request(engine_options: list[str] | None, llm_model_name: str | None) -> bool:
    """Return True if any model involved in this request is a Gemini Pro model."""
    if is_gemini_pro_model(llm_model_name):
        return True
    if engine_options:
        for engine in engine_options:
            if is_gemini_pro_model(engine):
                return True
    return False


def check_gemini_pro_rate_limit(user_email: str) -> tuple[bool, int, int]:
    """Read-only check whether *user_email* is within their Gemini Pro usage limit.

    Returns (allowed, current_count, limit).
    NOTE: For gating requests, use check_and_reserve_gemini_pro_quota() instead
    to avoid race conditions.
    """
    try:
        doc = db.collection("usage_statistics").document(user_email).get()
        if not doc.exists:
            return (True, 0, GEMINI_PRO_DEFAULT_LIMIT)
        data = doc.to_dict() or {}
        count = int(data.get("gemini_pro_usage_count", 0))
        limit = int(data.get("gemini_pro_usage_limit", GEMINI_PRO_DEFAULT_LIMIT))
        return (count < limit, count, limit)
    except Exception as e:
        logger.error(f"Error checking Gemini Pro rate limit for {user_email}: {e}")
        return (True, 0, GEMINI_PRO_DEFAULT_LIMIT)


def check_and_reserve_gemini_pro_quota(user_email: str) -> tuple[bool, int, int]:
    """Atomically check and increment Gemini Pro usage count.

    Uses a Firestore transaction to prevent concurrent requests from
    bypassing the limit.  Returns (allowed, count_after, limit).
    """
    try:
        user_ref = db.collection("usage_statistics").document(user_email)

        @_gc_firestore.transactional
        def _txn(transaction):
            doc = user_ref.get(transaction=transaction)
            if not doc.exists:
                # Brand-new user — allow and initialise count to 1
                transaction.set(user_ref, {
                    "gemini_pro_usage_count": 1,
                    "gemini_pro_usage_limit": GEMINI_PRO_DEFAULT_LIMIT,
                }, merge=True)
                return (True, 1, GEMINI_PRO_DEFAULT_LIMIT)

            data = doc.to_dict() or {}
            count = int(data.get("gemini_pro_usage_count", 0))
            limit = int(data.get("gemini_pro_usage_limit", GEMINI_PRO_DEFAULT_LIMIT))

            if count >= limit:
                return (False, count, limit)

            new_count = count + 1
            transaction.update(user_ref, {"gemini_pro_usage_count": new_count})
            return (True, new_count, limit)

        return _txn(db.transaction())
    except Exception as e:
        logger.error(f"Error in Gemini Pro rate-limit reservation for {user_email}: {e}")
        # Fail-open so the request isn't silently blocked by a transient error
        return (True, 0, GEMINI_PRO_DEFAULT_LIMIT)


def release_gemini_pro_quota(user_email: str):
    """Decrement gemini_pro_usage_count by 1 (e.g. after a failed request).

    Safe to call even if the count is already 0 — will not go negative.
    """
    try:
        user_ref = db.collection("usage_statistics").document(user_email)

        @_gc_firestore.transactional
        def _txn(transaction):
            doc = user_ref.get(transaction=transaction)
            if not doc.exists:
                return
            count = int((doc.to_dict() or {}).get("gemini_pro_usage_count", 0))
            if count > 0:
                transaction.update(user_ref, {"gemini_pro_usage_count": count - 1})

        _txn(db.transaction())
    except Exception as e:
        logger.error(f"Error releasing Gemini Pro quota for {user_email}: {e}")


# ── Daily usage email alerts ────────────────────────────────────────────

DAILY_ALERT_THRESHOLDS = [100, 200, 500]

def _send_daily_usage_alerts(user_email: str, current_day: str, prev_count: int):
    """Fire admin emails for first-call-of-day and daily volume thresholds.

    *prev_count* is the user's daily count **before** this request was added.
    """
    try:
        from flask import current_app
        sender = current_app.config.get('email_sender')
        if not sender or not sender.is_enabled:
            return

        new_count = prev_count + 1

        # First call of the day
        if prev_count == 0:
            sender.send_admin_usage_alert(
                f"Daily activity: {user_email}",
                f"<p><strong>{user_email}</strong> made their first API call today "
                f"(<strong>{current_day}</strong>).</p>",
            )

        # High-volume thresholds
        for threshold in DAILY_ALERT_THRESHOLDS:
            if prev_count < threshold <= new_count:
                sender.send_admin_usage_alert(
                    f"High volume: {user_email} hit {threshold} calls today",
                    f"<p><strong>{user_email}</strong> has made <strong>{new_count}</strong> "
                    f"API calls today (<strong>{current_day}</strong>), crossing the "
                    f"{threshold}-call threshold.</p>",
                )
    except Exception as e:
        logger.error(f"Error sending daily usage alert for {user_email}: {e}")


_RATE_LIMIT_ALERT_COOLDOWN = 300  # seconds (5 minutes)


def _send_rate_limit_hit_alert(user_email: str, count: int, limit: int):
    """Notify admin that a user was blocked by the Gemini Pro rate limit.

    De-duplicated via Firestore: only one email is sent per user per cooldown
    window, even if dozens of parallel workers are all rejected simultaneously.
    Survives server restarts and works across multiple instances.
    """
    try:
        user_ref = db.collection("usage_statistics").document(user_email)
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            last_alert = data.get("last_rate_limit_alert_at")
            if last_alert is not None:
                # Firestore timestamps come back as datetime objects
                if hasattr(last_alert, 'timestamp'):
                    last_alert_ts = last_alert.timestamp()
                else:
                    last_alert_ts = float(last_alert)
                if time.time() - last_alert_ts < _RATE_LIMIT_ALERT_COOLDOWN:
                    return  # already alerted recently

        # Mark the alert time *before* sending so concurrent requests
        # that read in the same moment also see it
        user_ref.set({"last_rate_limit_alert_at": firestore.SERVER_TIMESTAMP}, merge=True)

        from flask import current_app
        sender = current_app.config.get('email_sender')
        if not sender or not sender.is_enabled:
            return
        sender.send_admin_usage_alert(
            f"Rate limit hit: {user_email}",
            f"<p><strong>{user_email}</strong> attempted to use a Gemini Pro model but has "
            f"reached their limit (<strong>{count}/{limit}</strong> requests used).</p>"
            f"<p>You can increase their limit from the <em>Rate Limits</em> tab in the "
            f"admin dashboard.</p>",
        )
    except Exception as e:
        logger.error(f"Error sending rate-limit alert for {user_email}: {e}")


def _send_pro_migration_advisory(user_email: str, count: int, limit: int):
    """Send the user a one-per-day advisory suggesting they migrate away from Pro models.

    Checks Firestore for `last_pro_advisory_date`; if it matches today, the
    email is suppressed.  Only call this when the user is NOT supplying their
    own API key.
    """
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        user_ref = db.collection("usage_statistics").document(user_email)
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            if data.get("last_pro_advisory_date") == today:
                return  # already sent today

        # Mark today *before* sending to prevent duplicates from parallel workers
        user_ref.set({"last_pro_advisory_date": today}, merge=True)

        from flask import current_app
        sender = current_app.config.get('email_sender')
        if not sender or not sender.is_enabled:
            return

        sender.send_email(
            user_email,
            "VoucherVision — Gemini Pro usage advisory",
            textwrap.dedent(f"""\
            <html><body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <p>Hello,</p>

            <p>You've used <strong>{count}</strong> of your <strong>{limit}</strong>
            Gemini&nbsp;Pro model requests on VoucherVision today.</p>

            <p>To help you keep working without interruption, here are two options:</p>

            <h3>Option 1 — Switch to a faster, unlimited model</h3>
            <p>Consider using <code>gemini-3.1-flash-lite-preview</code> instead.
            It has <strong>no call limit</strong> on VoucherVision and offers equivalent
            performance to the Gemini Pro models for transcription tasks.</p>

            <h3>Option 2 — Supply your own Gemini API key</h3>
            <p>If you prefer to keep using Pro models, you can provide your own
            Google Gemini API key. This bypasses the server-side quota entirely.</p>
            <p>Add the <code>gemini_api_key</code> parameter to your requests:</p>
            <pre style="background: #f4f4f4; padding: 12px; border-radius: 4px;">
# Python example
requests.post(
    "https://&lt;server&gt;/process",
    data={{
        "engines": "gemini-3.1-pro-preview",
        "gemini_api_key": "YOUR_GEMINI_API_KEY",
        ...
    }},
    files={{"file": open("image.jpg", "rb")}},
)</pre>

            <p>You can obtain an API key from
            <a href="https://aistudio.google.com/apikey">Google AI Studio</a>.</p>

            <p>For more detailed information and usage examples, see the
            <a href="https://pypi.org/project/vouchervision-go-client/">VoucherVision GO
            Python client documentation</a>.</p>

            <p style="color: #666; font-size: 0.9em;">This is an automated
            one-per-day advisory from the VoucherVision team.</p>
            </body></html>"""),
        )
        logger.info(f"Sent pro-migration advisory to {user_email}")
    except Exception as e:
        logger.error(f"Error sending pro-migration advisory to {user_email}: {e}")


# ── API key expiration notification system ──────────────────────────────
# Runs at most once per day, triggered lazily on the first request.
# The daily guard is stored in Firestore (system_config/expiry_check) so it
# survives instance restarts and prevents duplicate scans across Cloud Run
# instances.  A local in-memory cache avoids hitting Firestore on every request.

_EXPIRY_WARNING_DAYS = 30  # warn this many days before expiration
_EXPIRY_CHECK_COLLECTION = "system_config"
_EXPIRY_CHECK_DOC = "expiry_check"
_expiry_check_lock = threading.Lock()
_local_expiry_check_date = None  # in-memory cache to skip Firestore reads


def _check_api_key_expirations():
    """Gate for the daily expiry scan.

    Uses a two-layer guard:
      1. In-memory cache — avoids Firestore read on every request within
         the same instance.
      2. Firestore document (system_config/expiry_check) — prevents
         duplicate scans across multiple Cloud Run instances and survives
         restarts.
    """
    global _local_expiry_check_date
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # Layer 1: fast in-memory check
    if _local_expiry_check_date == today_str:
        return

    # Acquire lock so only one thread in this instance proceeds
    if not _expiry_check_lock.acquire(blocking=False):
        return
    try:
        # Re-check after lock
        if _local_expiry_check_date == today_str:
            return

        # Layer 2: Firestore check (cross-instance)
        check_ref = db.collection(_EXPIRY_CHECK_COLLECTION).document(_EXPIRY_CHECK_DOC)
        check_doc = check_ref.get()
        if check_doc.exists and check_doc.to_dict().get("last_scan_date") == today_str:
            # Another instance already ran the scan today
            _local_expiry_check_date = today_str
            return

        # Claim today's scan in Firestore before starting
        check_ref.set({"last_scan_date": today_str, "started_at": firestore.SERVER_TIMESTAMP}, merge=True)
        _local_expiry_check_date = today_str
    except Exception as e:
        logger.error(f"Error checking expiry scan guard in Firestore: {e}")
        return
    finally:
        _expiry_check_lock.release()

    # Run the actual scan in a background thread to avoid blocking the request
    admin_email = os.environ.get('VOUCHERVISION_API_EMAIL_ADDRESS')
    logger.info(f"Starting API key expiration scan for {today_str} (ADMIN_EMAIL={'set' if admin_email else 'NOT SET'})")
    threading.Thread(target=_run_expiry_scan, args=(today_str,), daemon=True).start()


def _run_expiry_scan(today_str: str):
    """Background thread: iterate over active API keys and send notifications."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc)

        with app.app_context():
            sender = app.config.get('email_sender')
            if not sender or not sender.is_enabled:
                logger.info("Email sender not available; skipping expiry scan.")
                return

            # Counters for the admin summary email
            keys_checked = 0
            warnings_sent = 0
            expired_notices_sent = 0
            already_expired_count = 0

            # Single pass over all active keys
            all_keys = db.collection('api_keys').where('active', '==', True).stream()

            for doc in all_keys:
                try:
                    data = doc.to_dict()
                    expires_at = data.get('expires_at')
                    if not expires_at:
                        continue

                    keys_checked += 1

                    # Normalize to datetime with UTC
                    if hasattr(expires_at, '_seconds'):
                        expires_at = datetime.datetime.fromtimestamp(
                            expires_at._seconds, datetime.timezone.utc
                        )
                    elif isinstance(expires_at, datetime.datetime) and expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)

                    owner = data.get('owner')
                    key_name = data.get('name', 'Unnamed Key')
                    if not owner:
                        continue

                    days_remaining = (expires_at - now).days

                    if days_remaining < 0:
                        # Key is expired
                        already_expired_count += 1
                        if not data.get('expiry_expired_sent'):
                            expires_date_str = expires_at.strftime("%B %d, %Y")
                            _send_expired_email(sender, owner, key_name, doc.id, expires_date_str)
                            db.collection('api_keys').document(doc.id).set(
                                {'expiry_expired_sent': today_str}, merge=True
                            )
                            expired_notices_sent += 1
                    elif days_remaining <= _EXPIRY_WARNING_DAYS:
                        # Key expires within warning window — send ONE warning per key ever
                        if not data.get('expiry_warning_sent'):
                            expires_date_str = expires_at.strftime("%B %d, %Y")
                            _send_expiry_warning_email(
                                sender, owner, key_name, doc.id, expires_date_str, days_remaining
                            )
                            db.collection('api_keys').document(doc.id).set(
                                {'expiry_warning_sent': today_str}, merge=True
                            )
                            warnings_sent += 1
                except Exception as e:
                    logger.error(f"Error checking expiry for key {doc.id[:8]}...: {e}")

            # Send admin summary email
            _send_expiry_scan_summary(
                sender, today_str, keys_checked, warnings_sent,
                expired_notices_sent, already_expired_count
            )

            # Record completion in Firestore
            db.collection(_EXPIRY_CHECK_COLLECTION).document(_EXPIRY_CHECK_DOC).set({
                "last_scan_date": today_str,
                "completed_at": firestore.SERVER_TIMESTAMP,
                "keys_checked": keys_checked,
                "warnings_sent": warnings_sent,
                "expired_notices_sent": expired_notices_sent,
                "already_expired_count": already_expired_count,
            }, merge=True)

        logger.info(
            f"API key expiration scan completed for {today_str}: "
            f"{keys_checked} checked, {warnings_sent} warnings sent, "
            f"{expired_notices_sent} expired notices sent, "
            f"{already_expired_count} total expired keys"
        )
    except Exception as e:
        logger.error(f"Error during API key expiration scan: {e}")


def _send_expiry_scan_summary(sender, today_str, keys_checked, warnings_sent,
                              expired_notices_sent, already_expired_count):
    """Send a daily summary of the expiration scan to the admin account."""
    try:
        subject = f"VoucherVision — API key expiry scan summary ({today_str})"
        body = textwrap.dedent(f"""\
        <html><body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #4285f4;">Daily API Key Expiration Scan</h2>
            <p>Date: <strong>{today_str}</strong></p>

            <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
                <tr style="background: #f4f4f4;">
                    <td style="padding: 10px; border: 1px solid #ddd;">API keys checked</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;"><strong>{keys_checked}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">30-day warning emails sent today</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;"><strong>{warnings_sent}</strong></td>
                </tr>
                <tr style="background: #f4f4f4;">
                    <td style="padding: 10px; border: 1px solid #ddd;">Expired-key notices sent today</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;"><strong>{expired_notices_sent}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Total keys currently expired</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;"><strong>{already_expired_count}</strong></td>
                </tr>
            </table>

            <p style="color: #666; font-size: 0.9em;">Automated daily scan from VoucherVision.
            Scan results are also stored in Firestore at
            <code>system_config/expiry_check</code>.</p>
        </div>
        </body></html>""")

        admin_email = os.environ.get('VOUCHERVISION_API_EMAIL_ADDRESS')
        if not admin_email:
            logger.warning("VOUCHERVISION_API_EMAIL_ADDRESS env var not set; skipping expiry scan summary email")
            return
        logger.info(f"Attempting to send expiry scan summary to {admin_email} for {today_str}")
        result = sender.send_email(admin_email, subject, body)
        if result:
            logger.info(f"Sent expiry scan summary to {admin_email} for {today_str}")
        else:
            logger.error(f"send_email returned False for expiry scan summary to {admin_email}")
    except Exception as e:
        logger.error(f"Error sending expiry scan summary email: {e}")


def _send_expiry_warning_email(sender, user_email, key_name, key_id, expires_date, days_remaining):
    """Send the 'your key expires soon' email."""
    subject = f"VoucherVision — Your API key expires in {days_remaining} day{'s' if days_remaining != 1 else ''}"
    body = textwrap.dedent(f"""\
    <html><body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #e67e22;">API Key Expiring Soon</h2>
        <p>Dear {user_email},</p>

        <p>Your VoucherVision API key <strong>{key_name}</strong>
        (<code>{key_id[:8]}...</code>) will expire on
        <strong>{expires_date}</strong> ({days_remaining} day{'s' if days_remaining != 1 else ''} from now).</p>

        <p>Once expired, any scripts or applications using this key will receive
        authentication errors.</p>

        <h3>How to create a new API key</h3>
        <ol>
            <li>Go to the <a href="https://vouchervision-go-738307415303.us-central1.run.app/login">VoucherVision login page</a> and sign in with your email and password.</li>
            <li>On the account overview page, click <strong>Manage API Keys</strong>.</li>
            <li>Click <strong>Create New Key</strong>, give it a name, and choose an expiry duration.</li>
            <li>Copy the new key and update it in your scripts (replace the <code>X-API-Key</code> header value).</li>
        </ol>

        <div style="margin: 30px 0; text-align: center;">
            <a href="https://vouchervision-go-738307415303.us-central1.run.app/login"
               style="background-color: #4285f4; color: white; padding: 12px 20px;
                      text-decoration: none; border-radius: 4px; font-weight: bold;">
                Log In &amp; Renew Your Key
            </a>
        </div>

        <p style="color: #666; font-size: 0.9em;">This is a one-time automated notification
        from the VoucherVision team. You will receive one additional notice if the key
        expires without being renewed.</p>
    </div>
    </body></html>""")

    if sender.send_email(user_email, subject, body):
        logger.info(f"Sent expiry warning to {user_email} for key {key_id[:8]}... ({days_remaining} days left)")
    else:
        logger.error(f"Failed to send expiry warning to {user_email} for key {key_id[:8]}...")


def _send_expired_email(sender, user_email, key_name, key_id, expires_date):
    """Send the 'your key has expired' email."""
    subject = "VoucherVision — Your API key has expired"
    body = textwrap.dedent(f"""\
    <html><body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #e74c3c;">API Key Expired</h2>
        <p>Dear {user_email},</p>

        <p>Your VoucherVision API key <strong>{key_name}</strong>
        (<code>{key_id[:8]}...</code>) expired on <strong>{expires_date}</strong>
        and can no longer be used for API requests.</p>

        <p>To continue using the VoucherVision API, please create a new key:</p>

        <ol>
            <li>Go to the <a href="https://vouchervision-go-738307415303.us-central1.run.app/login">VoucherVision login page</a> and sign in with your email and password.</li>
            <li>On the account overview page, click <strong>Manage API Keys</strong>.</li>
            <li>Click <strong>Create New Key</strong>, give it a name, and choose an expiry duration.</li>
            <li>Copy the new key and update it in your scripts (replace the <code>X-API-Key</code> header value).</li>
        </ol>

        <div style="margin: 30px 0; text-align: center;">
            <a href="https://vouchervision-go-738307415303.us-central1.run.app/login"
               style="background-color: #4285f4; color: white; padding: 12px 20px;
                      text-decoration: none; border-radius: 4px; font-weight: bold;">
                Log In &amp; Create a New Key
            </a>
        </div>

        <p style="color: #666; font-size: 0.9em;">This is a one-time automated
        notification from the VoucherVision team.</p>
    </div>
    </body></html>""")

    if sender.send_email(user_email, subject, body):
        logger.info(f"Sent expired notice to {user_email} for key {key_id[:8]}...")
    else:
        logger.error(f"Failed to send expired notice to {user_email} for key {key_id[:8]}...")


def update_usage_statistics(
    user_email: str,
    engines: list[str] | None = None,
    llm_model_name: str | None = None,
    est_impact: dict | None = None,
    *,
    backfill_tokens: int = 5000,
):
    """Update usage statistics for a user in Firestore, preserving original behavior,
    mirroring with token/sustainability totals, and retroactively estimating past
    impact as total_images_processed * estimate_impact(5000).
    """

    if not user_email or user_email == 'unknown':
        logger.warning("Cannot track usage for unknown user")
        return

    # --- impact for this request (compute if not provided) ---
    try:
        if est_impact is None:
            logger.error(f"est_impact was None, defaulting to zeros: {backfill_tokens} tokens")
            est_impact = est_impact = estimate_impact(0)

        # Extract top-level metrics
        t_all   = int(est_impact.get("total_tokens_all", 0))
        wh   = float(est_impact.get("estimate_watt_hours", 0.0))
        gco2 = float(est_impact.get("estimate_grams_CO2", 0.0))
        h2o  = float(est_impact.get("estimate_milliliters_water",
                                    est_impact.get("estimate_mL_water", 0.0)))
    except Exception as e:
        logger.error(f"impact extraction failed, defaulting to zeros: {e}")
        est_impact = {}
        t_all = 0
        wh = gco2 = h2o = 0.0

    try:
        # Get current month/day
        now = datetime.datetime.now()
        current_month = now.strftime("%Y-%m")
        current_day = now.strftime("%Y-%m-%d")

        user_ref = db.collection("usage_statistics").document(user_email)
        doc = user_ref.get()

        if doc.exists:
            data = doc.to_dict() or {}

            # --- ONE-TIME BACKFILL ---
            backfill_done = bool(data.get("backfill_applied_v2", False))
            if not backfill_done:
                total_uses = int(data.get("total_images_processed", 0) or 0)
                if total_uses > 0:
                    try:
                        default_impact = estimate_impact(backfill_tokens)
                    except Exception as e:
                        logger.error(f"Backfill estimate_impact({backfill_tokens}) failed: {e}")
                        default_impact = {}

                    wh_per = float(default_impact.get("estimate_watt_hours", 0.0))
                    gco2_per = float(default_impact.get("estimate_grams_CO2", 0.0))
                    h2o_per = float(default_impact.get("estimate_milliliters_water",
                                                       default_impact.get("estimate_mL_water", 0.0)))

                    # total_images_processed * per-usage estimate
                    wh_total = wh_per * total_uses
                    gco2_total = gco2_per * total_uses
                    h2o_total = h2o_per * total_uses

                    t_all = t_all + (backfill_tokens * total_uses)

                    user_ref.update({
                        "total_watt_hours": firestore.Increment(wh_total),
                        "total_grams_CO2": firestore.Increment(gco2_total),
                        "total_mL_water": firestore.Increment(h2o_total),
                        "backfill_applied_v2": True,
                        "backfill_method": "total_images_processed * estimate_impact(5000)",
                        "backfill_snapshot": default_impact,
                        "backfill_tokens": backfill_tokens,
                    })
                    logger.info(f"Applied backfill for {user_email}: {total_uses} × {backfill_tokens} tokens.")

            # --- Update fine-grain per-request data ---
            monthly_usage = data.get("monthly_usage", {})
            monthly_usage[current_month] = monthly_usage.get(current_month, 0) + 1

            daily_usage = data.get("daily_usage", {})
            prev_daily_count = daily_usage.get(current_day, 0)
            daily_usage[current_day] = prev_daily_count + 1

            ocr_info = data.get("ocr_info", {})
            if engines:
                for engine in engines:
                    if engine:
                        ocr_info[engine] = ocr_info.get(engine, 0) + 1

            llm_info = data.get("llm_info", {})
            if llm_model_name:
                llm_info[llm_model_name] = llm_info.get(llm_model_name, 0) + 1

            increments = {
                "total_images_processed": firestore.Increment(1),
                "total_tokens_all": firestore.Increment(t_all),
                "total_watt_hours": firestore.Increment(wh),
                "total_grams_CO2": firestore.Increment(gco2),
                "total_mL_water": firestore.Increment(h2o),
            }

            # Auto-initialise the limit field for existing users (count is
            # now managed by check_and_reserve_gemini_pro_quota)
            if "gemini_pro_usage_limit" not in data:
                increments["gemini_pro_usage_limit"] = GEMINI_PRO_DEFAULT_LIMIT

            user_ref.update({
                **increments,
                "last_processed_at": firestore.SERVER_TIMESTAMP,
                "monthly_usage": monthly_usage,
                "daily_usage": daily_usage,
                "ocr_info": ocr_info,
                "llm_info": llm_info,
            })

        else:
            # Create new document (no backfill needed yet)
            monthly_usage = {current_month: 1}
            daily_usage = {current_day: 1}

            ocr_info = {}
            if engines:
                for engine in engines:
                    if engine:
                        ocr_info[engine] = 1

            llm_info = {}
            if llm_model_name:
                llm_info[llm_model_name] = 1

            # Use merge=True so we don't overwrite gemini_pro_usage_count
            # that was already set by check_and_reserve_gemini_pro_quota
            user_ref.set({
                "user_email": user_email,
                "first_processed_at": firestore.SERVER_TIMESTAMP,
                "last_processed_at": firestore.SERVER_TIMESTAMP,
                "total_images_processed": 1,
                "monthly_usage": monthly_usage,
                "daily_usage": daily_usage,
                "ocr_info": ocr_info,
                "llm_info": llm_info,
                "total_tokens_all": t_all,
                "total_watt_hours": wh,
                "total_grams_CO2": gco2,
                "total_mL_water": h2o,
                "backfill_applied_v2": True,  # Nothing to backfill yet
                "backfill_tokens": backfill_tokens,
                "last_impact_snapshot": est_impact,
                "gemini_pro_usage_limit": GEMINI_PRO_DEFAULT_LIMIT,
            }, merge=True)

        logger.info(f"Updated usage statistics for {user_email}")

        # ── Admin email alerts ───────────────────────────────────────
        _send_daily_usage_alerts(user_email, current_day,
                                 prev_daily_count if doc.exists else 0)

    except Exception as e:
        logger.error(f"Error updating usage statistics: {str(e)}")

def resize_image_to_max_pixels(image, max_pixels=5200000):
    """
    Resize an image to have no more than max_pixels while maintaining aspect ratio.
    
    Args:
        image (PIL.Image): The image to resize
        max_pixels (int): Maximum number of pixels allowed (default: 5,000,000 = 5 megapixels)
    
    Returns:
        PIL.Image: Resized image or original image if no resize needed
    """
    # Get current dimensions
    width, height = image.size
    current_pixels = width * height
    
    # If image is already within limits, return as-is
    if current_pixels <= max_pixels:
        return image
    
    # Calculate the scale factor needed
    scale_factor = math.sqrt(max_pixels / current_pixels)
    
    # Calculate new dimensions
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)
    
    # Ensure we don't exceed the pixel limit due to rounding
    while new_width * new_height > max_pixels:
        if new_width > new_height:
            new_width -= 1
        else:
            new_height -= 1
    
    # Resize the image using high-quality resampling
    resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    logger.debug(f"Image resized: {width}x{height} -> {new_width}x{new_height}")
    
    return resized_image

MAX_PDF_PAGES = 200

def convert_pdf_to_page_images(pdf_bytes, pdf_filename, dpi=150):
    """
    Convert each page of a PDF to an in-memory JPEG FileStorage object.

    Args:
        pdf_bytes: Raw bytes of the PDF file.
        pdf_filename: Original filename (e.g., "specimen.pdf").
        dpi: Rendering resolution. 150 balances OCR quality vs size.

    Returns:
        List of FileStorage objects, one per page, named like
        {pdf_stem}__page_0001.jpg, {pdf_stem}__page_0002.jpg, etc.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_files = []
    base_name = os.path.splitext(pdf_filename)[0]

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("jpeg")
        page_filename = f"{base_name}__page_{page_num + 1:04d}.jpg"
        file_obj = FileStorage(
            stream=io.BytesIO(img_bytes),
            filename=page_filename,
            content_type='image/jpeg'
        )
        page_files.append(file_obj)

    doc.close()
    return page_files

def process_uploaded_file_with_resize(file, max_pixels=5200000):
    """
    Process an uploaded file, resize if necessary, and return a new file-like object.
    
    Args:
        file: Flask uploaded file object
        max_pixels (int): Maximum number of pixels allowed
    
    Returns:
        FileStorage: New file object with resized image, or original if no resize needed
    """
    try:
        # Open the image
        image = Image.open(file.stream)
        original_filename = file.filename
        
        # Check if resize is needed
        width, height = image.size
        current_pixels = width * height

        is_heic = original_filename and original_filename.lower().endswith(('.heic', '.heif'))
        if current_pixels <= max_pixels and not is_heic:
            file.stream.seek(0)
            return file

        
        # if current_pixels <= max_pixels:
        #     # No resize needed, reset stream position and return original
        #     file.stream.seek(0)
        #     return file
        
        # Resize the image
        resized_image = resize_image_to_max_pixels(image, max_pixels)
        
        # Save resized image to bytes
        img_byte_array = io.BytesIO()
        
        # Determine format - default to JPEG for compatibility
        image_format = 'JPEG'
        if original_filename and original_filename.lower().endswith('.png'):
            image_format = 'PNG'
        elif original_filename and original_filename.lower().endswith(('.jpg', '.jpeg')):
            image_format = 'JPEG'
        
        # Convert to RGB if necessary for JPEG
        if image_format == 'JPEG':
            if resized_image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', resized_image.size, (255, 255, 255))
                if resized_image.mode == 'P':
                    resized_image = resized_image.convert('RGBA')
                background.paste(resized_image, mask=resized_image.split()[-1] if resized_image.mode == 'RGBA' else None)
                resized_image = background
            elif resized_image.mode != 'RGB':
                resized_image = resized_image.convert('RGB')
        
        # Save with high quality
        save_kwargs = {'format': image_format}
        if image_format == 'JPEG':
            save_kwargs['quality'] = 95
            save_kwargs['optimize'] = True
        
        resized_image.save(img_byte_array, **save_kwargs)
        img_byte_array.seek(0)
        
        # Create new FileStorage object
        from werkzeug.datastructures import FileStorage
        
        # Update filename if format changed
        if image_format == 'JPEG' and original_filename and not original_filename.lower().endswith(('.jpg', '.jpeg')):
            name_without_ext = os.path.splitext(original_filename)[0]
            original_filename = f"{name_without_ext}.jpg"
        
        resized_file = FileStorage(
            stream=img_byte_array,
            filename=original_filename,
            content_type=f'image/{image_format.lower()}'
        )
        
        return resized_file
        
    except Exception as e:
        logger.error(f"Error processing image for resize: {e}")
        # If there's an error, return the original file
        file.stream.seek(0)
        return file
    
def process_url_image_with_resize(image_url, max_pixels=5000000):
    """
    Download and resize an image from URL if necessary.
    
    Args:
        image_url (str): URL of the image
        max_pixels (int): Maximum number of pixels allowed
    
    Returns:
        tuple: (FileStorage object, filename)
    """
    try:        
        # Download the image
        response = requests.get(image_url, stream=True, timeout=60, headers={"User-Agent": APP_USER_AGENT})
        if response.status_code == 403:
            logger.error(
                f"403 Forbidden for {image_url}\n"
                f"  Response Headers: {dict(response.headers)}\n"
                f"  Response Body (first 500 chars): {response.text[:500]}\n"
                f"  Request User-Agent: {response.request.headers.get('User-Agent', 'N/A')}"
            )
        response.raise_for_status()
        
        # Get filename from URL
        filename = extract_filename_from_url(image_url)
        
        # Open image from response content
        image = Image.open(io.BytesIO(response.content))
        
        # Check if resize is needed
        width, height = image.size
        current_pixels = width * height
        is_heic = filename and filename.lower().endswith(('.heic', '.heif'))

        if current_pixels <= max_pixels and not is_heic:
            # No resize needed, create FileStorage from original content
            file_obj = FileStorage(
                stream=io.BytesIO(response.content),
                filename=filename,
                content_type=response.headers.get('Content-Type', 'image/jpeg')
            )
            return file_obj, filename
        
        # Resize the image (returns original if already within pixel limit)
        resized_image = resize_image_to_max_pixels(image, max_pixels)
        
        # Save resized image to bytes
        img_byte_array = io.BytesIO()
        
        # Determine format - HEIC always converts to JPEG
        image_format = 'JPEG'
        if filename and filename.lower().endswith('.png'):
            image_format = 'PNG'
        
        # Convert to RGB if necessary for JPEG
        if image_format == 'JPEG':
            if resized_image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', resized_image.size, (255, 255, 255))
                if resized_image.mode == 'P':
                    resized_image = resized_image.convert('RGBA')
                background.paste(resized_image, mask=resized_image.split()[-1] if resized_image.mode == 'RGBA' else None)
                resized_image = background
            elif resized_image.mode != 'RGB':
                # Catches YCbCr, CMYK, etc. (common in HEIC)
                resized_image = resized_image.convert('RGB')
        
        # Save with high quality
        save_kwargs = {'format': image_format}
        if image_format == 'JPEG':
            save_kwargs['quality'] = 95
            save_kwargs['optimize'] = True
        
        resized_image.save(img_byte_array, **save_kwargs)
        img_byte_array.seek(0)
        
        # Update filename if format changed (covers HEIC -> JPEG rename)
        if image_format == 'JPEG' and filename and not filename.lower().endswith(('.jpg', '.jpeg')):
            name_without_ext = os.path.splitext(filename)[0]
            filename = f"{name_without_ext}.jpg"
        
        # Create FileStorage object
        file_obj = FileStorage(
            stream=img_byte_array,
            filename=filename,
            content_type=f'image/{image_format.lower()}'
        )
        
        return file_obj, filename
        
    except Exception as e:
        logger.error(f"Error processing URL image for resize: {e}")
        raise

class SimpleEmailSender:
    """
    A simple class to send emails using Gmail SMTP with credentials from environment variables
    """
    def __init__(self):
        # Setup logger
        self.logger = logging.getLogger('EmailSender')
        
        # Get credentials from environment variables
        self.smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.from_email = os.environ.get('SMTP_USERNAME')  # Gmail address
        self.password = os.environ.get('SMTP_PASSWORD')    # Gmail password
        self.from_name = os.environ.get('FROM_NAME', 'VoucherVision API')
        
        # Check if email sending is enabled
        self.is_enabled = all([
            self.smtp_server,
            self.smtp_port,
            self.from_email,
            self.password
        ])
        
        if not self.is_enabled:
            self.logger.warning("Email sending is disabled due to missing configuration")
            missing = []
            if not self.smtp_server: missing.append('SMTP_SERVER')
            if not self.smtp_port: missing.append('SMTP_PORT')
            if not self.from_email: missing.append('SMTP_USERNAME')
            if not self.password: missing.append('SMTP_PASSWORD')
            if missing:
                self.logger.warning(f"Missing environment variables: {', '.join(missing)}")
    
    def send_email(self, to_email, subject, body):
        """
        Send a simple email
        
        Args:
            to_email (str): Recipient email address
            subject (str): Email subject
            body (str): Email body (HTML or plain text)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_enabled:
            self.logger.warning(f"Email not sent to {to_email}: Email sending is disabled")
            return False
        
        try:
            # Create a multipart message
            msg = MIMEMultipart()
            msg['From'] = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Determine if body is HTML or plain text
            if body.strip().startswith('<'):
                # Looks like HTML
                msg.attach(MIMEText(body, 'html'))
            else:
                # Plain text
                msg.attach(MIMEText(body, 'plain'))
            
            # Connect to the SMTP server and send the email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(self.from_email, self.password)
                server.send_message(msg)
            
            self.logger.info(f"Email sent to {to_email}: {subject}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def send_approval_notification(self, user_email):
        """
        Send application approval notification email
        
        Args:
            user_email (str): The recipient's email address
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        subject = "Your VoucherVision API Application has been Approved"
        
        # Create HTML content
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4285f4;">Application Approved</h2>
                    <p>Dear {user_email},</p>
                    <p>We're pleased to inform you that your application for access to the VoucherVision API has been approved.</p>
                    <p>You can now log in to your account and access the API through our web interface or via API tokens.</p>
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vouchervision-go-738307415303.us-central1.run.app/auth-success" 
                           style="background-color: #4285f4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                            Access Your Account
                        </a>
                    </div>
                    <p>If you have any questions or need assistance, please don't hesitate to contact us.</p>
                    <p>Thank you for your interest in VoucherVision!</p>
                    <p>Best regards,<br>The VoucherVision Team</p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body)
    
    def send_api_key_permission_notification(self, user_email):
        """
        Send API key permission granted notification email
        
        Args:
            user_email (str): The recipient's email address
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        subject = "API Key Access Granted for VoucherVision"
        
        # Create HTML content
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4285f4;">API Key Access Granted</h2>
                    <p>Dear {user_email},</p>
                    <p>We're pleased to inform you that you have been granted permission to create API keys for programmatic access to the VoucherVision API.</p>
                    <p>API keys allow your applications to authenticate with our API without browser-based authentication, enabling automated workflows and integrations.</p>
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vouchervision-go-738307415303.us-central1.run.app/api-key-management" 
                           style="background-color: #4285f4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                            Manage Your API Keys
                        </a>
                    </div>
                    <p>Please remember to keep your API keys secure and never share them publicly. You can revoke and manage your keys at any time through the API Key Management page.</p>
                    <p>If you have any questions about using API keys or need technical assistance, please contact us.</p>
                    <p>Best regards,<br>The VoucherVision Team</p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body)
    
    def send_application_submission_notification(self, user_email, organization, purpose):
        """
        Send notification to admin about a new application submission
        
        Args:
            user_email (str): The email of the user who submitted the application
            organization (str): The organization the user belongs to
            purpose (str): The purpose for API access as described by the user
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        subject = "New VoucherVision API Application Submitted"
        
        # Create HTML content
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4285f4;">New Application Received</h2>
                    <p>A new application for VoucherVision API access has been submitted.</p>
                    
                    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #333;">Application Details</h3>
                        <p><strong>Email:</strong> {user_email}</p>
                        <p><strong>Organization:</strong> {organization}</p>
                        <p><strong>Purpose:</strong> {purpose}</p>
                    </div>
                    
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vouchervision-go-738307415303.us-central1.run.app/admin" 
                          style="background-color: #4285f4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                            Review Application
                        </a>
                    </div>
                    
                    <p>Please review this application at your earliest convenience.</p>
                    <p>Best regards,<br>VoucherVision Notification System</p>
                </div>
            </body>
        </html>
        """
        
        # Send to the same email address configured for sending
        # This assumes the admin's email is the same as the sender email
        admin_email = self.from_email

        return self.send_email(admin_email, subject, body)

    def send_admin_usage_alert(self, subject_line, detail_html):
        """Send a usage-related alert email to the admin.

        Args:
            subject_line (str): Email subject (prefixed with [VoucherVision])
            detail_html (str): HTML snippet placed inside the alert card body
        Returns:
            bool: True if sent successfully
        """
        subject = f"[VoucherVision] {subject_line}"
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #e53935;">Usage Alert</h2>
                    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px; margin: 20px 0;">
                        {detail_html}
                    </div>
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vouchervision-go-738307415303.us-central1.run.app/admin"
                           style="background-color: #4285f4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                            Open Admin Dashboard
                        </a>
                    </div>
                    <p>Best regards,<br>VoucherVision Notification System</p>
                </div>
            </body>
        </html>
        """
        admin_email = self.from_email
        return self.send_email(admin_email, subject, body)

def create_initial_admin(email):
    """Create the initial admin user"""
    try:
        # Check if admin already exists
        admin_doc = db.collection('admins').document(email).get()
        
        if admin_doc.exists:
            logger.info(f"Admin {email} already exists")
            return
        
        # Create admin record
        admin_data = {
            'added_by': 'System',
            'added_at': firestore.SERVER_TIMESTAMP,
            'is_super_admin': True  # This is the initial admin, give them super admin status
        }
        
        db.collection('admins').document(email).set(admin_data)
        
        # Create an approved application for the admin
        app_data = {
            'email': email,
            'organization': 'System Administrator',
            'purpose': 'System administration',
            'status': 'approved',
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'approved_by': 'System',
            'approved_at': firestore.SERVER_TIMESTAMP,
            'notes': ['Automatically created as initial admin']
        }
        
        db.collection('user_applications').document(email).set(app_data)
        
        logger.info(f"Created initial admin: {email}")
        
    except Exception as e:
        logger.error(f"Error creating initial admin: {str(e)}")
        raise

# Authentication middleware function
def authenticate_request(request):
    """Verify Firebase ID token from various sources."""
    # Check in Authorization header
    auth_header = request.headers.get('Authorization', '')
    id_token = None
    
    if auth_header.startswith('Bearer '):
        id_token = auth_header.split('Bearer ')[1]
    
    # If not in query, check in cookies
    if not id_token:
        id_token = request.cookies.get('auth_token')
    
    if not id_token:
        return None
        
    try:
        # Verify the token
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        return None

def get_user_email_from_request(request):
    """
    Get the user email from an already authenticated request.
    This function assumes authentication has already been performed by authenticate_request.
    
    Args:
        request: The Flask request object
        
    Returns:
        str: The user's email address, or 'unknown' if not found
    """
    user_email = 'unknown'
    
    try:
        # Check for API key first in header
        api_key = request.headers.get('X-API-Key')
        
        # Also check for API key in query parameters
        if not api_key:
            api_key = request.args.get('api_key')
        
        if api_key:
            # Get the API key document
            api_key_doc = db.collection('api_keys').document(api_key).get()
            
            if api_key_doc.exists:
                key_data = api_key_doc.to_dict()
                user_email = key_data.get('owner', 'unknown')
                logger.debug(f"API key auth: {user_email}")
                return user_email
        
        # Check for Firebase token
        auth_header = request.headers.get('Authorization', '')
        id_token = None
        
        if auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]
        
        # If not in header, check in query parameters
        if not id_token:
            id_token = request.args.get('token')
        
        # If not in query, check in cookies
        if not id_token:
            id_token = request.cookies.get('auth_token')
        
        if id_token:
            # Just get the email from the token without re-validating
            # This relies on the authenticate_request middleware having already validated the token
            try:
                # Get info about the token without full verification
                decoded_claims = auth.verify_id_token(id_token, check_revoked=False)
                user_email = decoded_claims.get('email', 'unknown')
                logger.debug(f"Firebase auth: {user_email}")
            except Exception as e:
                logger.error(f"Error getting email from token: {e}")
        
    except Exception as e:
        logger.error(f"Error getting user email: {e}")
    
    return user_email

def authenticated_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # For OPTIONS requests, only return CORS headers without executing the route function
        if request.method == 'OPTIONS':
            response = make_response()
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
            response.headers.add('Access-Control-Allow-Methods', 'GET,POST')
            response.headers.add('Access-Control-Max-Age', '3600')
            return response
            
        # For non-OPTIONS requests, proceed with authentication
        # Check for API key first in header
        api_key = request.headers.get('X-API-Key')
        
        # Also check for API key in query parameters (for easier testing)
        if not api_key:
            api_key = request.args.get('api_key')
        
        if api_key and validate_api_key(api_key):
            # API key is valid
            logger.debug(f"Authenticated via API key: {api_key[:8]}...")
            return f(*args, **kwargs)
        
        # Fall back to Firebase token authentication
        user = authenticate_request(request)
        if user:
            logger.debug(f"Authenticated via Firebase: {user.get('email', 'unknown')}")
            return f(*args, **kwargs)
        
        # Neither authentication method succeeded
        logger.warning(f"Authentication failed from IP: {request.remote_addr}")
        return jsonify({'error': 'Unauthorized - Valid authentication required (Firebase token or API key)'}), 401
    
    return decorated_function


class RequestThrottler:
    """
    Class to handle throttling of concurrent requests
    """
    def __init__(self, max_concurrent=32): 
        self.semaphore = threading.Semaphore(max_concurrent)
        self.active_count = 0
        self.lock = threading.Lock()
        self.max_concurrent = max_concurrent
        
    def acquire(self):
        """Acquire a slot for processing"""
        acquired = self.semaphore.acquire(blocking=False)
        if acquired:
            with self.lock:
                self.active_count += 1
                logger.debug(f"Request acquired. Active: {self.active_count}/{self.max_concurrent}")
        return acquired

    def release(self):
        """Release a processing slot"""
        self.semaphore.release()
        with self.lock:
            self.active_count -= 1
            logger.debug(f"Request released. Active: {self.active_count}/{self.max_concurrent}")
    
    def get_active_count(self):
        """Get the current count of active requests"""
        with self.lock:
            return self.active_count

class VoucherVisionProcessor:
    """
    Class to handle VoucherVision processing with initialization done once.
    """
    def __init__(self, app_logger=None, max_concurrent=32):
        # Setup logging
        if app_logger and hasattr(app_logger, 'info'):
            self.logger = app_logger
            self.use_console_fallback = False
        else:
            self.logger = logging.getLogger(__name__)
            self.use_console_fallback = not self.logger.handlers and self.logger.level == 0

        self._log("Initializing VoucherVisionProcessor...", "info")

        # Configuration
        self.ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'tif', 'tiff', 'heic', 'heif', 'pdf'}
        self.MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max upload size (increased for multi-page PDFs)
        
        # Initialize request throttler
        self.throttler = RequestThrottler(max_concurrent)
        self.collage_engine_lock = threading.Lock()
        
        # Get API key for Gemini
        try:
            self.api_key = self._get_api_key()
            self._log("API key retrieved successfully", "info")
        except Exception as e:
            self._log(f"Failed to get API key: {e}", "error")
            raise
        
        # OCR engines are lazily initialized on first use (see ocr_engines_lock below)
        self.ocr_engines = {}
        self.ocr_engines_lock = threading.Lock()

        # Initialize CollageEngine
        self.collage_engine = None
        try:
            model_path = os.path.join(project_root, "TextCollage", "models", "openvino", "best.xml")
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"CollageEngine model not found at {model_path}")

            self.collage_engine = CollageEngine(
                model_xml_path=model_path,
                collage_classes=['barcode', 'label', 'map'], # Classes to RENDER in the collage
                engine="gemini", # No resizing, use original resolution
                output_path=None, # Force return in-memory
                hide_long_objects=False, # Sensible default for clean OCR input
                draw_overlay=False
            )
            self._log("CollageEngine initialized", "info")
        except Exception as e:
            self._log(f"Failed to initialize CollageEngine: {e}", "error")

        # Load VoucherVision config
        self.config_file = os.path.join(os.path.dirname(__file__), 'VoucherVision.yaml')
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"Configuration file not found at {self.config_file}")

        self.cfg = load_custom_cfg(self.config_file)
        self.dir_home = os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main"))

        # Initialize VoucherVision
        self.Voucher_Vision = VoucherVision(
            self.cfg, self.logger, self.dir_home, None, None, None,
            is_hf=False, skip_API_keys=True
        )
        self.Voucher_Vision.initialize_token_counters()

        # Set default prompt
        self.default_prompt = "SLTPvM_default.yaml"
        self.custom_prompts_dir = os.path.join(self.dir_home, 'custom_prompts')
        self.Voucher_Vision.path_custom_prompts = os.path.join(
            self.dir_home, 'custom_prompts', self.default_prompt
        )

        # Initialize LLM models
        self.Voucher_Vision.setup_JSON_dict_structure()
        self.llm_models = {}
        for model_name in ["gemini-1.5-pro", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-pro-preview"]:
            self.llm_models[model_name] = GoogleGeminiHandler(
                self.cfg, self.logger, model_name, self.Voucher_Vision.JSON_dict_structure,
                config_vals_for_permutation=None, exit_early_for_JSON=True
            )
        self._log(f"Initialized {len(self.ocr_engines)} OCR engines, {len(self.llm_models)} LLM models", "info")

        self.thread_local = threading.local()
        self._log("VoucherVisionProcessor ready", "info")
    
    def _log(self, message, level="info"):
        """Log a message at the given level"""
        log_fn = getattr(self.logger, level, self.logger.info)
        try:
            log_fn(message)
        except Exception:
            pass
    
    def _add_tokens(self, tokens_in, tokens_out, ocr_tokens_total) -> float:
        """
        Safely sums any of the three token counts.
        Accepts int, float, or numeric strings; treats None and "" as 0.0.
        """
        def to_number(x):
            if x in (None, ""):
                return 0.0
            try:
                return float(x)
            except (ValueError, TypeError):
                return 0.0

        return to_number(tokens_in) + to_number(tokens_out) + to_number(ocr_tokens_total)

    def _get_api_key(self):
        """Get API key from environment variable"""
        api_key = os.environ.get("API_KEY")
        if not api_key:
            raise ValueError("API_KEY environment variable not set")
        return api_key
    
    # def _sanitize_text(self, s: str) -> str: 
    #     DANGER_PREFIXES = ("=", "+", "-", "@") # Excel formula-injection set 
        
    #     if not isinstance(s, str): return s
    #     # 1) collapse newlines to spaces, 
    #     # 2) drop §, «, » 
    #     s = re.sub(r'[\r\n]+', ' ', s)
    #     s = s.replace('§', '').replace('«', '').replace('»', '') 
    #     s = s.replace('<', '').replace('>', '').replace('~', '') 
    #     if s and s[0] in DANGER_PREFIXES: 
    #         s = "'" + s 
    #     # also collapse multiple spaces that may result 
    #     s = re.sub(r'\s{2,}', ' ', s).strip() 
    #     return s 
    
    # def _sanitize_obj(self, obj): 
    #     """Recursively sanitize strings in dict/list/tuple structures.""" 
    #     if isinstance(obj, dict): 
    #         return {k: self._sanitize_obj(v) for k, v in obj.items()} 
    #     if isinstance(obj, list): return [self._sanitize_obj(v) for v in obj] 
    #     if isinstance(obj, tuple): return tuple(self._sanitize_obj(v) for v in obj) 
    #     if isinstance(obj, (str,)): return self._sanitize_text(obj) 
    #     # if the LLM returns a JSON string, try to sanitize the string version return obj 
    
    # def _strip_ocr_headers(self, s: str) -> str: 
    #     if not isinstance(s, str): return s 
    #     # 1) Drop lines like "gemini-2.0-flash OCR:" (case-insensitive, any leading spaces) 
    #     s = re.sub( r'(?im)^\s*gemini-(?:\d+(?:\.\d+)?)-(?:flash|pro)\s+OCR:\s*\n?', '', s, )
    #     # 2) Remove the exact known strings (defensive—covers historical variants) 
    #     exact_headers = [ "gemini-2.0-flash OCR:", "gemini-2.5-flash OCR:", "gemini-1.5-pro OCR:", "gemini-2.5-pro OCR:", "gemini-3.0-flash OCR:", "gemini-3.0-pro OCR:", ] 
    #     for h in exact_headers: 
    #         s = s.replace(h, '') 
    #     # 3) Remove bare model-name mentions anywhere in the text 
    #     s = re.sub( r'(?i)\bgemini-(?:\d+(?:\.\d+)?)-(?:flash|pro)\b', '', s, ) 
    #     # Also remove the exact bare names 
    #     bare_models = [ "gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.5-pro", "gemini-3.0-flash", "gemini-3.0-pro", ] 
    #     for m in bare_models: 
    #         s = s.replace(m, '') 
    #     return s

    def _sanitize_formatted_json(self, vv_results):
        """
        Ensure VoucherVision's JSON payload is deeply sanitized for storage/export.

        Behavior:
        - If vv_results is JSON (dict/list/tuple or JSON string): deep-sanitize and
        RETURN THE PYTHON OBJECT (no json.dumps here).
        - If vv_results is a non-JSON string: sanitize as text and return a plain string.
        - If scalar: sanitize and return the scalar.
        """
        # Case 1: already a Python object (dict/list/tuple)
        if isinstance(vv_results, (dict, list, tuple)):
            return sanitize_excel_record(vv_results)

        # Case 2: string that may be JSON
        if isinstance(vv_results, str):
            try:
                parsed = json.loads(vv_results)
            except Exception:
                # Not valid JSON → sanitize as text-ish block, return string
                return sanitize_for_storage(vv_results)
            else:
                # Valid JSON string → sanitize object, return object
                return sanitize_excel_record(parsed)

        # Case 3: other scalar (rare)
        return sanitize_excel_record(vv_results)
    
    def allowed_file(self, filename):
        """Check if file has allowed extension"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS
    
    def perform_ocr(self, file_path, engine_options, ocr_prompt_option, user_api_key=None):
        """Perform OCR on the provided image"""
        ocr_packet = {}
        ocr_all = ""
        ocr_tokens_total = 0
        
        for i, ocr_opt in enumerate(engine_options):
            ocr_packet[ocr_opt] = {}
            self._log(f"ocr_opt {ocr_opt}", "info")
            
            if user_api_key:
                # Per-request throwaway engine - never touches the shared pool
                OCR_Engine = OCRGeminiProVision(
                    user_api_key,
                    model_name=ocr_opt,
                    max_output_tokens=32768,
                    temperature=1.0,
                    top_p=0.95,
                    seed=123456,
                    do_resize_img=False
                )
            else:
                # Use the shared, pre-warmed server engine
                if ocr_opt not in self.ocr_engines:
                    with self.ocr_engines_lock:
                        if ocr_opt not in self.ocr_engines:
                            self.ocr_engines[ocr_opt] = OCRGeminiProVision(
                                self.api_key,
                                model_name=ocr_opt,
                                max_output_tokens=32768,
                                temperature=1,
                                top_p=0.95,
                                seed=123456,
                                do_resize_img=False
                            )
                OCR_Engine = self.ocr_engines[ocr_opt]
            
            # Execute OCR (this API call can run concurrently)
            response, cost_in, cost_out, total_cost, rates_in, rates_out, tokens_in, tokens_out = OCR_Engine.ocr_gemini(file_path, prompt=ocr_prompt_option)
            
            ocr_packet[ocr_opt]["ocr_text"] = response
            ocr_packet[ocr_opt]["cost_in"] = cost_in
            ocr_packet[ocr_opt]["cost_out"] = cost_out
            ocr_packet[ocr_opt]["total_cost"] = total_cost
            ocr_packet[ocr_opt]["rates_in"] = rates_in
            ocr_packet[ocr_opt]["rates_out"] = rates_out
            ocr_packet[ocr_opt]["tokens_in"] = tokens_in
            ocr_packet[ocr_opt]["tokens_out"] = tokens_out

            # ocr_all += f"{ocr_opt} OCR: {response} "
            # ocr_all += f"OCR Version {i}: {response} "
            ocr_all += f"{response} "
            ocr_tokens_total += self._add_tokens(tokens_in, tokens_out, 0)

        return ocr_packet, ocr_all, ocr_tokens_total
    
    def get_thread_local_vv(self, prompt, llm_model_name, user_api_key=None):
        """Get or create a thread-local VoucherVision instance with the specified prompt"""
        needs_new = (
            not hasattr(self.thread_local, 'vv')
            or user_api_key is not None
            or prompt != getattr(self.thread_local, 'prompt', None)
            or llm_model_name != getattr(self.thread_local, 'llm_model_name', None)
        )

        if needs_new:
            self.thread_local.vv = VoucherVision(
                self.cfg, self.logger, self.dir_home, None, None, None,
                is_hf=False, skip_API_keys=True
            )
            self.thread_local.vv.initialize_token_counters()
            self.thread_local.vv.path_custom_prompts = os.path.join(
                self.custom_prompts_dir, prompt
            )
            self.thread_local.vv.setup_JSON_dict_structure()
            self.thread_local.prompt = prompt
            self.thread_local.llm_model_name = llm_model_name

            self.thread_local.llm_model = GoogleGeminiHandler(
                self.cfg, self.logger, llm_model_name,
                self.thread_local.vv.JSON_dict_structure,
                config_vals_for_permutation=None,
                exit_early_for_JSON=True,
                api_key=user_api_key,  # None = use env, key = use theirs
            )
            self._log(f"Created new thread-local VV instance with prompt: {prompt}", "info")

        return self.thread_local.vv, self.thread_local.llm_model
    
    def process_voucher_vision(self, ocr_text, prompt, llm_model_name, LLM_name_cost, user_api_key=None):
        """Process the OCR text with VoucherVision using a thread-local instance"""
        # Get thread-local VoucherVision instance with the correct prompt
        vv, llm_model = self.get_thread_local_vv(prompt, llm_model_name, user_api_key=user_api_key)

        # Update OCR text for processing
        prompt_text = vv.setup_prompt(ocr_text)

        # Call the LLM to process the OCR text
        response_candidate, nt_in, nt_out, _, _, _ = llm_model.call_llm_api_GoogleGemini(
            prompt_text, json_report=None, paths=None
        )
        self._log(f"response_candidate\n{response_candidate}", "info")
        cost_in, cost_out, parsing_cost, rate_in, rate_out = calculate_cost(LLM_name_cost, os.path.join(self.dir_home, 'api_cost', 'api_cost.yaml'), nt_in, nt_out)

        return response_candidate, nt_in, nt_out, cost_in, cost_out

    def process_pdf_request(self, file, **kwargs):
        """
        Process a PDF file by converting each page to a JPG and running
        the standard image pipeline on each page.

        Returns (result_dict, status_code) where result_dict contains
        a 'pages' list with per-page results.
        """
        pdf_bytes = file.read()
        pdf_filename = file.filename

        try:
            page_files = convert_pdf_to_page_images(pdf_bytes, pdf_filename, dpi=150)
        except Exception as e:
            self._log(f"PDF conversion failed for {pdf_filename}: {e}", "error")
            return {'error': f'Failed to convert PDF: {str(e)}'}, 400

        if not page_files:
            return {'error': 'PDF contains no pages'}, 400
        if len(page_files) > MAX_PDF_PAGES:
            return {'error': f'PDF has {len(page_files)} pages, maximum allowed is {MAX_PDF_PAGES}'}, 400

        self._log(f"PDF '{pdf_filename}' has {len(page_files)} pages, processing each as a separate image", "info")

        page_results = []
        for page_file in page_files:
            # Resize each page-image just like a normal upload
            try:
                page_file = process_uploaded_file_with_resize(page_file, max_pixels=5200000)
            except Exception as e:
                self._log(f"Resize failed for {page_file.filename}: {e}", "error")
                page_results.append({
                    'filename': page_file.filename,
                    'error': f'Image resize failed: {str(e)}',
                    'status_code': 500
                })
                continue

            result, status_code = self.process_image_request(file=page_file, **kwargs)
            if status_code != 200:
                page_results.append({
                    'filename': page_file.filename,
                    'error': result.get('error', 'Unknown error'),
                    'status_code': status_code
                })
            else:
                result['filename'] = page_file.filename
                page_results.append(result)

        return OrderedDict([
            ('source_pdf', pdf_filename),
            ('page_count', len(page_files)),
            ('pages', page_results),
        ]), 200

    def process_image_request(self, file,
                              engine_options=None,
                              ocr_prompt_option=None,
                              prompt=None,
                              ocr_only=False,
                              include_wfo=False,
                              include_cop90=False,
                              llm_model_name=None,
                              url_source="",
                              notebook_mode=False,
                              skip_label_collage=False,
                              user_api_key=None):
        """
        Process an image from a request file
        ocr_prompt_option=["verbatim_with_annotations", None]
        None will use the default LLM ocr, *anything* else will use the "verbatim"
        """
        # Check if we can accept this request based on throttling
        if not self.throttler.acquire():
            return {'error': 'Server is at maximum capacity. Please try again later.'}, 429
        
        original_temp_path = None
        collage_temp_path = None
        try:
            if notebook_mode:
                ocr_only = True

            # Check if the file is valid
            if file.filename == '':
                return {'error': 'No file selected'}, 400
            
            if not self.allowed_file(file.filename):
                return {'error': f'File type not allowed. Supported types: {", ".join(self.ALLOWED_EXTENSIONS)}'}, 400
            
            # --- STAGE 1: COLLAGE ENGINE PRE-PROCESSING ---
            if not self.collage_engine:
                return {'error': 'Collage Engine is not available on the server.'}, 503
            
            # Save uploaded file to a temporary location
            temp_dir = tempfile.mkdtemp()
            original_temp_path = os.path.join(temp_dir, f"original_{secure_filename(file.filename)}")
            file.save(original_temp_path)

            # Encode the (possibly resized) original image as base64 for the response
            with open(original_temp_path, 'rb') as f_orig:
                base64image_input_resized = base64.b64encode(f_orig.read()).decode('utf-8')

            if not self.collage_engine:
                return {'error': 'Collage Engine is not available on the server.'}, 503

            collage_resize_method = "gemini"

            with self.collage_engine_lock:
                if notebook_mode:
                    self._log("[notebook_mode] NOT Running CollageEngine for pre-processing... Using original image...", "info")
                    collage_json_data = self.collage_engine.run_fake(original_temp_path)
                elif skip_label_collage:
                    self._log("[skip_label_collage] NOT Running CollageEngine for pre-processing... Using original image...", "info")
                    collage_json_data = self.collage_engine.run_fake(original_temp_path)
                else:
                    self._log("Running CollageEngine for pre-processing...", "info")
                    collage_json_data = self.collage_engine.run(original_temp_path)

            collage_json_data['base64image_input_resized'] = base64image_input_resized

            if collage_json_data['base64image_text_collage'] is None:
                raise RuntimeError("CollageEngine failed to produce an image.")
            
            # Save the resulting collage image to a *new* temporary file for the OCR step
            # Decode the base64 string to bytes
            collage_image_bytes = base64.b64decode(collage_json_data['base64image_text_collage'])
            
            # Save the resulting collage image to a *new* temporary file for the OCR step
            collage_temp_path = os.path.join(temp_dir, f"collage_{secure_filename(file.filename)}")
            with open(collage_temp_path, 'wb') as f:
                f.write(collage_image_bytes)
            self._log(f"Collage created at {collage_temp_path}, proceeding to OCR.", "info")
            
           
            
            try:
                # Get engine options (default to gemini models if not specified)
                if engine_options is None:
                    if ocr_only:
                        engine_options = ["gemini-2.0-flash"]
                    else:
                        engine_options = ["gemini-2.0-flash"]

                if ocr_prompt_option is None:
                    if notebook_mode:
                        ocr_prompt_option = "verbatim_notebook"
                    elif ocr_only:
                        ocr_prompt_option = "verbatim_with_annotations"
                    else:
                        ocr_prompt_option = None

                # Simpler alternative approach
                if llm_model_name is None:
                    llm_model_name = "gemini-2.0-flash"

                # Direct mapping from API model names to cost constants
                api_to_cost_mapping = {
                    "gemini-2.0-flash": "GEMINI_2_0_FLASH",
                    "gemini-1.5-flash": "GEMINI_1_5_FLASH",
                    "gemini-1.5-pro": "GEMINI_1_5_PRO",
                    "gemini-2.5-flash": "GEMINI_2_5_FLASH",
                    "gemini-2.5-pro": "GEMINI_2_5_PRO",
                    # "gemini-3-pro": "GEMINI_3_PRO",
                    "gemini-3-pro-preview": "GEMINI_3_PRO",
                }

                self._log(f"Received llm_model_name: '{llm_model_name}' (type: {type(llm_model_name)})", "info")
                LLM_name_cost = api_to_cost_mapping.get(llm_model_name, "GEMINI_2_0_FLASH")
                self._log(f"Mapped to cost constant: {LLM_name_cost}", "info")

                # Use default prompt if none specified
                current_prompt = prompt if prompt else self.default_prompt
                self._log(f"Using prompt file: {current_prompt}", "info")
                self._log(f"file_path: {collage_temp_path}", "info")
                self._log(f"engine_options: {engine_options}", "info")
                self._log(f"llm_model_name: {llm_model_name}", "info")
                self._log(f"LLM_name_cost {LLM_name_cost}", "info")

                # Extract the original filename for the response
                original_filename = os.path.basename(file.filename)
                
                # Perform OCR
                ocr_info, ocr, ocr_tokens_total = self.perform_ocr(collage_temp_path, 
                                                                   engine_options, 
                                                                   ocr_prompt_option,
                                                                   user_api_key=user_api_key)

                # If ocr_only is True, skip VoucherVision processing
                if notebook_mode:
                    # In this mode "ocr" is actually md formatted, we need to remove that for the basic ocr field in the response
                    ocr_plain = markdown_to_simple_text(ocr, remove_headers=True, guard_excel=True)

                    self._log(f"Tokens: OCR={ocr_tokens_total}", "info")
                    est_impact = estimate_impact(ocr_tokens_total)

                    results = OrderedDict([
                        ("filename", original_filename),
                        ("url_source", url_source),
                        ("prompt", ocr_prompt_option),
                        ("ocr_info", ocr_info),
                        ("WFO_info", ""),
                        ("COP90_elevation_m", ""),
                        ("ocr", ocr_plain),
                        ("formatted_json", ""),
                        ("formatted_md", ocr),
                        ("parsing_info", OrderedDict([
                            ("model", ""),
                            ("input", 0),
                            ("output", 0),
                            ("cost_in", 0),
                            ("cost_out", 0),
                        ])),
                        ("impact", est_impact),
                        ("collage_info", collage_json_data),
                        ("collage_image_format", 'jpeg'),
                        ("success", {
                            "image_available": "True",
                            "text_collage": "False",
                            "text_collage_resize": f'{collage_resize_method}',
                            "ocr": "True",
                            "llm": "False",
                        }),
                    ])

                elif ocr_only:

                    ocr_info_sanitized = sanitize_excel_record(ocr_info)
                    ocr_sanitized = sanitize_for_storage(ocr)

                    self._log(f"Tokens: OCR={ocr_tokens_total}", "info")
                    est_impact = estimate_impact(ocr_tokens_total)

                    results = OrderedDict([
                        ("filename", original_filename),
                        ("url_source", url_source),
                        ("prompt", ocr_prompt_option),
                        ("ocr_info", ocr_info_sanitized),
                        ("WFO_info", ""),
                        ("COP90_elevation_m", ""),
                        ("ocr", ocr_sanitized),
                        ("formatted_json", ""),
                        ("formatted_md", ""),
                        ("parsing_info", OrderedDict([
                            ("model", ""),
                            ("input", 0),
                            ("output", 0),
                            ("cost_in", 0),
                            ("cost_out", 0),
                        ])),
                        ("impact", est_impact),
                        ("collage_info", collage_json_data),
                        ("collage_image_format", 'jpeg'),
                        ("success", {
                            "image_available": "True",
                            "text_collage": "True",
                            "text_collage_resize": f'{collage_resize_method}',
                            "ocr": "True",
                            "llm": "False",
                        }),
                    ])
                else:
                    # Process with VoucherVision
                    vv_results, tokens_in, tokens_out, cost_in, cost_out = self.process_voucher_vision(ocr,
                                                                                                       current_prompt,
                                                                                                       llm_model_name,
                                                                                                       LLM_name_cost,
                                                                                                       user_api_key=user_api_key)

                    # WFO taxonomy lookup (local SQLite database)
                    WFO = ""
                    if include_wfo and _wfo_lookup and isinstance(vv_results, dict):
                        try:
                            WFO = _wfo_lookup.check_wfo(vv_results, replace_if_success_wfo=False)
                            self._log(f"WFO Record: {WFO}", "info")
                        except Exception as e:
                            self._log(f"WFO lookup failed: {e}", "error")
                            WFO = _wfo_lookup.NULL_DICT

                    ocr_info_sanitized = sanitize_excel_record(ocr_info)
                    ocr_sanitized = sanitize_for_storage(ocr)
                    vv_results_sanitized = self._sanitize_formatted_json(vv_results)   

                    llm_tokens_total = self._add_tokens(tokens_in, tokens_out, ocr_tokens_total)    
                    self._log(f"Tokens: OCR={ocr_tokens_total}, LLM_in={tokens_in}, LLM_out={tokens_out}, total={llm_tokens_total}", "info")

                    est_impact = estimate_impact(llm_tokens_total)

                    results = OrderedDict([
                        ("filename", original_filename),
                        ("url_source", url_source),
                        ("prompt", current_prompt),
                        ("ocr_info", ocr_info_sanitized),
                        ("WFO_info", WFO),
                        ("COP90_elevation_m", ""),
                        ("ocr", ocr_sanitized),
                        ("formatted_json", vv_results_sanitized),
                        ("formatted_md", ""),
                        ("parsing_info", OrderedDict([
                            ("model", llm_model_name),
                            ("input", tokens_in),
                            ("output", tokens_out),
                            ("cost_in", cost_in),
                            ("cost_out", cost_out),
                        ])),
                        ("impact", est_impact),
                        ("collage_info", collage_json_data),
                        ("collage_image_format", 'jpeg'),
                        ("success", {
                            "image_available": "True",
                            "text_collage": "True",
                            "text_collage_resize": f'{collage_resize_method}',
                            "ocr": "True",
                            "llm": "True",
                        }),
                    ])
                
                if include_cop90:
                    try:
                        fj = results.get("formatted_json")
                        if isinstance(fj, dict):
                            lat_val = fj.get("decimalLatitude") or fj.get("decimal_latitude")
                            lon_val = fj.get("decimalLongitude") or fj.get("decimal_longitude")
                            elev = _elevation_lookup.query(float(lat_val), float(lon_val))
                            results["COP90_elevation_m"] = elev if elev is not None else ""
                    except Exception:
                        pass

                self._log(f"Processing completed successfully", "info")
                return results, 200
            
            except Exception as e:
                self._log(f"Error processing request: {e}", "error")
                import traceback
                self._log(f"Traceback: {traceback.format_exc()}", "error")
                return {'error': str(e)}, 500
            
            finally:
                # Clean up the temporary file
                try:
                    if original_temp_path and os.path.exists(original_temp_path):
                        os.remove(original_temp_path)
                    if collage_temp_path and os.path.exists(collage_temp_path):
                        os.remove(collage_temp_path)
                    if 'temp_dir' in locals() and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as cleanup_error:
                    self._log(f"Error during cleanup: {cleanup_error}", "warning")
        finally:
            # Release the throttling semaphore
            self.throttler.release()

def create_multipart_response(json_data, image_bytes):
    """Creates a multipart/form-data response containing both JSON and an image."""
    boundary = f"boundary--{uuid.uuid4()}"
    
    # Start the multipart body
    body = []
    
    # Part 1: JSON data
    body.append(f'--{boundary}')
    body.append('Content-Disposition: form-data; name="json_data"')
    body.append('Content-Type: application/json')
    body.append('')
    body.append(json.dumps(json_data, cls=OrderedJsonEncoder))
    
    # Part 2: Image data
    body.append(f'--{boundary}')
    body.append('Content-Disposition: form-data; name="image"; filename="collage.jpg"')
    body.append('Content-Type: image/jpeg')
    body.append('')
    # The image bytes need to be appended as raw bytes, not strings
    # So we join the text parts first, then append the bytes
    
    # Final boundary
    end_boundary = f'\r\n--{boundary}--\r\n'
    
    # Combine text parts
    text_parts = "\r\n".join(body) + "\r\n"
    
    # Create the full response body
    full_body = text_parts.encode('utf-8') + image_bytes + end_boundary.encode('utf-8')

    # Create and return the Flask response
    response = make_response(full_body)
    response.headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    return response

# Initialize Flask app
app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app, 
     origins=["*"],  # Allow all origins, or specify: ["https://leafmachine.org", "http://localhost:8000"]
     methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
     allow_headers=["Content-Type", "Authorization", "X-API-Key", "Accept"],
     supports_credentials=True,
     send_wildcard=False,
     vary_header=True
)

# Create a custom encoder that preserves order
class OrderedJsonEncoder(json.JSONEncoder):
    def __init__(self, **kwargs):
        kwargs['sort_keys'] = False
        super(OrderedJsonEncoder, self).__init__(**kwargs)

# Set the encoder immediately after creating the Flask app
app.json_encoder = OrderedJsonEncoder

try:
    # Create initial admin if specified
    initial_admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    if initial_admin_email:
        create_initial_admin(initial_admin_email)
except Exception as e:
    logger.error(f"Failed to create initial admin: {str(e)}")

# Initialize processor once at startup
try:
    processor = VoucherVisionProcessor(app.logger)
    app.config['processor'] = processor
    # Initialize email sender
    email_sender = SimpleEmailSender()
    app.config['email_sender'] = email_sender
    if not email_sender.is_enabled:
        app.logger.warning("Email sending disabled (missing SMTP config)")
    app.logger.info("Application initialized successfully")
except Exception as e:
    app.logger.error(f"Failed to initialize application components: {str(e)}")
    raise



class GCSElevationLookup:
    """
    Point-sample COP90 GeoTIFFs stored in Google Cloud Storage.
    Tiles are opened via GDAL's /vsigs/ virtual filesystem — no local copy needed.
    GDAL uses HTTP range requests so only the relevant raster blocks are fetched per query.
    """
    def __init__(self, gcs_bucket: str, gcs_prefix: str = "COP90", cache_size: int = 32):
        self.bucket = gcs_bucket
        self.prefix = gcs_prefix.rstrip("/")
        self._cache = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self._gdal_cred_file = self._prepare_gdal_credentials()

        # Configure GDAL via rasterio to use our temp file and suppress
        # GDAL's error logging (which would leak raw credentials)
        import rasterio
        gdal_opts = {"CPL_LOG": os.devnull}
        if self._gdal_cred_file:
            gdal_opts["GOOGLE_APPLICATION_CREDENTIALS"] = self._gdal_cred_file
        self._rasterio_env = rasterio.Env(**gdal_opts)
        self._rasterio_env.__enter__()
        import atexit
        atexit.register(self.close)

    def close(self):
        """Clean up rasterio env, cached datasets, and temp credential file."""
        with self._lock:
            for ds in self._cache.values():
                try:
                    ds.close()
                except Exception:
                    pass
            self._cache.clear()
        try:
            self._rasterio_env.__exit__(None, None, None)
        except Exception:
            pass
        if self._gdal_cred_file and self._gdal_cred_file.startswith(tempfile.gettempdir()):
            try:
                os.remove(self._gdal_cred_file)
            except OSError:
                pass

    @staticmethod
    def _prepare_gdal_credentials():
        """Write raw JSON credentials to a temp file for GDAL/rasterio.

        GOOGLE_APPLICATION_CREDENTIALS is left UNTOUCHED (VoucherVision's
        get_google_credentials() reads it and expects raw JSON).
        The returned file path is passed to rasterio.Env() only.

        CRITICAL: raw credentials must never appear in logs or tracebacks.
        """
        cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not cred:
            return None
        if os.path.isfile(cred):
            return cred
        if cred.lstrip().startswith("{"):
            try:
                fd, path = tempfile.mkstemp(suffix=".json", prefix="gdal_gcs_cred_")
                with os.fdopen(fd, "w") as f:
                    f.write(cred)
                app.logger.info("[elevation] Wrote GCS credentials to temp file for GDAL")
                return path
            except Exception:
                app.logger.error("[elevation] Failed to write GCS credential file")
                return None
            finally:
                cred = None  # noqa: F841
        return None

    def _tile_name(self, lat: float, lon: float) -> str:
        lat_deg = int(math.floor(lat))
        lon_deg = int(math.floor(lon))
        lat_h = "N" if lat_deg >= 0 else "S"
        lon_h = "E" if lon_deg >= 0 else "W"
        return (
            f"Copernicus_DSM_30_{lat_h}{abs(lat_deg):02d}_00"
            f"_{lon_h}{abs(lon_deg):03d}_00_DEM.tif"
        )

    def _open(self, tile_name: str):
        import rasterio
        path = f"/vsigs/{self.bucket}/{self.prefix}/{tile_name}"
        with self._lock:
            if path in self._cache:
                self._cache.move_to_end(path)
                return self._cache[path]
            ds = rasterio.open(path)
            self._cache[path] = ds
            self._cache.move_to_end(path)
            while len(self._cache) > self._cache_size:
                _, old = self._cache.popitem(last=False)
                try:
                    old.close()
                except Exception:
                    pass
            return ds

    def query(self, lat: float, lon: float):
        """Return elevation in metres as int, or None if tile missing or no-data."""
        try:
            tile = self._tile_name(lat, lon)
            ds = self._open(tile)
            val = float(next(ds.sample([(lon, lat)]))[0])
            if math.isnan(val):
                return None
            if ds.nodata is not None and val == float(ds.nodata):
                return None
            return round(val)
        except Exception:
            app.logger.warning(f"[elevation] query({lat},{lon}) failed")
            return None


GCS_ELEVATION_BUCKET = os.environ.get("COP90_GCS_BUCKET", "vouchervision-cop90-rasters")
_elevation_lookup = GCSElevationLookup(gcs_bucket=GCS_ELEVATION_BUCKET, gcs_prefix="COP90")

# WFO local taxonomy lookup
WFO_DB_PATH = os.path.join(os.path.dirname(__file__), "wfo_backbone.db")
_wfo_lookup = None
if os.path.exists(WFO_DB_PATH):
    try:
        _wfo_lookup = WFOLocalLookup(WFO_DB_PATH)
        logger.info(f"WFO local database loaded from {WFO_DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to load WFO database: {e}")
else:
    logger.warning(f"WFO database not found at {WFO_DB_PATH} — WFO lookups will be disabled")


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,X-API-Key,Accept")
        response.headers.add('Access-Control-Allow-Methods', "GET,POST,OPTIONS,PUT,DELETE")
        response.headers.add('Access-Control-Max-Age', '3600')
        return response

    # Lazy daily check: scan API key expirations on the first request of each day
    _check_api_key_expirations()

@app.route('/auth-check', methods=['GET'])
@maintenance_mode_middleware
@authenticated_route
def auth_check():
    """Simple endpoint to verify authentication status"""
    # If we get here, authentication was successful
    return jsonify({
        'status': 'authenticated',
        'message': 'Your authentication token is valid.'
    }), 200
    
@app.route('/process', methods=['POST', 'OPTIONS'])
@maintenance_mode_middleware
@authenticated_route
def process_image():
    """API endpoint to process an image with explicit CORS headers and automatic resizing"""
    # Check if file is present in the request
    if 'file' not in request.files:
        response = make_response(jsonify({'error': 'No file provided'}), 400)
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    # Get user email using the new function
    user_email = get_user_email_from_request(request)

    file = request.files['file']

    # Parse all form parameters before branching on file type
    engine_options = request.form.getlist('engines') if 'engines' in request.form else None
    prompt = request.form.get('prompt') if 'prompt' in request.form else None
    ocr_only = request.form.get('ocr_only', 'false').lower() == 'true'
    notebook_mode = request.form.get('notebook_mode', 'false').lower() == 'true'
    skip_label_collage = request.form.get('skip_label_collage', 'false').lower() == 'true'
    include_wfo = request.form.get('include_wfo', 'true').lower() == 'true'
    include_cop90 = request.form.get('include_cop90', 'true').lower() == 'true'
    llm_model_name = request.form.get('llm_model') if 'llm_model' in request.form else None
    user_gemini_key = request.form.get('gemini_api_key') or None  # None = fall back to server key

    # Common kwargs for process_image_request / process_pdf_request
    process_kwargs = dict(
        engine_options=engine_options,
        prompt=prompt,
        ocr_only=ocr_only,
        include_wfo=include_wfo,
        include_cop90=include_cop90,
        llm_model_name=llm_model_name,
        url_source="",
        notebook_mode=notebook_mode,
        skip_label_collage=skip_label_collage,
        user_api_key=user_gemini_key,
    )

    # Detect PDF by extension
    is_pdf = file.filename and file.filename.lower().endswith('.pdf')

    if is_pdf:
        # PDF branch: convert pages to JPGs internally, skip resize here
        logger.info(f"PDF upload detected for user: {user_email}, filename: {file.filename}")

        # ── Gemini Pro rate-limit gate (skip if user supplies their own key) ──
        # For PDFs, quota is checked per-page inside process_image_request
        # so we skip the single-slot reservation here.
        results, status_code = app.config['processor'].process_pdf_request(
            file=file, **process_kwargs
        )

        # Update usage statistics for each successful page
        if status_code == 200:
            for page_result in results.get('pages', []):
                if 'impact' in page_result:
                    update_usage_statistics(user_email, engines=engine_options, llm_model_name=llm_model_name, est_impact=page_result['impact'])

    else:
        # Image branch: resize then process (existing flow)
        try:
            file = process_uploaded_file_with_resize(file, max_pixels=5200000)
            logger.info(f"Image processed and resized if necessary for user: {user_email}")
        except Exception as e:
            logger.error(f"Error processing image for resize: {e}")
            response = make_response(jsonify({'error': f'Error processing image: {str(e)}'}), 500)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response

        # ── Gemini Pro rate-limit gate (skip if user supplies their own key) ──
        pro_quota_reserved = False
        if is_pro_request(engine_options, llm_model_name) and not user_gemini_key:
            allowed, count, limit = check_and_reserve_gemini_pro_quota(user_email)
            if not allowed:
                logger.warning(f"Gemini Pro rate limit hit for {user_email}: {count}/{limit}")
                _send_rate_limit_hit_alert(user_email, count, limit)
                resp = make_response(jsonify({
                    "error": "Gemini Pro rate limit exceeded",
                    "message": (
                        f"You have used all {limit} of your Gemini Pro model requests. "
                        "Contact an administrator to request additional quota."
                    ),
                    "gemini_pro_usage_count": count,
                    "gemini_pro_usage_limit": limit,
                }), 503)
                resp.headers.add('Access-Control-Allow-Origin', '*')
                return resp
            pro_quota_reserved = True

        results, status_code = app.config['processor'].process_image_request(
            file=file, **process_kwargs
        )

        # If processing was successful, update usage statistics
        if status_code == 200:
            update_usage_statistics(user_email, engines=engine_options, llm_model_name=llm_model_name, est_impact=results["impact"])
            # Advisory email: nudge users toward flash-lite / own API key (max 1/day)
            if pro_quota_reserved:
                _, count, limit = check_gemini_pro_rate_limit(user_email)
                _send_pro_migration_advisory(user_email, count, limit)
        else:
            # Release the reserved pro quota on failure
            if pro_quota_reserved:
                release_gemini_pro_quota(user_email)
            update_usage_statistics(user_email, engines=[f"failure_code_{status_code}"] if engine_options else None, llm_model_name=f"failure_code_{status_code}" if llm_model_name else None, est_impact=None)

    # Always return JSON
    response = make_response(json.dumps(results, cls=OrderedJsonEncoder), status_code)
    response.headers['Content-Type'] = 'application/json'
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/process-url', methods=['POST', 'OPTIONS'])
@maintenance_mode_middleware
@authenticated_route
def process_image_by_url():
    """API endpoint to process an image from a URL with FormData, matching /process behavior and automatic resizing"""
    max_retries=3
    # Get user email
    user_email = get_user_email_from_request(request)

    # Check content type to determine how to process the request
    content_type = request.headers.get('Content-Type', '').lower()
    
    # Handle JSON request
    if 'application/json' in content_type:
        data = request.get_json()
        if not data or 'image_url' not in data:
            response = make_response(jsonify({'error': 'No image URL provided'}), 400)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
            
        image_url = data.get('image_url')
        engine_options = data.get('engines')
        prompt = data.get('prompt')
        ocr_only = data.get('ocr_only', False)
        notebook_mode = data.get('notebook_mode', False)
        skip_label_collage = data.get('skip_label_collage', False)
        include_wfo = data.get('include_wfo', True)
        include_cop90 = data.get('include_cop90', True)
        llm_model_name = data.get('llm_model')
        user_gemini_key = data.get('gemini_api_key') or None

    # Handle form data request
    else:
        if 'image_url' not in request.form:
            response = make_response(jsonify({'error': 'No image URL provided'}), 400)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response

        image_url = request.form.get('image_url')
        engine_options = request.form.getlist('engines') if 'engines' in request.form else None
        prompt = request.form.get('prompt') if 'prompt' in request.form else None
        ocr_only = request.form.get('ocr_only', 'false').lower() == 'true'
        notebook_mode = request.form.get('notebook_mode', 'false').lower() == 'true'
        skip_label_collage = request.form.get('skip_label_collage', 'false').lower() == 'true'
        include_wfo = request.form.get('include_wfo', 'true').lower() == 'true'
        include_cop90 = request.form.get('include_cop90', 'true').lower() == 'true'
        llm_model_name = request.form.get('llm_model') if 'llm_model' in request.form else None
        user_gemini_key = request.form.get('gemini_api_key') or None

    # ── Gemini Pro rate-limit gate (skip if user supplies their own key) ──
    pro_quota_reserved = False
    if is_pro_request(engine_options, llm_model_name) and not user_gemini_key:
        allowed, count, limit = check_and_reserve_gemini_pro_quota(user_email)
        if not allowed:
            logger.warning(f"Gemini Pro rate limit hit for {user_email}: {count}/{limit}")
            _send_rate_limit_hit_alert(user_email, count, limit)
            resp = make_response(jsonify({
                "error": "Gemini Pro rate limit exceeded",
                "message": (
                    f"You have used all {limit} of your Gemini Pro model requests. "
                    "Contact an administrator to request additional quota."
                ),
                "gemini_pro_usage_count": count,
                "gemini_pro_usage_limit": limit,
            }), 503)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp
        pro_quota_reserved = True

    file_obj, filename = None, None
    last_exception = None

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} to fetch URL: {image_url}")
            # The actual download attempt
            # file_obj, filename = process_url_image_with_resize(image_url, max_pixels=5200000)
            try:
                allowed = os.environ.get("ALLOWED_IMAGE_DOMAINS", "").split(",") if os.environ.get("ALLOWED_IMAGE_DOMAINS") else None
                cookie  = os.environ.get("PORTAL_COOKIE")  # optional: e.g., "sessionid=abc123; other=xyz"
                extra   = {}  # optionally: {"X-Requested-With": "XMLHttpRequest"}

                file_obj, filename_from_url = smart_fetch_image_as_filestorage(
                    image_url,
                    max_pixels=5_200_000,
                    max_retries=3,
                    connect_timeout=15.0,
                    read_timeout=90.0,
                    per_try_base_delay=0.75,
                    per_try_jitter=0.75,
                    allowed_domains=allowed,
                    user_agent=APP_USER_AGENT,
                    extra_headers=extra,    # if the site expects specific headers
                    cookie=cookie,          # if you have an approved session
                    logger=logger,
                )
                logger.info(f"URL fetched filenam: {filename_from_url}")
            except:
                file_obj, filename = process_url_image_with_resize(image_url, max_pixels=5200000)


            logger.info(f"URL image fetched successfully for user: {user_email}")
            # If successful, break the loop and proceed
            break
        except requests.exceptions.RequestException as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1} failed for URL '{image_url}'. Reason: {e}")

            # If this was the last attempt, the loop will end, and we'll handle the failure below.
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Waiting for {wait_time} second(s) before retrying...")
                time.sleep(wait_time)
        except Exception as e:
            # Catch other unexpected errors during download/resize
            logger.exception(f"An unexpected error occurred during URL processing on attempt {attempt + 1}: {e}")
            return jsonify({'error': f'An unexpected server error occurred: {str(e)}'}), 500
    
    # After the loop, check if we ultimately failed
    if file_obj is None and last_exception is not None:
        logger.error(f"All {max_retries} retries failed for URL '{image_url}'. Final error: {last_exception}")
        
        # Construct the desired empty JSON response for the final failure
        error_response_data = OrderedDict([
            ("filename", extract_filename_from_url(image_url)),
            ("url_source", image_url),
            ("prompt", prompt),
            ("ocr_info", {"error": f"Failed to fetch URL: {str(last_exception)}"}),
            ("WFO_info", ""),
            ("COP90_elevation_m", ""),
            ("ocr", ""),
            ("formatted_json", ""),
            ("parsing_info", OrderedDict([
                ("model", ""),
                ("input", 0),
                ("output", 0),
                ("cost_in", 0),
                ("cost_out", 0),
            ])),
            ("impact", {}),
            ("collage_info", {"error": "Image could not be retrieved from URL."}),
            ("collage_image_format", ""),
            ("success", {  
                "image_available": "False",
                "text_collage": "False",
                "text_collage_resize": "False",
                "ocr": "False",
                "llm": "False",
            }),
        ])
        
        # Return this structure with a 200 OK status
        response = make_response(json.dumps(error_response_data, cls=OrderedJsonEncoder), 200)
        response.headers['Content-Type'] = 'application/json'
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    try:
        # Process image
        results, status_code = app.config['processor'].process_image_request(
            file=file_obj,
            engine_options=engine_options,
            prompt=prompt,
            ocr_only=ocr_only,
            include_wfo=include_wfo,
            include_cop90=include_cop90,
            llm_model_name=llm_model_name,
            url_source=image_url,
            notebook_mode=notebook_mode,
            skip_label_collage=skip_label_collage,
            user_api_key=user_gemini_key
        )

        # Update usage stats
        if status_code == 200:
            update_usage_statistics(user_email, engines=engine_options, llm_model_name=llm_model_name, est_impact=results["impact"])
            # Advisory email: nudge users toward flash-lite / own API key (max 1/day)
            if pro_quota_reserved:
                _, count, limit = check_gemini_pro_rate_limit(user_email)
                _send_pro_migration_advisory(user_email, count, limit)
        else:
            # Release the reserved pro quota on failure
            if pro_quota_reserved:
                release_gemini_pro_quota(user_email)
            update_usage_statistics(user_email, engines=[f"failure_code_{status_code}"] if engine_options else None, llm_model_name=f"failure_code_{status_code}" if llm_model_name else None, est_impact=None)

        response = make_response(json.dumps(results, cls=OrderedJsonEncoder), status_code)
        response.headers['Content-Type'] = 'application/json'

        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    except Exception as e:
        logger.exception(f"Error during main processing after successful download from URL: {e}")
        # Release the reserved pro quota on unhandled exception
        if pro_quota_reserved:
            release_gemini_pro_quota(user_email)
        return jsonify({'error': str(e)}), 500
    

@app.route('/impact', methods=['GET'])
@authenticated_route
def get_impact_summary():
    """
    Return total impact summary for the authenticated caller.
    Works with API key only (X-API-Key) or Firebase auth.
    """
    try:
        # Resolve the user email from API key or Firebase token
        user_email = get_user_email_from_request(request)
        if not user_email or user_email == 'unknown':
            return jsonify({'error': 'Unable to resolve user from credentials'}), 401

        # Fetch their usage stats doc (doc id = user_email)
        doc_ref = db.collection('usage_statistics').document(user_email)
        doc = doc_ref.get()

        if not doc.exists:
            # Return zeros if they have no usage yet
            return jsonify({
                'status': 'success',
                'user_email': user_email,
                'totals': {
                    'total_images_processed': 0,
                    'total_tokens_all': 0,
                    'total_watt_hours': 0.0,
                    'total_grams_CO2': 0.0,
                    'total_mL_water': 0.0,
                },
                'units': {
                    'total_tokens_all': 'tokens',
                    'total_watt_hours': 'Wh',
                    'total_grams_CO2': 'g CO2e',
                    'total_mL_water': 'mL'
                }
            })

        data = doc.to_dict() or {}

        # Normalize/defend against missing fields
        total_images_processed = int(data.get('total_images_processed', 0) or 0)
        total_tokens_all          = int(data.get('total_tokens_all', 0) or 0)
        total_watt_hours      = float(data.get('total_watt_hours', 0.0) or 0.0)
        total_grams_CO2       = float(data.get('total_grams_CO2', 0.0) or 0.0)
        # water may be stored under either name; support both
        total_mL_water        = float(
            data.get('total_mL_water',
                     data.get('total_milliliters_water', 0.0)) or 0.0
        )

        return jsonify({
            'status': 'success',
            'totals': {
                'total_images_processed': total_images_processed,
                'total_tokens_all': total_tokens_all,
                'total_watt_hours': total_watt_hours,
                'total_grams_CO2': total_grams_CO2,
                'total_mL_water': total_mL_water,
            },
            'units': {
                'total_tokens_all': 'tokens',
                'total_watt_hours': 'Wh',
                'total_grams_CO2': 'g CO2e',
                'total_mL_water': 'mL'
            }
        })
    except Exception as e:
        logger.error(f"/impact/summary failed: {e}")
        return jsonify({'error': f'Failed to get impact summary: {str(e)}'}), 500


@app.route('/api-demo', methods=['GET', 'POST'])
def api_demo_page():
    """Serve the API demo HTML page - accepts both GET and POST requests"""
    # For POST requests, process the auth token from form data
    if request.method == 'POST':
        auth_token = request.form.get('auth_token')
        if auth_token:
            try:
                # Log the token (first few chars only for security)
                token_prefix = auth_token[:8] if len(auth_token) > 8 else ""
                logger.info(f"Auth token from form: {token_prefix}... (length: {len(auth_token)})")
                
                # Verify the token is valid
                decoded_token = auth.verify_id_token(auth_token)
                user_email = decoded_token.get('email', 'unknown')
                
                logger.info(f"Token verified successfully for: {user_email}")
                
                # Create response that redirects to the GET version
                response = make_response(redirect('/api-demo'))
                
                # Store token in cookie for future requests
                response.set_cookie(
                    'auth_token', 
                    auth_token, 
                    httponly=True, 
                    secure=True, 
                    samesite='Lax',
                    max_age=3600  # 1 hour expiration
                )
                
                return response
            except Exception as e:
                logger.error(f"Error verifying token in /api-demo POST: {str(e)}")
                return redirect('/login')
        else:
            return redirect('/login')
    
    # For GET requests, verify authentication
    user = authenticate_request(request)
    if not user or not user.get('email'):
        # Redirect to login page if not authenticated
        return redirect('/login')
    
    user_email = user.get('email')
    logger.info(f"User {user_email} accessing API demo page")
    
    # Get current authentication token if available
    auth_token = None
    # Check in Authorization header
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        auth_token = auth_header.split('Bearer ')[1]
    # If not in header, check in cookies
    if not auth_token:
        auth_token = request.cookies.get('auth_token')
    
    # Check for API key in header or query params
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    
    # Check if user has API keys
    has_api_keys = False
    try:
        keys_ref = db.collection('api_keys').where('owner', '==', user_email).where('active', '==', True).limit(1).get()
        has_api_keys = len(list(keys_ref)) > 0
    except Exception as e:
        logger.warning(f"Error checking API keys: {str(e)}")
    
    # Get the base URL from the request
    base_url = request.url_root.rstrip('/')
    # Force HTTPS
    if base_url.startswith('http:'):
        base_url = 'https:' + base_url[5:]
    
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    # Pass the user info and server URL to the template
    return render_template(
        'api_demo.html',
        server_url=base_url,
        user_email=user_email,
        auth_token=auth_token,
        api_key=api_key,
        has_api_keys=has_api_keys,
        api_key_config=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"]
    )

@app.route('/admin/usage-statistics', methods=['GET'])
@authenticated_route
def get_usage_statistics():
    """Get usage statistics for all users"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get all usage statistics
        stats_ref = db.collection('usage_statistics').stream()
        
        stats_list = []
        for stat_doc in stats_ref:
            stat_data = stat_doc.to_dict()
            
            # Format timestamps for display
            if 'last_processed_at' in stat_data and hasattr(stat_data['last_processed_at'], '_seconds'):
                stat_data['last_processed_at'] = {
                    '_seconds': stat_data['last_processed_at']._seconds,
                    '_formatted': datetime.datetime.fromtimestamp(
                        stat_data['last_processed_at']._seconds
                    ).strftime('%Y-%m-%d %H:%M:%S')
                }
            
            if 'first_processed_at' in stat_data and hasattr(stat_data['first_processed_at'], '_seconds'):
                stat_data['first_processed_at'] = {
                    '_seconds': stat_data['first_processed_at']._seconds,
                    '_formatted': datetime.datetime.fromtimestamp(
                        stat_data['first_processed_at']._seconds
                    ).strftime('%Y-%m-%d %H:%M:%S')
                }
            
            stats_list.append(stat_data)
        
        # Sort by total images processed (descending)
        stats_list.sort(key=lambda x: x.get('total_images_processed', 0), reverse=True)
        
        return jsonify({
            'status': 'success',
            'count': len(stats_list),
            'usage_statistics': stats_list
        })
        
    except Exception as e:
        logger.error(f"Error getting usage statistics: {str(e)}")
        return jsonify({'error': f'Failed to get usage statistics: {str(e)}'}), 500


@app.route('/admin/test-pro-advisory', methods=['POST'])
@authenticated_route
def test_pro_advisory_email():
    """TEMPORARY: Send the pro-migration advisory email to the calling admin.
    DELETE THIS ROUTE after verifying the email looks correct.
    """
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'Not authenticated'}), 401
    admin_email = user['email']
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Admin access required'}), 403

    # Clear the daily dedup so the email actually sends
    user_ref = db.collection("usage_statistics").document(admin_email)
    user_ref.set({"last_pro_advisory_date": ""}, merge=True)

    _send_pro_migration_advisory(admin_email, 42, 100)
    return jsonify({'status': 'sent', 'to': admin_email})


@app.route('/admin/rate-limits/<email>', methods=['POST'])
@authenticated_route
def update_user_rate_limit(email):
    """Update Gemini Pro usage limit for a specific user."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = user.get('email')
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    data = request.get_json()
    if not data or 'gemini_pro_usage_limit' not in data:
        return jsonify({'error': 'Missing gemini_pro_usage_limit in request body'}), 400

    try:
        new_limit = int(data['gemini_pro_usage_limit'])
    except (ValueError, TypeError):
        return jsonify({'error': 'gemini_pro_usage_limit must be an integer'}), 400

    try:
        user_ref = db.collection('usage_statistics').document(email)
        doc = user_ref.get()
        if not doc.exists:
            return jsonify({'error': f'No usage record found for {email}'}), 404

        user_ref.update({'gemini_pro_usage_limit': new_limit})
        logger.info(f"Admin {admin_email} updated Gemini Pro limit for {email} to {new_limit}")

        return jsonify({
            'status': 'success',
            'message': f'Updated Gemini Pro limit for {email} to {new_limit}',
            'email': email,
            'gemini_pro_usage_limit': new_limit,
        })
    except Exception as e:
        logger.error(f"Error updating rate limit for {email}: {e}")
        return jsonify({'error': f'Failed to update rate limit: {str(e)}'}), 500


@app.route('/cors-test', methods=['GET', 'OPTIONS'])
@maintenance_mode_middleware
def cors_test():
    """Simple endpoint to test CORS configuration and maintenance status"""
    return jsonify({
        'status': 'ok',
        'cors': 'enabled',
        'message': 'If you can see this response in your browser or JavaScript app, CORS is working correctly.',
        'maintenance_mode': False  # If this endpoint responds, maintenance is not active
    })

@app.route('/test_json_order', methods=['GET'])
# curl https://vouchervision-go-738307415303.us-central1.run.app/test_json_order
def test_json_order():
    from collections import OrderedDict
    test_dict = OrderedDict([
        ("first", 1),
        ("second", 2),
        ("third", 3),
        ("fourth", 4)
    ])
    return json.dumps(test_dict, cls=OrderedJsonEncoder), 200, {'Content-Type': 'application/json'}

@app.route('/health', methods=['GET', 'OPTIONS'])
def health_check():
    """Health check endpoint that bypasses maintenance mode and reports status"""
    
    # Handle OPTIONS preflight request for CORS
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
        response.headers.add('Access-Control-Max-Age', '3600')
        return response
    
    # Get the active request count from the processor
    active_requests = app.config['processor'].throttler.get_active_count()
    max_requests = app.config['processor'].throttler.max_concurrent
    
    # Check maintenance status from Firestore
    maintenance_status = get_maintenance_status()
    
    # Get maintenance info if available
    maintenance_info = {}
    try:
        maintenance_doc = db.collection('system_config').document('maintenance').get()
        if maintenance_doc.exists:
            data = maintenance_doc.to_dict()
            maintenance_info = {
                'last_updated': data.get('last_updated'),
                'updated_by': data.get('updated_by', 'Unknown')
            }
    except Exception as e:
        logger.warning(f"Could not get maintenance info: {str(e)}")
    
    # Create the response with all the original functionality
    response = jsonify({
        'status': 'ok',
        'active_requests': active_requests,
        'max_concurrent_requests': max_requests,
        'server_load': f"{(active_requests / max_requests) * 100:.1f}%",
        'maintenance_mode': maintenance_status,
        'maintenance_info': maintenance_info,
        'api_status': 'maintenance' if maintenance_status else 'available'
    })
    
    # Ensure CORS headers are present on the actual response
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
    
    return response, 200


@app.route('/api-costs', methods=['GET', 'OPTIONS'])
def api_costs():
    """Return the api_cost.yaml contents as JSON for the cost calculator."""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200

    try:
        yaml_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main")), 'api_cost', 'api_cost.yaml')
        with open(yaml_path, 'r') as f:
            cost_data = yaml.safe_load(f)
        response = make_response(jsonify(cost_data))
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/elevation', methods=['GET'])
def elevation():
    """Return COP90 elevation in metres for a given lat/lon coordinate.

    Query params:
        lat (float): Decimal latitude [-90, 90]
        lon (float): Decimal longitude [-180, 180]

    Returns JSON: {"lat": ..., "lon": ..., "elevation_m": <float or null>}
    """
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon query parameters are required"}), 400
    if not (-90 <= lat <= 90):
        return jsonify({"error": "lat must be in [-90, 90]"}), 400
    if not (-180 <= lon <= 180):
        return jsonify({"error": "lon must be in [-180, 180]"}), 400
    elev = _elevation_lookup.query(lat, lon)
    return jsonify({"lat": lat, "lon": lon, "elevation_m": elev})


@app.after_request
def after_request(response):
    """Ensure CORS headers are present on all responses"""
    # Add CORS headers to all responses (if not already present)
    if not response.headers.get('Access-Control-Allow-Origin'):
        response.headers.add('Access-Control-Allow-Origin', '*')
    
    # Add other CORS headers for non-preflight responses
    if request.method != 'OPTIONS':
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key,Accept')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS,PUT,DELETE')
    
    return response

@app.route('/auth-success', methods=['GET'])
def auth_success():    
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()

    # Get the base URL from the request
    base_url = request.url_root.rstrip('/')
    # Force HTTPS
    if base_url.startswith('http:'):
        base_url = 'https:' + base_url[5:]
    
    # Pass the firebase config and server URL to the template
    return render_template(
        'auth_success.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"],
        server_url=base_url
    )

@app.route('/check-admin-status', methods=['GET'])
@authenticated_route
def check_admin_status():
    """Check if the authenticated user is an admin"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Check if the user is an admin
        admin_doc = db.collection('admins').document(user_email).get()
        
        is_admin = admin_doc.exists
        
        return jsonify({
            'is_admin': is_admin,
            'email': user_email
        })
        
    except Exception as e:
        logger.error(f"Error checking admin status: {str(e)}")
        return jsonify({'error': f'Failed to check admin status: {str(e)}'}), 500
    
@app.route('/signup', methods=['GET'])
def signup_page():    
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    # Pass the firebase config to the template
    return render_template(
        'signup.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )

@app.route('/pending-approval', methods=['GET'])
def pending_approval_page():
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    # Pass the firebase config to the template
    return render_template(
        'pending_approval.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )

@app.route('/application-rejected', methods=['GET'])
def application_rejected_page():
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    # Pass the firebase config to the template
    return render_template(
        'application_rejected.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )

@app.route('/login', methods=['GET'])
def login_page():    
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    # Pass the firebase config to the template
    return render_template(
        'login.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )


@app.route('/submit-application', methods=['POST'])
def submit_application():
    """Submit a new user application"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Get application data from request
        data = request.get_json() or {}
        
        if not data.get('organization') or not data.get('purpose'):
            return jsonify({'error': 'Missing required fields'}), 400
        
        organization = data.get('organization')
        purpose = data.get('purpose')
        
        # Create an application record in Firestore
        application_data = {
            'email': user_email,
            'organization': organization,
            'purpose': purpose,
            'status': 'pending',  # pending, approved, rejected
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'approved_by': None,
            'rejected_by': None,
            'rejection_reason': None,
            'notes': []
        }
        
        # Save to Firestore - use email as document ID for easy lookup
        db.collection('user_applications').document(user_email).set(application_data)
        
        # Send notification email to admin
        notification_sent = False
        if 'email_sender' in app.config and app.config['email_sender'].is_enabled:
            notification_sent = app.config['email_sender'].send_application_submission_notification(
                user_email, 
                organization, 
                purpose
            )
            if notification_sent:
                logger.info(f"Application submission notification sent for {user_email}")
            else:
                logger.warning(f"Failed to send application submission notification for {user_email}")
        else:
            logger.warning("Email sender not configured or disabled, skipping notification")
        
        # Return success response
        return jsonify({
            'status': 'success',
            'message': 'Application submitted successfully',
            'notification_sent': notification_sent
        })
        
    except Exception as e:
        logger.error(f"Error submitting application: {str(e)}")
        return jsonify({'error': f'Failed to submit application: {str(e)}'}), 500

@app.route('/check-approval-status', methods=['GET'])
def check_approval_status():
    """Check the approval status of a user's application"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Check if the user is an admin (admins are always approved)
        admin_doc = db.collection('admins').document(user_email).get()
        if admin_doc.exists:
            return jsonify({
                'status': 'approved',
                'is_admin': True,
                'message': 'User is an admin'
            })
        
        # Get application record from Firestore
        application_doc = db.collection('user_applications').document(user_email).get()
        
        if not application_doc.exists:
            # No application found - create a pending one for this user
            application_data = {
                'email': user_email,
                'organization': 'Unknown',
                'purpose': 'Auto-created record',
                'status': 'pending',
                'created_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            db.collection('user_applications').document(user_email).set(application_data)
            
            return jsonify({
                'status': 'pending',
                'message': 'Application pending approval'
            })
        
        # Get application data
        application_data = application_doc.to_dict()
        
        return jsonify({
            'status': application_data.get('status', 'pending'),
            'message': f"Application {application_data.get('status', 'pending')}",
            'reason': application_data.get('rejection_reason')
        })
        
    except Exception as e:
        logger.error(f"Error checking approval status: {str(e)}")
        return jsonify({'error': f'Failed to check approval status: {str(e)}'}), 500

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    """Admin dashboard for managing user applications"""
    # For POST requests, validate token and render directly (avoids
    # third-party cookie issues when embedded in a cross-origin iframe)
    if request.method == 'POST':
        auth_token = request.form.get('auth_token')
        if auth_token:
            try:
                decoded = auth.verify_id_token(auth_token)
                user_email = decoded.get('email')
                if user_email:
                    # Check if the user is an admin
                    admin_doc = db.collection('admins').document(user_email).get()
                    if not admin_doc.exists:
                        return redirect('/auth-success')

                    firebase_config = get_firebase_config()
                    return render_template(
                        'admin_dashboard.html',
                        api_key=firebase_config["apiKey"],
                        auth_domain=firebase_config["authDomain"],
                        project_id=firebase_config["projectId"],
                        storage_bucket=firebase_config.get("storageBucket", ""),
                        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
                        app_id=firebase_config["appId"]
                    )
            except Exception as e:
                logger.warning(f"POST to /admin with invalid token: {e}")

    # For GET requests, follow normal authentication
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    user_email = user.get('email')

    # Check if the user is an admin
    admin_doc = db.collection('admins').document(user_email).get()
    if not admin_doc.exists:
        # Not an admin - redirect to appropriate page
        return redirect('/auth-success')

    firebase_config = get_firebase_config()

    # Pass the firebase config and user info to the template
    return render_template(
        'admin_dashboard.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )

@app.route('/admin/applications', methods=['GET'])
@authenticated_route
def list_applications():
    """List all user applications"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(user_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get all applications
        applications_ref = db.collection('user_applications').stream()
        
        applications = []
        for app_doc in applications_ref:
            app_data = app_doc.to_dict()
            app_data['email'] = app_doc.id  # Add email as a field (which is the document ID)
            applications.append(app_data)
        
        # Sort applications by status and creation date
        applications.sort(key=lambda app: (
            0 if app.get('status') == 'pending' else 1 if app.get('status') == 'approved' else 2,
            # Newest first within each status
            -app.get('created_at', {}).get('_seconds', 0) if isinstance(app.get('created_at'), dict) else 0
        ))
        
        return jsonify({
            'status': 'success',
            'count': len(applications),
            'applications': applications
        })
        
    except Exception as e:
        logger.error(f"Error listing applications: {str(e)}")
        return jsonify({'error': f'Failed to list applications: {str(e)}'}), 500

@app.route('/admin/applications/<email>/approve', methods=['POST'])
@authenticated_route
def approve_application(email):
    """Approve a user application with optional API key permission"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get data from request
        data = request.get_json() or {}
        # Check if API key creation is allowed for this user
        allow_api_keys = data.get('allow_api_keys', False)
        
        # Get the application
        app_doc = db.collection('user_applications').document(email).get()
        
        if not app_doc.exists:
            return jsonify({'error': 'Application not found'}), 404
        
        app_data = app_doc.to_dict()
        
        # Check if already approved
        if app_data.get('status') == 'approved':
            return jsonify({'error': 'Application is already approved'}), 400
        
        # Update the application status
        update_data = {
            'status': 'approved',
            'approved_by': admin_email,
            'approved_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'api_key_access': allow_api_keys  # Add API key permission flag
        }
        
        db.collection('user_applications').document(email).update(update_data)
        
        # Send email notification
        email_sent = False
        if 'email_sender' in app.config and app.config['email_sender'].is_enabled:
            # Send approval notification
            email_sent = app.config['email_sender'].send_approval_notification(email)
            
            # If API key access is granted, send another notification
            if allow_api_keys:
                app.config['email_sender'].send_api_key_permission_notification(email)
        
        return jsonify({
            'status': 'success',
            'message': f'Application for {email} has been approved',
            'api_key_access': allow_api_keys,
            'email_sent': email_sent
        })
        
    except Exception as e:
        logger.error(f"Error approving application: {str(e)}")
        return jsonify({'error': f'Failed to approve application: {str(e)}'}), 500


# 2. Add endpoint to update API key permission for already approved users
@app.route('/admin/applications/<email>/update-api-access', methods=['POST'])
@authenticated_route
def update_api_key_access(email):
    """Update API key creation permission for a user"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get data from request
        data = request.get_json() or {}
        allow_api_keys = data.get('allow_api_keys', False)
        
        # Get the application
        app_doc = db.collection('user_applications').document(email).get()
        
        if not app_doc.exists:
            return jsonify({'error': 'User application not found'}), 404
        
        app_data = app_doc.to_dict()
        
        # Check if application is approved
        if app_data.get('status') != 'approved':
            return jsonify({'error': 'Cannot update API key access for non-approved users'}), 400
        
        # Check if API key permission is changing from false to true (new grant)
        is_new_grant = allow_api_keys and not app_data.get('api_key_access', False)
        
        # Update the API key permission
        db.collection('user_applications').document(email).update({
            'api_key_access': allow_api_keys,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'notes': firestore.ArrayUnion([
                f"API key access {'granted' if allow_api_keys else 'revoked'} by {admin_email} on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ])
        })
        
        # Send email notification if it's a new grant
        email_sent = False
        if is_new_grant and 'email_sender' in app.config and app.config['email_sender'].is_enabled:
            email_sent = app.config['email_sender'].send_api_key_permission_notification(email)
        
        return jsonify({
            'status': 'success',
            'message': f"API key access {'granted' if allow_api_keys else 'revoked'} for {email}",
            'api_key_access': allow_api_keys,
            'email_sent': email_sent
        })
        
    except Exception as e:
        logger.error(f"Error updating API key access: {str(e)}")
        return jsonify({'error': f'Failed to update API key access: {str(e)}'}), 500


@app.route('/admin/applications/<email>/reject', methods=['POST'])
@authenticated_route
def reject_application(email):
    """Reject a user application"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get rejection reason from request
        data = request.get_json() or {}
        reason = data.get('reason')
        
        if not reason:
            return jsonify({'error': 'Rejection reason is required'}), 400
        
        # Get the application
        app_doc = db.collection('user_applications').document(email).get()
        
        if not app_doc.exists:
            return jsonify({'error': 'Application not found'}), 404
        
        app_data = app_doc.to_dict()
        
        # Check if already rejected
        if app_data.get('status') == 'rejected':
            return jsonify({'error': 'Application is already rejected'}), 400
        
        # Update the application status
        db.collection('user_applications').document(email).update({
            'status': 'rejected',
            'rejected_by': admin_email,
            'rejected_at': firestore.SERVER_TIMESTAMP,
            'rejection_reason': reason,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        return jsonify({
            'status': 'success',
            'message': f'Application for {email} has been rejected'
        })
        
    except Exception as e:
        logger.error(f"Error rejecting application: {str(e)}")
        return jsonify({'error': f'Failed to reject application: {str(e)}'}), 500

@app.route('/admin/api-keys', methods=['GET'])
@authenticated_route
def list_all_api_keys():
    """List all API keys (admin only)"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get all API keys
        keys_ref = db.collection('api_keys').stream()
        
        keys = []
        for key_doc in keys_ref:
            key_data = key_doc.to_dict()
            key_data['key_id'] = key_doc.id  # Add key ID (which is the document ID)
            keys.append(key_data)
        
        # Sort keys by creation date (newest first) and then by owner
        keys.sort(key=lambda key: (
            -key.get('created_at', {}).get('_seconds', 0) if isinstance(key.get('created_at'), dict) else 0,
            key.get('owner', '')
        ))
        
        return jsonify({
            'status': 'success',
            'count': len(keys),
            'api_keys': keys
        })
        
    except Exception as e:
        logger.error(f"Error listing API keys: {str(e)}")
        return jsonify({'error': f'Failed to list API keys: {str(e)}'}), 500   

@app.route('/admin/api-keys/<key_id>/revoke', methods=['POST'])
@authenticated_route
def admin_revoke_api_key(key_id):
    """Revoke an API key (admin only)"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get data from request
        data = request.get_json() or {}
        reason = data.get('reason', 'Revoked by administrator')
        
        # Get the API key
        key_doc = db.collection('api_keys').document(key_id).get()
        
        if not key_doc.exists:
            return jsonify({'error': 'API key not found'}), 404
        
        key_data = key_doc.to_dict()
        
        # Check if already revoked
        if not key_data.get('active', False):
            return jsonify({'error': 'API key is already revoked'}), 400
        
        # Update the API key
        db.collection('api_keys').document(key_id).update({
            'active': False,
            'revoked_at': firestore.SERVER_TIMESTAMP,
            'revoked_by': admin_email,
            'revocation_reason': reason
        })
        
        return jsonify({
            'status': 'success',
            'message': f'API key has been revoked'
        })
        
    except Exception as e:
        logger.error(f"Error revoking API key: {str(e)}")
        return jsonify({'error': f'Failed to revoke API key: {str(e)}'}), 500

@app.route('/admin/list-admins', methods=['GET'])
@authenticated_route
def list_admins():
    """List all admins"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get all admins
        admins_ref = db.collection('admins').stream()
        
        admins = []
        for admin_doc in admins_ref:
            admin_data = admin_doc.to_dict()
            admin_data['email'] = admin_doc.id  # Add email as a field (which is the document ID)
            admins.append(admin_data)
        
        # Sort admins by email
        admins.sort(key=lambda admin: admin.get('email', ''))
        
        return jsonify({
            'status': 'success',
            'count': len(admins),
            'admins': admins
        })
        
    except Exception as e:
        logger.error(f"Error listing admins: {str(e)}")
        return jsonify({'error': f'Failed to list admins: {str(e)}'}), 500    
    
@app.route('/admin/add-admin', methods=['POST'])
@authenticated_route
def add_admin():
    """Add a new admin"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get data from request
        data = request.get_json() or {}
        new_admin_email = data.get('email')
        
        if not new_admin_email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Check if already an admin
        existing_admin = db.collection('admins').document(new_admin_email).get()
        if existing_admin.exists:
            return jsonify({'error': 'User is already an admin'}), 400
        
        # Create admin record
        admin_data = {
            'added_by': admin_email,
            'added_at': firestore.SERVER_TIMESTAMP
        }
        
        db.collection('admins').document(new_admin_email).set(admin_data)
        
        # If user has an application, approve it automatically
        app_doc = db.collection('user_applications').document(new_admin_email).get()
        if app_doc.exists:
            # Update application to approved
            db.collection('user_applications').document(new_admin_email).update({
                'status': 'approved',
                'approved_by': admin_email,
                'approved_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP,
                'notes': firestore.ArrayUnion(['Automatically approved when added as admin'])
            })
        else:
            # Create an approved application for the admin
            app_data = {
                'email': new_admin_email,
                'organization': 'Admin User',
                'purpose': 'Administrative access',
                'status': 'approved',
                'created_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP,
                'approved_by': admin_email,
                'approved_at': firestore.SERVER_TIMESTAMP,
                'notes': ['Automatically created when added as admin']
            }
            db.collection('user_applications').document(new_admin_email).set(app_data)
        
        return jsonify({
            'status': 'success',
            'message': f'{new_admin_email} has been added as admin'
        })
        
    except Exception as e:
        logger.error(f"Error adding admin: {str(e)}")
        return jsonify({'error': f'Failed to add admin: {str(e)}'}), 500
    
@app.route('/admin/remove-admin', methods=['POST'])
@authenticated_route
def remove_admin():
    """Remove an admin"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get data from request
        data = request.get_json() or {}
        target_email = data.get('email')
        
        if not target_email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Can't remove yourself
        if target_email == admin_email:
            return jsonify({'error': 'Cannot remove yourself as admin'}), 400
        
        # Check if the target is an admin
        target_admin = db.collection('admins').document(target_email).get()
        if not target_admin.exists:
            return jsonify({'error': 'User is not an admin'}), 404
        
        # Delete the admin record
        db.collection('admins').document(target_email).delete()
        
        # Add a note to the user's application if it exists
        app_doc = db.collection('user_applications').document(target_email).get()
        if app_doc.exists:
            db.collection('user_applications').document(target_email).update({
                'updated_at': firestore.SERVER_TIMESTAMP,
                'notes': firestore.ArrayUnion([f'Admin status removed by {admin_email} on {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
            })
        
        return jsonify({
            'status': 'success',
            'message': f'{target_email} has been removed as admin'
        })
        
    except Exception as e:
        logger.error(f"Error removing admin: {str(e)}")
        return jsonify({'error': f'Failed to remove admin: {str(e)}'}), 500

@app.route('/session-expired', methods=['GET'])
def session_expired():
    """Simple page that shows session expired message and login form"""
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    return render_template(
        'session_expired.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )

@app.route('/prompts', methods=['GET'])
def list_prompts_api():
    """API endpoint to list all available prompt templates"""
    # Get prompt directory
    prompt_dir = os.path.join(project_root, "vouchervision_main", "custom_prompts")
    
    # Determine format type: json (default for API) or html (for web UI)
    format_type = request.args.get('format', 'json')
    view_details = request.args.get('view', 'false').lower() == 'true'
    specific_prompt = request.args.get('prompt')
    
    # Get all YAML files
    prompt_files = []
    for ext in ['.yaml', '.yml']:
        prompt_files.extend(list(Path(prompt_dir).glob(f'*{ext}')))
    
    if not prompt_files:
        if format_type == 'text':
            return "No prompt files found.", 404, {'Content-Type': 'text/plain'}
        else:
            return jsonify({
                'status': 'error',
                'message': f'No prompt files found in {prompt_dir}'
            }), 404
    
    # If a specific prompt was requested
    if specific_prompt:
        target_file = None
        for file in prompt_files:
            if file.name == specific_prompt:
                target_file = file
                break
                
        if target_file:
            # Return the prompt content
            prompt_details = extract_prompt_details(target_file)
            
            # Format response based on requested format
            if format_type == 'text':
                # Return plain text version for command line
                response_text = format_prompt_as_text(target_file.name, prompt_details)
                return response_text, 200, {'Content-Type': 'text/plain'}
            else:
                # Return JSON structure
                return jsonify({
                    'status': 'success',
                    'prompt': {
                        'filename': target_file.name,
                        'details': prompt_details
                    }
                })
        else:
            # Return error with list of available prompts
            available_prompts = [file.name for file in prompt_files]
            
            if format_type == 'text':
                return f"Prompt file '{specific_prompt}' not found.\nAvailable prompts: {', '.join(available_prompts)}", 404, {'Content-Type': 'text/plain'}
            else:
                return jsonify({
                    'status': 'error',
                    'message': f"Prompt file '{specific_prompt}' not found.",
                    'available_prompts': available_prompts
                }), 404
    
    # Otherwise list all prompts
    prompt_info_list = []
    for file in prompt_files:
        info = extract_prompt_info(file)
        
        # If view_details is True, include the full prompt content
        if view_details:
            info['details'] = extract_prompt_details(file)
        
        prompt_info_list.append(info)
    
    # Format response based on requested format
    if format_type == 'text':
        # Return a text table for command line
        response_text = format_prompts_as_text_table(prompt_info_list)
        return response_text, 200, {'Content-Type': 'text/plain'}
    else:
        # Return JSON structure
        return jsonify({
            'status': 'success',
            'count': len(prompt_files),
            'prompts': prompt_info_list
        })
    
def format_prompts_as_text_table(prompt_list):
    """
    Format a list of prompts as a text table suitable for terminal display
    
    Args:
        prompt_list (list): List of prompt info dictionaries
        
    Returns:
        str: Formatted text table
    """
    # Prepare table data
    table_data = []
    for i, info in enumerate(prompt_list, 1):
        # Format the description with proper text wrapping
        wrapped_description = textwrap.fill(info.get('description', ''), width=50)
        
        table_data.append([
            i,
            info.get('filename', ''),
            wrapped_description,
            info.get('version', 'Unknown'),
            info.get('author', 'Unknown'),
            info.get('institution', 'Unknown')
        ])
    
    # Generate table
    table = tabulate(
        table_data, 
        headers=['#', 'Filename', 'Description', 'Version', 'Author', 'Institution'],
        tablefmt='grid'
    )
    
    return f"Available Prompt Templates:\n\n{table}\n\nTotal: {len(prompt_list)} prompt file(s) found"

def format_prompt_as_text(filename, details):
    """
    Format a prompt's details as plain text suitable for terminal display
    
    Args:
        filename (str): Name of the prompt file
        details (dict): Prompt details dictionary
        
    Returns:
        str: Formatted text representation
    """
    import textwrap
    
    lines = []
    lines.append("=" * 80)
    lines.append(f"PROMPT FILE: {filename}")
    lines.append("=" * 80)
    lines.append("")
    
    # Extract metadata from parsed data
    metadata = {}
    if 'parsed_data' in details and details['parsed_data']:
        data = details['parsed_data']
        metadata_fields = {
            'prompt_name': 'Name',
            'prompt_description': 'Description',
            'prompt_version': 'Version',
            'prompt_author': 'Author',
            'prompt_author_institution': 'Institution',
            'LLM': 'LLM Type'
        }
        
        for field_key, display_name in metadata_fields.items():
            if field_key in data and data[field_key]:
                metadata[display_name] = data[field_key]
    
    # Display metadata section
    if metadata:
        lines.append("METADATA:")
        for name, value in metadata.items():
            if isinstance(value, str):
                wrapped_value = textwrap.fill(value, width=76, subsequent_indent='    ')
                lines.append(f"{name}: {wrapped_value}")
            else:
                lines.append(f"{name}: {value}")
        lines.append("")
    
    # Display important content sections
    if 'parsed_data' in details and details['parsed_data']:
        data = details['parsed_data']
        
        # Priority sections to display first
        priority_sections = [
            ('instructions', 'INSTRUCTIONS'),
            ('json_formatting_instructions', 'JSON FORMATTING INSTRUCTIONS'),
            ('rules', 'RULES'),
            ('mapping', 'MAPPING'),
            ('examples', 'EXAMPLES'),
        ]
        
        for key, heading in priority_sections:
            if key in data and data[key]:
                lines.append(heading + ":")
                value = data[key]
                if isinstance(value, str):
                    # Format strings with proper wrapping
                    wrapped = textwrap.fill(value, width=76, subsequent_indent='  ')
                    lines.append(wrapped)
                else:
                    # Format dictionaries/lists with proper indentation
                    import yaml
                    yaml_str = yaml.dump(value, default_flow_style=False)
                    for yaml_line in yaml_str.split('\n'):
                        lines.append("  " + yaml_line)
                lines.append("")
        
        # Add other sections not in priority list
        for key, value in data.items():
            if key not in [k for k, _ in priority_sections] and key not in [
                'prompt_name', 'prompt_description', 'prompt_version', 
                'prompt_author', 'prompt_author_institution', 'LLM'
            ]:
                heading = key.replace('_', ' ').upper()
                lines.append(heading + ":")
                if isinstance(value, str):
                    # Format strings with proper wrapping
                    wrapped = textwrap.fill(value, width=76, subsequent_indent='  ')
                    lines.append(wrapped)
                else:
                    # Format dictionaries/lists with proper indentation
                    import yaml
                    yaml_str = yaml.dump(value, default_flow_style=False)
                    for yaml_line in yaml_str.split('\n'):
                        lines.append("  " + yaml_line)
                lines.append("")
    
    # Display raw content if parsing failed or as a fallback
    elif 'raw_content' in details:
        lines.append("RAW CONTENT:")
        lines.append(details['raw_content'])
    
    lines.append("=" * 80)
    
    return "\n".join(lines)

def format_prompts_as_text_table(prompt_list):
    """
    Format a list of prompts as a text table suitable for terminal display
    
    Args:
        prompt_list (list): List of prompt info dictionaries
        
    Returns:
        str: Formatted text table
    """
    import textwrap
    from tabulate import tabulate
    
    # Prepare table data
    table_data = []
    for i, info in enumerate(prompt_list, 1):
        # Format the description with proper text wrapping
        wrapped_description = textwrap.fill(info.get('description', ''), width=50)
        
        table_data.append([
            i,
            info.get('filename', ''),
            wrapped_description,
            info.get('version', 'Unknown'),
            info.get('author', 'Unknown'),
            info.get('institution', 'Unknown')
        ])
    
    # Generate table
    table = tabulate(
        table_data, 
        headers=['#', 'Filename', 'Description', 'Version', 'Author', 'Institution'],
        tablefmt='grid'
    )
    
    return f"Available Prompt Templates:\n\n{table}\n\nTotal: {len(prompt_list)} prompt file(s) found"

def extract_prompt_info(prompt_file):
    """
    Extract basic information from a prompt file for API response
    
    Args:
        prompt_file (Path): Path to the prompt file
        
    Returns:
        dict: Dictionary with name, description, and other info
    """
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Initialize info dictionary with defaults
        info = {
            'filename': prompt_file.name,
            'description': 'No description provided',
            'version': 'Unknown',
            'author': 'Unknown',
            'institution': 'Unknown',
            'name': os.path.splitext(prompt_file.name)[0],
            'full_path': str(prompt_file.absolute())
        }
        
        # Try YAML parsing
        try:
            data = yaml.safe_load(content)
            
            if isinstance(data, dict):
                # Map YAML fields to info fields
                field_mapping = {
                    'prompt_name': 'name',
                    'prompt_version': 'version',
                    'prompt_author': 'author',
                    'prompt_author_institution': 'institution',
                    'prompt_description': 'description'
                }
                
                for yaml_field, info_field in field_mapping.items():
                    if yaml_field in data and data[yaml_field]:
                        info[info_field] = data[yaml_field]
            
        except Exception as e:
            logger.warning(f"YAML parsing failed for info extraction: {e}, using regex")
            # Fall back to regex pattern matching for common fields
            patterns = {
                'name': r'prompt_name:\s*(.*?)(?=\n\w+:|$)',
                'version': r'prompt_version:\s*(.*?)(?=\n\w+:|$)',
                'author': r'prompt_author:\s*(.*?)(?=\n\w+:|$)',
                'institution': r'prompt_author_institution:\s*(.*?)(?=\n\w+:|$)',
                'description': r'prompt_description:\s*(.*?)(?=\n\w+:|$)'
            }
            
            for field, pattern in patterns.items():
                matches = re.findall(pattern, content, re.DOTALL)
                if matches:
                    value = ' '.join([line.strip() for line in matches[0].strip().split('\n')])
                    info[field] = value
        
        return info
    
    except Exception as e:
        logger.error(f"Error extracting info from {prompt_file}: {e}")
        return {
            'filename': prompt_file.name,
            'description': f'Error reading file: {str(e)}',
            'version': 'Unknown',
            'author': 'Unknown',
            'institution': 'Unknown',
            'name': os.path.splitext(prompt_file.name)[0],
            'full_path': str(prompt_file.absolute())
        }

def extract_prompt_details(prompt_file):
    """
    Extract detailed content from a prompt file with improved YAML parsing
    
    Args:
        prompt_file (Path): Path to the prompt file
        
    Returns:
        dict: Dictionary with all parsed content
    """
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Initialize details dictionary
        details = {
            'raw_content': content
        }
        
        # Try YAML parsing with improved error handling
        try:
            import yaml
            
            # Use safe_load to prevent code execution
            data = yaml.safe_load(content)
            
            if isinstance(data, dict):
                # Store the parsed data directly
                details['parsed_data'] = data
            else:
                logger.warning(f"YAML parsing produced non-dictionary: {type(data)}")
                details['parsed_data'] = {"content": data}  # Wrap non-dict data
                
        except Exception as e:
            logger.warning(f"YAML parsing failed for {prompt_file}: {e}")
            details['parse_error'] = str(e)
            
            # Attempt a line-by-line parsing approach for common YAML formats
            try:
                parsed_data = {}
                current_section = None
                section_content = []
                lines = content.split('\n')
                
                for line in lines:
                    line = line.rstrip()
                    
                    # Check if this is a top-level key
                    if not line.startswith(' ') and ':' in line and not line.startswith('#'):
                        # Store previous section if any
                        if current_section and section_content:
                            parsed_data[current_section] = '\n'.join(section_content)
                            section_content = []
                        
                        # Extract new key
                        parts = line.split(':', 1)
                        key = parts[0].strip()
                        value = parts[1].strip() if len(parts) > 1 else ''
                        
                        if value in ['>', '|', '']:
                            # Multi-line value starts
                            current_section = key
                        else:
                            # Single line value
                            parsed_data[key] = value
                            current_section = None
                    
                    # Append to current section if inside one
                    elif current_section and line.strip():
                        # Remove consistent indentation from the beginning
                        if line.startswith('  '):
                            line = line[2:]
                        section_content.append(line)
                
                # Add the last section if any
                if current_section and section_content:
                    parsed_data[current_section] = '\n'.join(section_content)
                
                # Add the backup parsed data if primary parsing failed
                if 'parsed_data' not in details or not details['parsed_data']:
                    details['parsed_data'] = parsed_data
                
            except Exception as backup_e:
                logger.warning(f"Backup parsing also failed: {backup_e}")
        
        return details
    
    except Exception as e:
        logger.error(f"Error extracting details from {prompt_file}: {e}")
        return {'error': str(e), 'raw_content': ''}

# HTML UI route for browsing prompts
@app.route('/prompts-ui', methods=['GET'])
def prompts_ui():
    """Web UI for browsing prompts"""
    return render_template('prompts_ui.html')


@app.route('/api-key-management', methods=['GET', 'POST'])
def api_key_management_ui():
    """Web UI for API key management"""
    # For POST requests, validate the token and render the page directly
    # (avoids cookie-based redirect which fails in cross-origin iframes due
    # to third-party cookie blocking with SameSite=Lax)
    if request.method == 'POST':
        auth_token = request.form.get('auth_token')
        if auth_token:
            try:
                decoded = auth.verify_id_token(auth_token)
                user_email = decoded.get('email')
                if user_email:
                    logger.info(f"POST to /api-key-management. User {user_email} authenticated, rendering page directly.")

                    firebase_config = get_firebase_config()
                    base_url = request.url_root.rstrip('/')
                    if base_url.startswith('http:'):
                        base_url = 'https:' + base_url[5:]

                    return render_template('api_key_management.html',
                        api_key=firebase_config["apiKey"],
                        auth_domain=firebase_config["authDomain"],
                        project_id=firebase_config["projectId"],
                        storage_bucket=firebase_config.get("storageBucket", ""),
                        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
                        app_id=firebase_config["appId"],
                        server_url=base_url
                    )
            except Exception as e:
                logger.warning(f"POST to /api-key-management with invalid token: {e}")

            logger.warning("POST to /api-key-management with invalid auth_token. Redirecting to login.")
            return redirect('/login')
        else:
            # If no token is provided in the POST, redirect to login.
            logger.warning("POST to /api-key-management without auth_token. Redirecting to login.")
            return redirect('/login')

    # For GET requests, use existing authentication mechanism
    user = authenticate_request(request)
    if not user or not user.get('email'):
        logger.warning(f"Unauthenticated GET request to /api-key-management from {request.remote_addr}. Redirecting to login.")
        return redirect('/login')

    user_email = user.get('email')
    logger.info(f"User {user_email} accessing API key management UI")

    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()

    # Get the base URL from the request
    base_url = request.url_root.rstrip('/')
    # Force HTTPS
    if base_url.startswith('http:'):
        base_url = 'https:' + base_url[5:]

    return render_template('api_key_management.html',
        api_key=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"],
        server_url=base_url
    )

@app.route('/api-keys', methods=['GET'])
@authenticated_route
def list_api_keys():
    """List API keys for the authenticated user"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Get API keys where the user is the owner
        keys_ref = db.collection('api_keys').where('owner', '==', user_email).stream()
        
        keys = []
        for key_doc in keys_ref:
            key_data = key_doc.to_dict()
            # Add the document ID (the actual API key)
            key_data['key_id'] = key_doc.id
            
            # Format timestamps for frontend display
            if 'created_at' in key_data and hasattr(key_data['created_at'], '_seconds'):
                key_data['created_at'] = {
                    '_seconds': key_data['created_at']._seconds,
                    '_formatted': datetime.datetime.fromtimestamp(
                        key_data['created_at']._seconds
                    ).strftime('%Y-%m-%d %H:%M:%S')
                }
                
            if 'expires_at' in key_data and hasattr(key_data['expires_at'], '_seconds'):
                key_data['expires_at'] = {
                    '_seconds': key_data['expires_at']._seconds,
                    '_formatted': datetime.datetime.fromtimestamp(
                        key_data['expires_at']._seconds
                    ).strftime('%Y-%m-%d %H:%M:%S')
                }
            
            # Don't return the full API key for security - mask it
            if 'api_key' in key_data:
                key_data['api_key'] = key_data['api_key'][:8] + '...'
                
            keys.append(key_data)
        
        # Return the API keys with formatted dates
        return jsonify({
            'status': 'success',
            'count': len(keys),
            'api_keys': keys
        })
        
    except Exception as e:
        logger.error(f"Error listing API keys: {str(e)}")
        return jsonify({'error': f'Failed to list API keys: {str(e)}'}), 500

@app.route('/api-keys/create', methods=['POST'])
@authenticated_route
def create_api_key():
    """Create a new API key for the authenticated user (only if they have API key permission)"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Check if the user is an admin first (admins always have API key access)
        admin_doc = db.collection('admins').document(user_email).get()
        is_admin = admin_doc.exists
        
        if not is_admin:
            # Check if the user has API key access permission
            app_doc = db.collection('user_applications').document(user_email).get()
            
            if not app_doc.exists:
                logger.warning(f"User {user_email} attempted to create API key but has no application record")
                return jsonify({'error': 'User application not found'}), 404
            
            app_data = app_doc.to_dict()
            
            # Verify the user is approved and has API key access
            if app_data.get('status') != 'approved':
                logger.warning(f"User {user_email} attempted to create API key but is not approved")
                return jsonify({'error': 'Your account is not approved yet'}), 403
            
            has_api_key_access = bool(app_data.get('api_key_access', False))
            
            if not has_api_key_access:
                logger.warning(f"User {user_email} attempted to create API key but does not have API key permission")
                return jsonify({
                    'error': 'You do not have permission to create API keys. Please contact an administrator.',
                    'code': 'no_api_key_permission'
                }), 403
                
            logger.info(f"User {user_email} authorized to create API key (non-admin with permission)")
        else:
            logger.info(f"User {user_email} authorized to create API key (admin)")
        
        # Get data from request
        data = request.get_json() or {}
        
        # Generate a secure API key
        import secrets
        import string
        import datetime
        
        # Create a 32-character API key with letters and numbers
        api_key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        
        # Set up expiration if provided (default to 1 year)
        expires_days = data.get('expires_days', 365)
        expires_at = datetime.datetime.now() + datetime.timedelta(days=expires_days)
        
        # Create the API key record
        key_data = {
            'name': data.get('name', f"API Key for {user_email}"),
            'owner': user_email,
            'created_at': firestore.SERVER_TIMESTAMP,
            'expires_at': expires_at,
            'active': True,
            'description': data.get('description', '')
        }
        
        # Save to Firestore using the API key as the document ID
        db.collection('api_keys').document(api_key).set(key_data)
        
        logger.info(f"New API key created for {user_email}")
        
        # Return the API key to the user - this is the only time they'll see the full key
        return jsonify({
            'status': 'success',
            'message': 'API key created successfully',
            'api_key': api_key,
            'details': {
                'name': key_data['name'],
                'expires_at': expires_at.isoformat(),
                'owner': user_email
            }
        })
        
    except Exception as e:
        logger.error(f"Error creating API key: {str(e)}")
        return jsonify({'error': f'Failed to create API key: {str(e)}'}), 500

@app.route('/check-api-key-permission', methods=['GET'])
@authenticated_route
def check_api_key_permission():
    """Check if the authenticated user has permission to create API keys"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Check if the user is an admin first (admins always have API key access)
        admin_doc = db.collection('admins').document(user_email).get()
        is_admin = admin_doc.exists
        
        if is_admin:
            # Admins always have API key access
            return jsonify({
                'status': 'success',
                'has_api_key_permission': True,
                'is_admin': True
            })
        
        # Check regular user permissions
        app_doc = db.collection('user_applications').document(user_email).get()
        
        if not app_doc.exists:
            return jsonify({
                'status': 'error',
                'has_api_key_permission': False,
                'message': 'User application not found'
            }), 404
        
        app_data = app_doc.to_dict()
        
        # Check if approved and has API key access
        is_approved = app_data.get('status') == 'approved'
        has_api_key_access = app_data.get('api_key_access', False)
        
        # Make sure we use boolean values for clarity
        has_api_key_access = bool(has_api_key_access)
        
        logger.info(f"User {user_email} API key permission check: approved={is_approved}, has_api_key_access={has_api_key_access}")
        
        return jsonify({
            'status': 'success',
            'has_api_key_permission': is_approved and has_api_key_access,
            'is_approved': is_approved,
            'is_admin': False,
            'debug_info': {
                'email': user_email,
                'approved': is_approved,
                'api_key_access': has_api_key_access
            }
        })
        
    except Exception as e:
        logger.error(f"Error checking API key permission: {str(e)}")
        return jsonify({'error': f'Failed to check API key permission: {str(e)}'}), 500

    
@app.route('/api-keys/<key_id>/revoke', methods=['POST'])
@authenticated_route
def revoke_api_key(key_id):
    """Revoke an API key by setting it to inactive"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
        # Get the API key document
        key_doc = db.collection('api_keys').document(key_id).get()
        
        if not key_doc.exists:
            return jsonify({'error': 'API key not found'}), 404
        
        key_data = key_doc.to_dict()
        
        # Verify ownership
        if key_data.get('owner') != user_email:
            return jsonify({'error': 'You do not have permission to revoke this API key'}), 403
        
        # Update the key to inactive
        db.collection('api_keys').document(key_id).update({
            'active': False,
            'revoked_at': firestore.SERVER_TIMESTAMP,
            'revoked_by': user_email
        })
        
        return jsonify({
            'status': 'success',
            'message': 'API key revoked successfully'
        })
        
    except Exception as e:
        logger.error(f"Error revoking API key: {str(e)}")
        return jsonify({'error': f'Failed to revoke API key: {str(e)}'}), 500
    
@app.route('/admin/maintenance-status', methods=['GET'])
@authenticated_route
def get_maintenance_status_endpoint():
    """Get current maintenance status (admin only)"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        maintenance_enabled = get_maintenance_status()
        
        # Also get additional maintenance info from Firestore
        maintenance_doc = db.collection('system_config').document('maintenance').get()
        maintenance_info = {}
        if maintenance_doc.exists:
            data = maintenance_doc.to_dict()
            maintenance_info = {
                'last_updated': data.get('last_updated'),
                'updated_by': data.get('updated_by', 'Unknown')
            }
        
        return jsonify({
            'status': 'success',
            'maintenance_enabled': maintenance_enabled,
            'maintenance_info': maintenance_info
        })
    except Exception as e:
        logger.error(f"Error getting maintenance status: {str(e)}")
        return jsonify({'error': f'Failed to get maintenance status: {str(e)}'}), 500

@app.route('/admin/maintenance-mode', methods=['POST'])
@authenticated_route
def set_maintenance_mode_endpoint():
    """Set maintenance mode status (admin only)"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    admin_email = user.get('email')
    
    # Check if the user is an admin
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403
    
    try:
        # Get data from request
        data = request.get_json() or {}
        enabled = data.get('enabled', False)
        
        # Validate the input
        if not isinstance(enabled, bool):
            return jsonify({'error': 'enabled must be a boolean value'}), 400
        
        # Set maintenance mode in Firestore
        success = set_maintenance_status(enabled, admin_email)
        
        if not success:
            return jsonify({'error': 'Failed to update maintenance status in database'}), 500
        
        # Log the action
        logger.info(f"Maintenance mode {'enabled' if enabled else 'disabled'} by {admin_email}")
        
        return jsonify({
            'status': 'success',
            'message': f"Maintenance mode {'enabled' if enabled else 'disabled'}",
            'maintenance_enabled': enabled
        })
        
    except Exception as e:
        logger.error(f"Error setting maintenance mode: {str(e)}")
        return jsonify({'error': f'Failed to set maintenance mode: {str(e)}'}), 500

@app.route('/changelog', methods=['GET'])
def get_changelog():
    """API endpoint to get the application changelog from a YAML file."""
    changelog_file = os.path.join(project_root, 'changelog.yaml')
    
    if not os.path.exists(changelog_file):
        logger.error(f"Changelog file not found at {changelog_file}")
        return jsonify({'error': 'Changelog file not found.'}), 404
        
    try:
        with open(changelog_file, 'r', encoding='utf-8') as f:
            changelog_data = yaml.safe_load(f)
        
        # The YAML file is a list, so we can return it directly.
        # Add a status wrapper for good practice.
        return jsonify({
            'status': 'success',
            'changelog': changelog_data
        })
        
    except yaml.YAMLError as e:
        logger.error(f"Error parsing changelog.yaml: {e}")
        return jsonify({'error': f'Failed to parse changelog file: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Error reading changelog file: {e}")
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500
# HTML UI route for browsing the changelog
@app.route('/changelog-ui', methods=['GET'])
def changelog_ui():
    """Web UI for viewing the changelog."""
    return render_template('changelog_ui.html')



if __name__ == '__main__':
    # Only configure logging when running directly (not under Gunicorn)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    port = int(os.environ.get('PORT', 8080))
    logger.info('VoucherVision service is starting up directly (not under Gunicorn)...')
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
else:
    # Under Gunicorn: use gunicorn's handler as the single root handler
    # to avoid duplicate log lines from multiple handlers
    gunicorn_logger = logging.getLogger('gunicorn.error')
    root = logging.getLogger()
    root.handlers = gunicorn_logger.handlers
    root.setLevel(gunicorn_logger.level)
    # Stop Flask from adding its own handler
    app.logger.handlers = []
    app.logger.propagate = True
    logger.info('VoucherVision service starting under Gunicorn')
