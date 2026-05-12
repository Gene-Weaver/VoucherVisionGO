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
import zipfile
import warnings
from urllib.parse import urlparse
from urllib.parse import quote
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
from google.api_core import exceptions as google_exceptions
from google.cloud import firestore as _gc_firestore
from google.cloud import storage
from google.cloud.firestore_v1.base_query import FieldFilter
from google.auth.transport.requests import AuthorizedSession, Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google.oauth2 import service_account
import google.auth

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
    """Setup exactly one logging sink for direct runs or Gunicorn."""
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

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    gunicorn_logger = logging.getLogger('gunicorn.error')
    if gunicorn_logger.handlers:
        for handler in gunicorn_logger.handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(gunicorn_logger.level or logging.INFO)
        gunicorn_logger.propagate = False
    else:
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
    from vouchervision.vouchervision_main_slim import load_custom_cfg # type: ignore
    from vouchervision.utils_VoucherVision import VoucherVision # type: ignore
    from vouchervision.LLM_GoogleGemini import GoogleGeminiHandler # type: ignore
    from vouchervision.model_maps import ModelMaps # type: ignore
    from vouchervision.general_utils_slim import calculate_cost # type: ignore
    from TextCollage.CollageEngine import CollageEngine # type: ignore
except Exception as e:
    logger.error(f"Import ERROR: {e}")
    from vouchervision_main.vouchervision.OCR_Gemini import OCRGeminiProVision
    from vouchervision_main.vouchervision.OCR_sanitize import strip_headers, sanitize_for_storage, sanitize_excel_record, markdown_to_simple_text
    from vouchervision_main.vouchervision.vouchervision_main_slim import load_custom_cfg
    from vouchervision_main.vouchervision.utils_VoucherVision import VoucherVision
    from vouchervision_main.vouchervision.LLM_GoogleGemini import GoogleGeminiHandler
    from vouchervision_main.vouchervision.model_maps import ModelMaps
    from vouchervision_main.vouchervision.general_utils_slim import calculate_cost
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

PDF_JOB_RETENTION_DAYS = 7
PDF_JOB_RETENTION_SECONDS = PDF_JOB_RETENTION_DAYS * 24 * 60 * 60
PDF_JOB_ALLOWED_SOURCE_TYPES = {"server", "user_vertex"}
PDF_JOB_CONTROL_QUEUE = os.environ.get("PDF_JOBS_CONTROL_QUEUE", "pdf-control")
PDF_JOB_PAGE_QUEUE = os.environ.get("PDF_JOBS_PAGE_QUEUE", "pdf-pages")
PDF_JOB_QUEUE_LOCATION = os.environ.get("PDF_JOBS_QUEUE_LOCATION", "us-central1")
PDF_JOB_BUCKET = (
    os.environ.get("PDF_JOBS_GCS_BUCKET")
    or os.environ.get("FIREBASE_STORAGE_BUCKET")
    or get_firebase_config().get("storageBucket")
)
PDF_JOB_PREFIX = os.environ.get("PDF_JOBS_GCS_PREFIX", "pdf-jobs").strip("/") or "pdf-jobs"
PDF_JOB_MAX_PAGES = int(os.environ.get("PDF_JOB_MAX_PAGES", "200"))
PDF_JOB_MAX_LIST = int(os.environ.get("PDF_JOB_MAX_LIST", "25"))
PDF_JOB_INTERNAL_SECRET = os.environ.get("PDF_JOBS_INTERNAL_SECRET")
PDF_JOB_TASK_SERVICE_ACCOUNT = os.environ.get("PDF_JOBS_TASK_SERVICE_ACCOUNT_EMAIL")
PDF_JOB_PUBLIC_BASE_URL = os.environ.get("PDF_JOBS_PUBLIC_BASE_URL", "").rstrip("/")
PDF_JOB_TASK_TARGET_BASE_URL = os.environ.get("PDF_JOBS_TASK_TARGET_BASE_URL", "").rstrip("/")


def _get_default_project_id() -> str | None:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if project_id:
        return project_id
    project_id = os.environ.get("FIREBASE_PROJECT_ID")
    if project_id:
        return project_id
    try:
        _, project_id = google.auth.default()
        return project_id
    except Exception:
        return None


PDF_JOB_PROJECT_ID = _get_default_project_id()

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

# Regions where Vertex AI hosts Gemini and where users may direct their
# vertex_project=<their-project>&vertex_region=<region> requests. Limited to
# this allow-list so a typo surfaces as a clear 400 instead of an opaque 404
# from Vertex. Source: cloud.google.com/vertex-ai/generative-ai/docs/learn/locations
VERTEX_ALLOWED_REGIONS = frozenset({
    "us-central1", "us-east4", "us-west1",
    "europe-west1", "europe-west4", "europe-west3", "europe-west2", "europe-southwest1",
    "asia-northeast1", "asia-southeast1", "asia-south1",
    "australia-southeast1",
    "me-central1", "me-central2",
    "northamerica-northeast1", "southamerica-east1",
    "global",
})

VERTEX_PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _is_vertex_permission_error(exc):
    """Heuristic: did the underlying Gemini call fail because the user's project
    didn't grant the runtime SA Vertex AI permissions, or because the user typed
    the project ID wrong?"""
    msg = str(exc).upper()
    if "PERMISSION_DENIED" in msg or "PERMISSION DENIED" in msg:
        return True
    if " 403" in msg or "STATUS: 403" in msg or "CODE: 403" in msg:
        return True
    if "AIPLATFORM" in msg and "DENIED" in msg:
        return True
    return False


def _vertex_permission_error_message(project):
    return (
        f"Vertex AI call denied for project '{project}'. Verify that you "
        f"granted role 'roles/aiplatform.user' (Vertex AI User) to the "
        f"VoucherVisionGO service account "
        f"'vouchervision-vertex@vouchervision-387816.iam.gserviceaccount.com' "
        f"on that project, and that the Vertex AI API is enabled. "
        f"If the project was linked in VoucherVisionGO, double-check that "
        f"the linked project ID is correct and relink it in API Key "
        f"Management if needed. See the docs for setup steps."
    )


def _is_vertex_model_not_found_error(exc):
    """Heuristic: did the underlying Gemini call fail because the requested
    model isn't published in the requested region's catalog? Most common
    cause today: gemini-3.x previews are only in the 'global' catalog."""
    msg = str(exc).upper()
    has_404 = (
        "NOT_FOUND" in msg
        or " 404" in msg
        or "STATUS: 404" in msg
        or "CODE: 404" in msg
    )
    return has_404 and ("PUBLISHER MODEL" in msg or "AIPLATFORM" in msg)


def _vertex_model_not_found_message(project, region, model):
    hint = ""
    if model and "gemini-3" in str(model).lower() and region != "global":
        hint = (
            " Gemini 3.x preview models are currently published only in the "
            "'global' catalog on Vertex AI — retry with vertex_region=global."
        )
    return (
        f"Vertex AI does not have model '{model}' available in region "
        f"'{region}' for project '{project}'.{hint} "
        f"Check Model Garden in your project for the authoritative model list."
    )


def _validate_vertex_params(api_key, project, region):
    """Validate the user-supplied auth params for a /process[-url] request.

    Returns (error_message, status_code) on failure, or (None, None) when valid.
    Enforces: at most one of {api_key, project} is set; project ↔ region must
    be supplied together; region must be on the allow-list.
    """
    if project and api_key:
        return ("Pass either gemini_api_key OR vertex_project, not both.", 400)
    if project and not region:
        return ("vertex_project requires vertex_region.", 400)
    if region and not project:
        return ("vertex_region requires vertex_project.", 400)
    if region and region not in VERTEX_ALLOWED_REGIONS:
        return (
            f"vertex_region '{region}' is not a supported Vertex AI region. "
            f"Supported: {sorted(VERTEX_ALLOWED_REGIONS)}",
            400,
        )
    return (None, None)


def _normalize_vertex_project_id(project_id: str | None) -> str | None:
    if project_id is None:
        return None
    if not isinstance(project_id, str):
        project_id = str(project_id)
    project_id = project_id.strip().lower()
    return project_id or None


def _normalize_email_identity(email: str | None) -> str | None:
    if email is None:
        return None
    if not isinstance(email, str):
        email = str(email)
    email = email.strip().lower()
    return email or None


def _validate_vertex_project_id(project_id: str | None) -> tuple[str | None, str | None]:
    normalized = _normalize_vertex_project_id(project_id)
    if not normalized:
        return None, "Project ID is required."
    if not VERTEX_PROJECT_ID_PATTERN.match(normalized):
        return None, (
            "Project ID must be a valid Google Cloud project ID: 6-30 "
            "characters, lowercase letters/numbers/hyphens, starting with "
            "a letter and not ending with a hyphen."
        )
    return normalized, None


def _serialize_vertex_project(project_doc_or_dict):
    if hasattr(project_doc_or_dict, "to_dict"):
        payload = project_doc_or_dict.to_dict() or {}
        payload.setdefault("project_id", getattr(project_doc_or_dict, "id", None))
    else:
        payload = dict(project_doc_or_dict or {})

    payload["project_id"] = payload.get("project_id")
    payload["owner_email"] = payload.get("owner_email")
    payload["nickname"] = payload.get("nickname") or ""
    payload["active"] = bool(payload.get("active"))
    payload["status"] = "Active" if payload["active"] else "Revoked"
    for field_name in ("created_at", "updated_at", "revoked_at"):
        payload[field_name] = _format_event_timestamp(payload.get(field_name))
    return payload


def _validate_vertex_project_binding(project_id: str, caller_email: str) -> str | None:
    normalized_project_id, validation_error = _validate_vertex_project_id(project_id)
    if validation_error:
        return validation_error
    caller_email = _normalize_email_identity(caller_email)
    if not caller_email or caller_email == "unknown":
        return "Cannot resolve caller identity for Vertex project binding check."

    project_doc = db.collection("vertex_projects").document(normalized_project_id).get()
    if not project_doc.exists:
        return (
            f"Vertex project '{normalized_project_id}' is not linked to any "
            f"VoucherVisionGO account. Link it in API Key Management before "
            f"calling the API."
        )

    project_data = project_doc.to_dict() or {}
    if not bool(project_data.get("active")):
        return f"Vertex project '{normalized_project_id}' link has been revoked."
    if _normalize_email_identity(project_data.get("owner_email")) != caller_email:
        return (
            f"Vertex project '{normalized_project_id}' is not linked to your "
            f"VoucherVisionGO account."
        )
    return None


PAYMENT_AUTH_PARAM_ALIASES = {
    "gemini_api_key": ("gemini_api_key", "geminiApiKey"),
    "vertex_project": ("vertex_project", "vertexProject"),
    "vertex_region": ("vertex_region", "vertexRegion"),
}


def _clean_optional_request_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _lookup_request_value(container, field_name):
    if not container:
        return None
    for alias in PAYMENT_AUTH_PARAM_ALIASES[field_name]:
        value = _clean_optional_request_value(container.get(alias))
        if value is not None:
            return value
    return None


def _get_api_key_from_request(req):
    return req.headers.get('X-API-Key') or req.args.get('api_key')


def _get_id_token_from_request(req):
    auth_header = req.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split('Bearer ')[1]
    return req.args.get('token') or req.cookies.get('auth_token')


def get_request_auth_details(req) -> dict:
    """Return safe auth identity metadata for analytics."""
    api_key = _get_api_key_from_request(req)
    api_key_owner = None
    if api_key:
        try:
            api_key_doc = db.collection('api_keys').document(api_key).get()
            if api_key_doc.exists:
                api_key_owner = (api_key_doc.to_dict() or {}).get('owner')
        except Exception as e:
            logger.error(f"Error resolving API key owner for analytics: {e}")

    authenticated_via = 'api_key' if api_key else 'firebase'
    return {
        "authenticated_via": authenticated_via,
        "api_key_owner": api_key_owner,
    }


def get_payment_auth_context(req):
    """Resolve per-request Gemini/Vertex billing inputs across form, JSON, and query params."""
    json_body = req.get_json(silent=True) if req.is_json else {}
    request_sources = (
        req.form,
        json_body or {},
        req.args,
    )

    gemini_api_key = None
    vertex_project = None
    vertex_region = None

    for source in request_sources:
        gemini_api_key = gemini_api_key or _lookup_request_value(source, "gemini_api_key")
        vertex_project = vertex_project or _lookup_request_value(source, "vertex_project")
        vertex_region = vertex_region or _lookup_request_value(source, "vertex_region")

    # vertex_region without vertex_project is treated as server auth — clients
    # commonly send vertex_region=global as a default, and it shouldn't force
    # them into user-Vertex mode unless they also supply a project.
    if vertex_region and not vertex_project:
        vertex_region = None

    if vertex_project:
        auth_method = "user_vertex"
    elif gemini_api_key:
        auth_method = "user_gemini"
    else:
        auth_method = "server"

    return {
        "gemini_api_key": gemini_api_key,
        "vertex_project": vertex_project,
        "vertex_region": vertex_region,
        "auth_method": auth_method,
    }


def build_request_analytics_context(
    req,
    *,
    user_email: str,
    endpoint: str,
    auth_ctx: dict,
    request_id: str,
    prompt: str | None,
    ocr_only: bool,
    notebook_mode: bool,
    include_wfo: bool,
    include_cop90: bool,
    llm_model_name: str | None,
):
    auth_details = get_request_auth_details(req)
    return {
        "request_id": request_id,
        "user_email": user_email,
        "endpoint": endpoint,
        "authenticated_via": auth_details["authenticated_via"],
        "api_key_owner": auth_details["api_key_owner"],
        "auth_method": auth_ctx.get("auth_method"),
        "prompt": prompt,
        "ocr_only": bool(ocr_only),
        "notebook_mode": bool(notebook_mode),
        "include_wfo": bool(include_wfo),
        "include_cop90": bool(include_cop90),
        "llm_model_name": llm_model_name,
    }

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

DAILY_ALERT_THRESHOLDS = [100, 500, 1000, 2000, 5000]

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
            <p>Consider using <code>gemini-3.1-flash-lite</code> instead.
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

            <h3>Option 3 — Bill Gemini directly to your Google Cloud project (Vertex AI)</h3>
            <p>If Google AI Studio is not available in your region, or you prefer
            to use Vertex AI, you can have Gemini calls billed to your own GCP
            project instead. One-time setup: enable the Vertex AI API on a project
            of yours, then in that project's IAM grant the
            <strong>Vertex AI User</strong> role to
            <code>vouchervision-vertex@vouchervision-387816.iam.gserviceaccount.com</code>.</p>
            <p>Then pass <code>vertex_project</code> and <code>vertex_region</code>
            instead of <code>gemini_api_key</code>:</p>
            <pre style="background: #f4f4f4; padding: 12px; border-radius: 4px;">
# Python example
requests.post(
    "https://&lt;server&gt;/process",
    data={{
        "engines": "gemini-3.1-pro-preview",
        "vertex_project": "your-gcp-project-id",
        "vertex_region": "us-central1",
        ...
    }},
    files={{"file": open("image.jpg", "rb")}},
)</pre>

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


def _apply_impact_backfill(user_ref, data: dict, backfill_tokens: int = 5000) -> dict:
    """Idempotently apply the one-time historical impact rollup to a usage_statistics doc.

    Estimates: total_images_processed * estimate_impact(backfill_tokens). Writes the
    increments + sets backfill_applied_v2=True. Safe to call repeatedly: a no-op
    once the flag is set or if the doc has no prior usage.
    """
    if bool(data.get("backfill_applied_v2", False)):
        return {"applied": False, "reason": "already_applied"}

    total_uses = int(data.get("total_images_processed", 0) or 0)
    if total_uses <= 0:
        user_ref.update({
            "backfill_applied_v2": True,
            "backfill_tokens": backfill_tokens,
        })
        return {"applied": False, "reason": "no_prior_uses"}

    try:
        default_impact = estimate_impact(backfill_tokens)
    except Exception as e:
        logger.error(f"Backfill estimate_impact({backfill_tokens}) failed: {e}")
        default_impact = {}

    wh_per = float(default_impact.get("estimate_watt_hours", 0.0))
    gco2_per = float(default_impact.get("estimate_grams_CO2", 0.0))
    h2o_per = float(default_impact.get("estimate_milliliters_water",
                                       default_impact.get("estimate_mL_water", 0.0)))

    wh_total = wh_per * total_uses
    gco2_total = gco2_per * total_uses
    h2o_total = h2o_per * total_uses
    tokens_total = backfill_tokens * total_uses

    user_ref.update({
        "total_watt_hours": firestore.Increment(wh_total),
        "total_grams_CO2": firestore.Increment(gco2_total),
        "total_mL_water": firestore.Increment(h2o_total),
        "total_tokens_all": firestore.Increment(tokens_total),
        "backfill_applied_v2": True,
        "backfill_method": "total_images_processed * estimate_impact(5000)",
        "backfill_snapshot": default_impact,
        "backfill_tokens": backfill_tokens,
    })
    return {
        "applied": True,
        "total_uses": total_uses,
        "tokens_added": tokens_total,
        "wh_added": wh_total,
        "gco2_added": gco2_total,
        "h2o_added": h2o_total,
    }


AUTH_METHODS = ("server", "user_gemini", "user_vertex")


def _coerce_auth_metric(value, caster):
    try:
        return caster(value or 0)
    except (TypeError, ValueError):
        return caster(0)


def _empty_auth_method_bucket(caster):
    return {method: caster(0) for method in AUTH_METHODS}


def _normalize_auth_method_totals(raw_map, caster):
    bucket = _empty_auth_method_bucket(caster)
    if isinstance(raw_map, dict):
        for method in AUTH_METHODS:
            bucket[method] = _coerce_auth_metric(raw_map.get(method), caster)
    return bucket


def _normalize_auth_method_monthly(raw_map, current_month, caster):
    monthly = {}
    if isinstance(raw_map, dict):
        for month, raw_bucket in raw_map.items():
            monthly[str(month)] = _normalize_auth_method_totals(raw_bucket, caster)
    monthly.setdefault(current_month, _empty_auth_method_bucket(caster))
    return monthly


USAGE_EVENT_DIMENSIONS = (
    "auth_method",
    "ocr_model",
    "parsing_model",
    "endpoint",
    "source_type",
    "prompt",
    "ocr_only",
    "notebook_mode",
    "success",
)


def _coerce_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default=0.0):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _safe_url_host(url_value: str | None) -> str | None:
    if not url_value:
        return None
    try:
        return urlparse(url_value).netloc or None
    except Exception:
        return None


def _sanitize_error_message(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    sensitive_markers = (
        '"type": "service_account"',
        '"private_key"',
        '"private_key_id"',
        "-----BEGIN PRIVATE KEY-----",
        "-----END PRIVATE KEY-----",
        "GOOGLE_APPLICATION_CREDENTIALS",
    )
    if any(marker in text for marker in sensitive_markers):
        return "Sensitive credential details were redacted."
    return text[:500] if text else None


def _infer_success_from_result(result: dict | None, status_code: int) -> bool:
    if status_code != 200:
        return False
    if not isinstance(result, dict):
        return False
    success_payload = result.get("success")
    if isinstance(success_payload, dict):
        image_available = str(success_payload.get("image_available", "")).lower()
        ocr_ok = str(success_payload.get("ocr", "")).lower()
        llm_ok = str(success_payload.get("llm", "")).lower()
        if image_available == "false":
            return False
        return ocr_ok == "true" or llm_ok == "true"
    return "impact" in result or "ocr_info" in result


def _derive_error_type(result: dict | None, status_code: int, source_type: str, success: bool) -> str | None:
    if success:
        return None
    if source_type == "url" and status_code == 200:
        return "fetch_failure"
    if status_code == 400:
        return "validation_failure"
    if status_code == 403:
        return "vertex_permission"
    if status_code >= 500:
        return "processing_failure"
    return "request_failure"


def _extract_event_error_message(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    if result.get("error"):
        return _sanitize_error_message(result.get("error"))
    collage_info = result.get("collage_info")
    if isinstance(collage_info, dict) and collage_info.get("error"):
        return _sanitize_error_message(collage_info.get("error"))
    ocr_info = result.get("ocr_info")
    if isinstance(ocr_info, dict) and ocr_info.get("error"):
        return _sanitize_error_message(ocr_info.get("error"))
    return None


def _extract_ocr_analytics(ocr_info_raw) -> tuple[dict, list[str], dict]:
    sanitized = {}
    ocr_models = []
    totals = {
        "ocr_tokens_in_total": 0,
        "ocr_tokens_out_total": 0,
        "ocr_tokens_total": 0,
        "ocr_cost_total_usd": 0.0,
    }
    if not isinstance(ocr_info_raw, dict):
        return sanitized, ocr_models, totals

    for model_name, payload in ocr_info_raw.items():
        if not isinstance(payload, dict):
            if model_name == "error":
                sanitized["error"] = _sanitize_error_message(payload)
            continue
        ocr_models.append(model_name)
        tokens_in = _coerce_int(payload.get("tokens_in"))
        tokens_out = _coerce_int(payload.get("tokens_out"))
        total_tokens = tokens_in + tokens_out
        cost_in = _coerce_float(payload.get("cost_in"))
        cost_out = _coerce_float(payload.get("cost_out"))
        total_cost = _coerce_float(payload.get("total_cost"), cost_in + cost_out)
        sanitized[model_name] = {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": total_tokens,
            "cost_in": cost_in,
            "cost_out": cost_out,
            "total_cost": total_cost,
            "rates_in": _coerce_float(payload.get("rates_in")),
            "rates_out": _coerce_float(payload.get("rates_out")),
        }
        totals["ocr_tokens_in_total"] += tokens_in
        totals["ocr_tokens_out_total"] += tokens_out
        totals["ocr_tokens_total"] += total_tokens
        totals["ocr_cost_total_usd"] += total_cost

    if "error" in ocr_info_raw and "error" not in sanitized:
        sanitized["error"] = _sanitize_error_message(ocr_info_raw.get("error"))

    return sanitized, sorted(ocr_models), totals


def _extract_parsing_analytics(parsing_info_raw) -> tuple[dict, dict]:
    parsing_info_raw = parsing_info_raw if isinstance(parsing_info_raw, dict) else {}
    model_name = parsing_info_raw.get("model") or ""
    tokens_in = _coerce_int(parsing_info_raw.get("input"))
    tokens_out = _coerce_int(parsing_info_raw.get("output"))
    total_tokens = tokens_in + tokens_out
    cost_in = _coerce_float(parsing_info_raw.get("cost_in"))
    cost_out = _coerce_float(parsing_info_raw.get("cost_out"))
    total_cost = cost_in + cost_out
    sanitized = {
        "model": model_name,
        "input": tokens_in,
        "output": tokens_out,
        "total_tokens": total_tokens,
        "cost_in": cost_in,
        "cost_out": cost_out,
        "total_cost": total_cost,
    }
    convenience = {
        "parsing_model": model_name or None,
        "parsing_tokens_in": tokens_in,
        "parsing_tokens_out": tokens_out,
        "parsing_tokens_total": total_tokens,
        "parsing_cost_total_usd": total_cost,
    }
    return sanitized, convenience


def sanitize_usage_event(event: dict) -> dict:
    """Strip repo/user-content fields that are unnecessary or risky for analytics."""
    blocked_keys = {
        "ocr",
        "formatted_json",
        "formatted_md",
        "collage_info",
        "base64_image",
    }
    sanitized = {}
    for key, value in (event or {}).items():
        if key in blocked_keys:
            continue
        sanitized[key] = value
    return sanitized


def build_usage_event(
    *,
    analytics_ctx: dict,
    result: dict,
    status_code: int,
    source_type: str,
    filename: str | None = None,
    url_source: str | None = None,
    source_pdf: str | None = None,
    page_index: int | None = None,
    page_count: int | None = None,
    success: bool | None = None,
    include_in_rollup: bool = True,
    error_type: str | None = None,
    error_message_safe: str | None = None,
):
    result = result if isinstance(result, dict) else {}
    success = _infer_success_from_result(result, status_code) if success is None else bool(success)
    ocr_info, ocr_models, ocr_totals = _extract_ocr_analytics(result.get("ocr_info"))
    parsing_info, parsing_totals = _extract_parsing_analytics(result.get("parsing_info"))
    impact = result.get("impact") if isinstance(result.get("impact"), dict) else {}

    total_tokens_all = _coerce_int(
        impact.get(
            "total_tokens_all",
            ocr_totals["ocr_tokens_total"] + parsing_totals["parsing_tokens_total"],
        )
    )
    total_request_cost_usd = _coerce_float(
        result.get(
            "total_request_cost_usd",
            ocr_totals["ocr_cost_total_usd"] + parsing_totals["parsing_cost_total_usd"],
        )
    )

    safe_error_message = (
        _sanitize_error_message(error_message_safe)
        or _extract_event_error_message(result)
    )
    derived_error_type = error_type or _derive_error_type(result, status_code, source_type, success)

    event = {
        "event_id": str(uuid.uuid4()),
        "request_id": analytics_ctx["request_id"],
        "parent_request_id": analytics_ctx["request_id"],
        "user_email": analytics_ctx["user_email"],
        "api_key_owner": analytics_ctx.get("api_key_owner"),
        "authenticated_via": analytics_ctx.get("authenticated_via"),
        "auth_method": analytics_ctx.get("auth_method"),
        "endpoint": analytics_ctx.get("endpoint"),
        "source_type": source_type,
        "source_pdf": source_pdf,
        "page_index": page_index,
        "page_count": page_count,
        "filename": filename or result.get("filename"),
        "url_host": _safe_url_host(url_source or result.get("url_source")),
        "prompt": analytics_ctx.get("prompt"),
        "ocr_only": bool(analytics_ctx.get("ocr_only")),
        "notebook_mode": bool(analytics_ctx.get("notebook_mode")),
        "include_wfo": bool(analytics_ctx.get("include_wfo")),
        "include_cop90": bool(analytics_ctx.get("include_cop90")),
        "success": success,
        "status_code": int(status_code),
        "error_type": derived_error_type,
        "error_message_safe": safe_error_message,
        "ocr_models": ocr_models,
        "ocr_info": ocr_info,
        "parsing_model": parsing_totals["parsing_model"],
        "parsing_info": parsing_info,
        "ocr_tokens_in_total": ocr_totals["ocr_tokens_in_total"],
        "ocr_tokens_out_total": ocr_totals["ocr_tokens_out_total"],
        "ocr_tokens_total": ocr_totals["ocr_tokens_total"],
        "ocr_cost_total_usd": round(ocr_totals["ocr_cost_total_usd"], 10),
        "parsing_tokens_in": parsing_totals["parsing_tokens_in"],
        "parsing_tokens_out": parsing_totals["parsing_tokens_out"],
        "parsing_tokens_total": parsing_totals["parsing_tokens_total"],
        "parsing_cost_total_usd": round(parsing_totals["parsing_cost_total_usd"], 10),
        "total_tokens_all": total_tokens_all,
        "total_request_cost_usd": total_request_cost_usd,
        "impact": impact,
        "total_watt_hours": _coerce_float(impact.get("estimate_watt_hours")),
        "total_grams_CO2": _coerce_float(impact.get("estimate_grams_CO2")),
        "total_mL_water": _coerce_float(
            impact.get("estimate_milliliters_water", impact.get("estimate_mL_water"))
        ),
        "include_in_rollup": bool(include_in_rollup),
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    return sanitize_usage_event(event)


def record_usage_event(event: dict) -> dict:
    event_payload = sanitize_usage_event(dict(event or {}))
    event_payload.setdefault("event_id", str(uuid.uuid4()))
    event_payload.setdefault("created_at", firestore.SERVER_TIMESTAMP)
    db.collection("usage_events").document(event_payload["event_id"]).set(event_payload)
    return event_payload


def record_usage_events(events: list[dict]) -> list[dict]:
    batch = db.batch()
    recorded = []
    for event in events or []:
        payload = sanitize_usage_event(dict(event or {}))
        payload.setdefault("event_id", str(uuid.uuid4()))
        payload.setdefault("created_at", firestore.SERVER_TIMESTAMP)
        batch.set(db.collection("usage_events").document(payload["event_id"]), payload)
        recorded.append(payload)
    if recorded:
        batch.commit()
    return recorded


def persist_usage_events_and_rollups(events: list[dict], *, route_label: str) -> list[dict]:
    """Write events first, then project them into usage_statistics."""
    recorded = record_usage_events(events)
    for event in recorded:
        try:
            update_usage_statistics_from_event(event)
        except Exception:
            logger.exception(
                "Rollup projection failed after usage_events write route=%s request_id=%s event_id=%s",
                route_label,
                event.get("request_id"),
                event.get("event_id"),
            )
    return recorded


def update_usage_statistics_from_event(event: dict, *, backfill_tokens: int = 5000):
    """Project one normalized usage event into the legacy usage_statistics doc."""
    if not event or not event.get("include_in_rollup", True):
        return

    user_email = event.get("user_email")
    if not user_email or user_email == 'unknown':
        logger.warning("Cannot track usage for unknown user")
        return

    try:
        now = datetime.datetime.now()
        current_month = now.strftime("%Y-%m")
        current_day = now.strftime("%Y-%m-%d")

        t_all = _coerce_int(event.get("total_tokens_all"))
        wh = _coerce_float(event.get("total_watt_hours"))
        gco2 = _coerce_float(event.get("total_grams_CO2"))
        h2o = _coerce_float(event.get("total_mL_water"))
        request_cost_usd = _coerce_float(event.get("total_request_cost_usd"))
        auth_method = event.get("auth_method")
        ocr_models = event.get("ocr_models") if isinstance(event.get("ocr_models"), list) else []
        llm_model_name = event.get("parsing_model")

        user_ref = db.collection("usage_statistics").document(user_email)
        doc = user_ref.get()

        if doc.exists:
            data = doc.to_dict() or {}

            bf = _apply_impact_backfill(user_ref, data, backfill_tokens=backfill_tokens)
            if bf.get("applied"):
                logger.info(
                    f"Applied backfill for {user_email}: "
                    f"{bf['total_uses']} × {backfill_tokens} tokens."
                )

            monthly_usage = data.get("monthly_usage", {})
            monthly_usage[current_month] = monthly_usage.get(current_month, 0) + 1

            daily_usage = data.get("daily_usage", {})
            prev_daily_count = daily_usage.get(current_day, 0)
            daily_usage[current_day] = prev_daily_count + 1

            ocr_info = data.get("ocr_info", {})
            for engine in ocr_models:
                if engine:
                    ocr_info[engine] = ocr_info.get(engine, 0) + 1

            llm_info = data.get("llm_info", {})
            if llm_model_name:
                llm_info[llm_model_name] = llm_info.get(llm_model_name, 0) + 1

            auth_method_usage = _normalize_auth_method_totals(
                data.get("auth_method_usage"), int
            )
            auth_method_monthly = _normalize_auth_method_monthly(
                data.get("auth_method_monthly"), current_month, int
            )
            cost_by_auth_method = _normalize_auth_method_totals(
                data.get("cost_by_auth_method"), float
            )
            cost_monthly_by_auth = _normalize_auth_method_monthly(
                data.get("cost_monthly_by_auth"), current_month, float
            )

            cost_total_usd = _coerce_auth_metric(data.get("cost_total_usd"), float)
            if auth_method in AUTH_METHODS:
                auth_method_usage[auth_method] += 1
                auth_method_monthly[current_month][auth_method] += 1
                if request_cost_usd > 0:
                    cost_total_usd += request_cost_usd
                    cost_by_auth_method[auth_method] += request_cost_usd
                    cost_monthly_by_auth[current_month][auth_method] += request_cost_usd

            increments = {
                "total_images_processed": firestore.Increment(1),
                "total_tokens_all": firestore.Increment(t_all),
                "total_watt_hours": firestore.Increment(wh),
                "total_grams_CO2": firestore.Increment(gco2),
                "total_mL_water": firestore.Increment(h2o),
            }

            if "gemini_pro_usage_limit" not in data:
                increments["gemini_pro_usage_limit"] = GEMINI_PRO_DEFAULT_LIMIT

            user_ref.update({
                **increments,
                "user_email": user_email,
                "last_processed_at": firestore.SERVER_TIMESTAMP,
                "monthly_usage": monthly_usage,
                "daily_usage": daily_usage,
                "ocr_info": ocr_info,
                "llm_info": llm_info,
                "auth_method_usage": auth_method_usage,
                "auth_method_monthly": auth_method_monthly,
                "cost_total_usd": cost_total_usd,
                "cost_by_auth_method": cost_by_auth_method,
                "cost_monthly_by_auth": cost_monthly_by_auth,
                "last_auth_method": auth_method or "unknown",
                "last_event_id": event.get("event_id"),
                "last_request_id": event.get("request_id"),
                "last_impact_snapshot": event.get("impact") or {},
            })

        else:
            monthly_usage = {current_month: 1}
            daily_usage = {current_day: 1}

            ocr_info = {}
            for engine in ocr_models:
                if engine:
                    ocr_info[engine] = 1

            llm_info = {}
            if llm_model_name:
                llm_info[llm_model_name] = 1

            auth_method_usage = _empty_auth_method_bucket(int)
            auth_method_monthly = {current_month: _empty_auth_method_bucket(int)}
            cost_by_auth_method = _empty_auth_method_bucket(float)
            cost_monthly_by_auth = {current_month: _empty_auth_method_bucket(float)}
            cost_total_usd = 0.0
            if auth_method in AUTH_METHODS:
                auth_method_usage[auth_method] = 1
                auth_method_monthly[current_month][auth_method] = 1
                if request_cost_usd > 0:
                    cost_total_usd = request_cost_usd
                    cost_by_auth_method[auth_method] = request_cost_usd
                    cost_monthly_by_auth[current_month][auth_method] = request_cost_usd

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
                "auth_method_usage": auth_method_usage,
                "auth_method_monthly": auth_method_monthly,
                "cost_total_usd": cost_total_usd,
                "cost_by_auth_method": cost_by_auth_method,
                "cost_monthly_by_auth": cost_monthly_by_auth,
                "last_auth_method": auth_method or "unknown",
                "backfill_applied_v2": True,
                "backfill_tokens": backfill_tokens,
                "last_impact_snapshot": event.get("impact") or {},
                "last_event_id": event.get("event_id"),
                "last_request_id": event.get("request_id"),
                "gemini_pro_usage_limit": GEMINI_PRO_DEFAULT_LIMIT,
            }, merge=True)

        logger.info(
            "Updated usage statistics from event %s for %s",
            event.get("event_id"),
            user_email,
        )

        _send_daily_usage_alerts(
            user_email,
            current_day,
            prev_daily_count if doc.exists else 0,
        )

    except Exception as e:
        logger.error(f"Error updating usage statistics from event: {str(e)}")


def update_usage_statistics(
    user_email: str,
    engines: list[str] | None = None,
    llm_model_name: str | None = None,
    est_impact: dict | None = None,
    *,
    auth_method: str | None = None,
    request_cost_usd: float = 0.0,
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

            # One-time historical backfill (idempotent; helper handles the gate).
            bf = _apply_impact_backfill(user_ref, data, backfill_tokens=backfill_tokens)
            if bf.get("applied"):
                logger.info(
                    f"Applied backfill for {user_email}: "
                    f"{bf['total_uses']} × {backfill_tokens} tokens."
                )

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

            auth_method_usage = _normalize_auth_method_totals(
                data.get("auth_method_usage"), int
            )
            auth_method_monthly = _normalize_auth_method_monthly(
                data.get("auth_method_monthly"), current_month, int
            )
            cost_by_auth_method = _normalize_auth_method_totals(
                data.get("cost_by_auth_method"), float
            )
            cost_monthly_by_auth = _normalize_auth_method_monthly(
                data.get("cost_monthly_by_auth"), current_month, float
            )

            cost_total_usd = _coerce_auth_metric(data.get("cost_total_usd"), float)
            if auth_method in AUTH_METHODS:
                auth_method_usage[auth_method] += 1
                auth_method_monthly[current_month][auth_method] += 1
                if request_cost_usd and request_cost_usd > 0:
                    cost_total_usd += float(request_cost_usd)
                    cost_by_auth_method[auth_method] += float(request_cost_usd)
                    cost_monthly_by_auth[current_month][auth_method] += float(request_cost_usd)

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
                "user_email": user_email,
                "last_processed_at": firestore.SERVER_TIMESTAMP,
                "monthly_usage": monthly_usage,
                "daily_usage": daily_usage,
                "ocr_info": ocr_info,
                "llm_info": llm_info,
                "auth_method_usage": auth_method_usage,
                "auth_method_monthly": auth_method_monthly,
                "cost_total_usd": cost_total_usd,
                "cost_by_auth_method": cost_by_auth_method,
                "cost_monthly_by_auth": cost_monthly_by_auth,
                "last_auth_method": auth_method or "unknown",
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

            # Seed auth-method + cost maps so the doc shape is predictable
            # from the first request. The selected method gets a 1 (and the
            # request's cost, if any); the other two are pinned to 0.
            auth_method_usage = _empty_auth_method_bucket(int)
            auth_method_monthly = {current_month: _empty_auth_method_bucket(int)}
            cost_by_auth_method = _empty_auth_method_bucket(float)
            cost_monthly_by_auth = {current_month: _empty_auth_method_bucket(float)}
            cost_total_usd = 0.0
            if auth_method in AUTH_METHODS:
                auth_method_usage[auth_method] = 1
                auth_method_monthly[current_month][auth_method] = 1
                if request_cost_usd and request_cost_usd > 0:
                    cost_total_usd = float(request_cost_usd)
                    cost_by_auth_method[auth_method] = float(request_cost_usd)
                    cost_monthly_by_auth[current_month][auth_method] = float(request_cost_usd)

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
                "auth_method_usage": auth_method_usage,
                "auth_method_monthly": auth_method_monthly,
                "cost_total_usd": cost_total_usd,
                "cost_by_auth_method": cost_by_auth_method,
                "cost_monthly_by_auth": cost_monthly_by_auth,
                "last_auth_method": auth_method or "unknown",
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


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _pdf_job_expiration_time() -> datetime.datetime:
    return _now_utc() + datetime.timedelta(days=PDF_JOB_RETENTION_DAYS)


class _CredentialError(Exception):
    """Raised for credential problems with a sanitized message."""


_PDF_JOB_STORAGE_CLIENT = None


def _build_storage_client():
    """Return a storage client without ever surfacing raw credential content."""
    credential_project = PDF_JOB_PROJECT_ID or None

    for var in ("GOOGLE_APPLICATION_CREDENTIALS", "firebase-admin-key"):
        raw = os.environ.get(var, "")
        if not raw:
            continue
        if os.path.isfile(raw):
            try:
                return storage.Client(project=credential_project) if credential_project else storage.Client()
            except Exception:
                logger.error("storage.Client() failed reading credentials file from %s", var)
                raise _CredentialError("Cloud Storage client initialization failed.")
        if raw.lstrip().startswith("{"):
            try:
                info = json.loads(raw)
                creds = service_account.Credentials.from_service_account_info(info)
                project = credential_project or info.get("project_id")
                return storage.Client(project=project, credentials=creds)
            except _CredentialError:
                raise
            except Exception:
                logger.error("storage.Client() failed reading inline service-account credentials from %s", var)
                raise _CredentialError("Cloud Storage client initialization failed.")

    try:
        return storage.Client(project=credential_project) if credential_project else storage.Client()
    except Exception:
        logger.error("storage.Client() ADC fallback failed")
        raise _CredentialError("Cloud Storage client initialization failed.")


def _get_storage_client():
    global _PDF_JOB_STORAGE_CLIENT
    if _PDF_JOB_STORAGE_CLIENT is None:
        _PDF_JOB_STORAGE_CLIENT = _build_storage_client()
    return _PDF_JOB_STORAGE_CLIENT


def _get_pdf_job_bucket_name() -> str:
    bucket_name = (PDF_JOB_BUCKET or "").replace("gs://", "").strip("/")
    if not bucket_name:
        raise RuntimeError(
            "PDF async jobs are not configured: missing PDF_JOBS_GCS_BUCKET/FIREBASE_STORAGE_BUCKET."
        )
    return bucket_name


def _pdf_job_blob_path(job_id: str, *parts: str) -> str:
    clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join([PDF_JOB_PREFIX, job_id] + clean_parts)


def _upload_pdf_job_bytes(blob_path: str, payload: bytes, *, content_type: str) -> str:
    bucket = _get_storage_client().bucket(_get_pdf_job_bucket_name())
    blob = bucket.blob(blob_path)
    blob.upload_from_string(payload, content_type=content_type)
    return blob_path


def _upload_pdf_job_json(blob_path: str, payload: dict | list) -> str:
    data = json.dumps(payload, cls=OrderedJsonEncoder, ensure_ascii=False, indent=2).encode("utf-8")
    return _upload_pdf_job_bytes(blob_path, data, content_type="application/json")


def _download_pdf_job_bytes(blob_path: str) -> bytes:
    bucket = _get_storage_client().bucket(_get_pdf_job_bucket_name())
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise FileNotFoundError(blob_path)
    return blob.download_as_bytes()


def _delete_pdf_job_prefix(job_id: str):
    try:
        bucket = _get_storage_client().bucket(_get_pdf_job_bucket_name())
        prefix = _pdf_job_blob_path(job_id)
        blobs = list(bucket.list_blobs(prefix=prefix))
        for blob in blobs:
            blob.delete()
    except Exception as e:
        logger.warning(f"Unable to delete PDF job artifacts for {job_id}: {e}")


def _serialize_pdf_job(job_doc_or_dict):
    if hasattr(job_doc_or_dict, "to_dict"):
        payload = job_doc_or_dict.to_dict() or {}
        payload.setdefault("job_id", getattr(job_doc_or_dict, "id", None))
    else:
        payload = dict(job_doc_or_dict or {})

    for field_name in (
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "expires_at",
        "finalize_enqueued_at",
        "email_sent_at",
    ):
        payload[field_name] = _format_event_timestamp(payload.get(field_name))

    payload["page_count"] = _coerce_int(payload.get("page_count"))
    payload["completed_pages"] = _coerce_int(payload.get("completed_pages"))
    payload["successful_pages"] = _coerce_int(payload.get("successful_pages"))
    payload["failed_pages"] = _coerce_int(payload.get("failed_pages"))
    payload["progress_percent"] = min(
        100,
        round(
            (
                _coerce_int(payload.get("completed_pages"))
                / max(_coerce_int(payload.get("page_count")), 1)
            ) * 100
        ) if _coerce_int(payload.get("page_count")) else 0,
    )
    return payload


def _serialize_pdf_job_page(page_doc_or_dict):
    if hasattr(page_doc_or_dict, "to_dict"):
        payload = page_doc_or_dict.to_dict() or {}
        payload.setdefault("page_id", getattr(page_doc_or_dict, "id", None))
    else:
        payload = dict(page_doc_or_dict or {})

    for field_name in ("created_at", "updated_at", "expires_at"):
        payload[field_name] = _format_event_timestamp(payload.get(field_name))
    payload["page_index"] = _coerce_int(payload.get("page_index"))
    payload["attempt_count"] = _coerce_int(payload.get("attempt_count"))
    payload["status_code"] = _coerce_int(payload.get("status_code"))
    payload["total_request_cost_usd"] = _coerce_float(payload.get("total_request_cost_usd"))
    payload["total_tokens_all"] = _coerce_int(payload.get("total_tokens_all"))
    return payload


def _resolve_pdf_job_public_base_url() -> str:
    if PDF_JOB_PUBLIC_BASE_URL:
        return PDF_JOB_PUBLIC_BASE_URL
    try:
        return request.host_url.rstrip("/")
    except RuntimeError:
        return ""


def _resolve_pdf_job_task_base_url() -> str:
    if PDF_JOB_TASK_TARGET_BASE_URL:
        return PDF_JOB_TASK_TARGET_BASE_URL
    try:
        return request.host_url.rstrip("/")
    except RuntimeError:
        return ""


def _build_pdf_job_download_url(job_data: dict) -> str | None:
    base_url = (job_data.get("public_base_url") or "").rstrip("/")
    job_id = job_data.get("job_id")
    token = job_data.get("download_token")
    if not (base_url and job_id and token):
        return None
    return f"{base_url}/pdf-jobs/{quote(str(job_id))}/download?token={quote(str(token))}"


def _build_pdf_job_email_body(job_data: dict) -> str:
    download_url = _build_pdf_job_download_url(job_data) or "#"
    filename = job_data.get("source_pdf_filename") or "your PDF"
    expires_at = _format_event_timestamp(job_data.get("expires_at")) or "in 1 week"
    page_count = _coerce_int(job_data.get("page_count"))
    success_count = _coerce_int(job_data.get("successful_pages"))
    failed_count = _coerce_int(job_data.get("failed_pages"))
    status = job_data.get("status") or "completed"
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
                <h2 style="color: #2E7D32;">Your VoucherVision PDF Job Is Ready</h2>
                <p><strong>{filename}</strong> has finished processing.</p>
                <div style="background:#f5f5f5; border-radius:8px; padding:16px; margin:18px 0;">
                    <p style="margin:0 0 8px 0;"><strong>Status:</strong> {status}</p>
                    <p style="margin:0 0 8px 0;"><strong>Pages:</strong> {page_count}</p>
                    <p style="margin:0 0 8px 0;"><strong>Successful pages:</strong> {success_count}</p>
                    <p style="margin:0;"><strong>Failed pages:</strong> {failed_count}</p>
                </div>
                <div style="margin: 28px 0; text-align: center;">
                    <a href="{download_url}"
                       style="background-color:#2E7D32; color:white; padding:12px 18px; text-decoration:none; border-radius:6px; font-weight:bold;">
                        Download ZIP Bundle
                    </a>
                </div>
                <p>This download is available for <strong>1 week</strong>.</p>
                <p><strong>Expires:</strong> {expires_at}</p>
                <p>You can also review the job status from the PDF Jobs tab on the VoucherVisionGO website.</p>
                <p>Best regards,<br>The VoucherVision Team</p>
            </div>
        </body>
    </html>
    """


def _send_pdf_job_completion_email(job_data: dict) -> bool:
    sender = app.config.get("email_sender")
    if not sender:
        logger.warning("PDF job email skipped: email sender missing")
        return False
    user_email = _normalize_email_identity(job_data.get("user_email"))
    if not user_email:
        logger.warning("PDF job email skipped: missing user_email")
        return False
    subject = f"Your VoucherVision PDF results are ready: {job_data.get('source_pdf_filename') or job_data.get('job_id')}"
    return sender.send_email(user_email, subject, _build_pdf_job_email_body(job_data))


def _get_google_authorized_session() -> AuthorizedSession:
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    for var in ("GOOGLE_APPLICATION_CREDENTIALS", "firebase-admin-key"):
        raw = os.environ.get(var, "")
        if not raw:
            continue
        if os.path.isfile(raw):
            break
        if raw.lstrip().startswith("{"):
            try:
                info = json.loads(raw)
                creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
                return AuthorizedSession(creds)
            except _CredentialError:
                raise
            except Exception:
                logger.error("Authorized session init failed reading inline credentials from %s", var)
                raise _CredentialError("Cloud Tasks client initialization failed.")
    try:
        credentials, _ = google.auth.default(scopes=scopes)
    except Exception:
        logger.error("Authorized session ADC fallback failed")
        raise _CredentialError("Cloud Tasks client initialization failed.")
    return AuthorizedSession(credentials)


def _enqueue_cloud_task(queue_name: str, target_url: str, payload: dict, *, delay_seconds: int = 0) -> dict:
    if not PDF_JOB_PROJECT_ID:
        raise RuntimeError("Cannot enqueue PDF jobs: missing Google Cloud project ID.")
    if not target_url:
        raise RuntimeError("Cannot enqueue PDF jobs: missing target URL.")

    task_url = (
        f"https://cloudtasks.googleapis.com/v2/projects/{PDF_JOB_PROJECT_ID}"
        f"/locations/{PDF_JOB_QUEUE_LOCATION}/queues/{queue_name}/tasks"
    )
    headers = {"Content-Type": "application/json"}
    if PDF_JOB_INTERNAL_SECRET:
        headers["X-Pdf-Task-Secret"] = PDF_JOB_INTERNAL_SECRET

    http_request = {
        "httpMethod": "POST",
        "url": target_url,
        "headers": headers,
        "body": base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8"),
    }
    if PDF_JOB_TASK_SERVICE_ACCOUNT:
        http_request["oidcToken"] = {
            "serviceAccountEmail": PDF_JOB_TASK_SERVICE_ACCOUNT,
            "audience": target_url,
        }

    task = {"httpRequest": http_request}
    if delay_seconds > 0:
        run_at = _now_utc() + datetime.timedelta(seconds=delay_seconds)
        task["scheduleTime"] = {"seconds": int(run_at.timestamp())}

    session = _get_google_authorized_session()
    response = session.post(task_url, json={"task": task}, timeout=30)
    response.raise_for_status()
    return response.json()


def _enqueue_pdf_split_task(job_data: dict):
    target = f"{(job_data.get('task_base_url') or '').rstrip('/')}/internal/pdf-jobs/{job_data['job_id']}/split"
    return _enqueue_cloud_task(PDF_JOB_CONTROL_QUEUE, target, {"job_id": job_data["job_id"]})


def _enqueue_pdf_page_task(job_data: dict, page_index: int):
    target = (
        f"{(job_data.get('task_base_url') or '').rstrip('/')}/internal/pdf-jobs/"
        f"{job_data['job_id']}/pages/{int(page_index)}/process"
    )
    return _enqueue_cloud_task(
        PDF_JOB_PAGE_QUEUE,
        target,
        {"job_id": job_data["job_id"], "page_index": int(page_index)},
    )


def _enqueue_pdf_finalize_task(job_data: dict):
    target = f"{(job_data.get('task_base_url') or '').rstrip('/')}/internal/pdf-jobs/{job_data['job_id']}/finalize"
    return _enqueue_cloud_task(PDF_JOB_CONTROL_QUEUE, target, {"job_id": job_data["job_id"]})


def _enqueue_pdf_email_task(job_data: dict):
    target = f"{(job_data.get('task_base_url') or '').rstrip('/')}/internal/pdf-jobs/{job_data['job_id']}/send-email"
    return _enqueue_cloud_task(PDF_JOB_CONTROL_QUEUE, target, {"job_id": job_data["job_id"]})


def _verify_internal_pdf_task_request() -> tuple[bool, str | None]:
    if not request.headers.get("X-CloudTasks-TaskName"):
        return False, "Missing Cloud Tasks headers."

    if PDF_JOB_INTERNAL_SECRET:
        supplied_secret = request.headers.get("X-Pdf-Task-Secret")
        if supplied_secret != PDF_JOB_INTERNAL_SECRET:
            return False, "Invalid internal task secret."

    if PDF_JOB_TASK_SERVICE_ACCOUNT:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False, "Missing task bearer token."
        token = auth_header.split("Bearer ", 1)[1]
        try:
            claims = google_id_token.verify_token(token, GoogleAuthRequest())
        except Exception as e:
            return False, f"Task token verification failed: {e}"

        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
        base_url = request.base_url
        candidates = {base_url}
        if forwarded_proto in ("http", "https") and "://" in base_url:
            candidates.add(forwarded_proto + base_url.split("://", 1)[1])
        if base_url.startswith("http://"):
            candidates.add("https://" + base_url[len("http://"):])
        elif base_url.startswith("https://"):
            candidates.add("http://" + base_url[len("https://"):])
        if claims.get("aud") not in candidates:
            return False, (
                f"Token has wrong audience {claims.get('aud')}, "
                f"expected one of {sorted(candidates)}"
            )
        if claims.get("email") != PDF_JOB_TASK_SERVICE_ACCOUNT:
            return False, "Unexpected task service account."

    return True, None


def internal_pdf_task_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ok, error_message = _verify_internal_pdf_task_request()
        if not ok:
            logger.warning("Rejected internal PDF task request: %s", error_message)
            return jsonify({"error": error_message}), 403
        return f(*args, **kwargs)

    return decorated_function


def _get_pdf_job_doc(job_id: str):
    return db.collection("pdf_jobs").document(job_id).get()


def _get_pdf_job_or_404(job_id: str) -> dict | None:
    job_doc = _get_pdf_job_doc(job_id)
    if not job_doc.exists:
        return None
    payload = job_doc.to_dict() or {}
    payload["job_id"] = job_doc.id
    return payload


def _is_pdf_job_expired(job_data: dict | None) -> bool:
    if not job_data:
        return False
    expires_at = _firestore_timestamp_to_datetime(job_data.get("expires_at"))
    if not expires_at:
        return False
    return expires_at <= _now_utc()


def _delete_pdf_job_firestore(job_id: str):
    pages = list(db.collection("pdf_jobs").document(job_id).collection("pages").stream())
    if pages:
        batch = db.batch()
        for page_doc in pages:
            batch.delete(page_doc.reference)
        batch.commit()
    db.collection("pdf_jobs").document(job_id).delete()


def _purge_expired_pdf_job(job_id: str):
    _delete_pdf_job_prefix(job_id)
    _delete_pdf_job_firestore(job_id)


def _assert_pdf_job_owner_or_admin(job_data: dict, user_email: str) -> tuple[bool, str | None]:
    user_email = _normalize_email_identity(user_email)
    owner_email = _normalize_email_identity(job_data.get("user_email"))
    if user_email and owner_email and user_email == owner_email:
        return True, None
    if user_email and _is_admin_email(user_email):
        return True, None
    return False, "You do not have access to this PDF job."


def _build_pdf_job_analytics_context(job_data: dict) -> dict:
    analytics_ctx = dict(job_data.get("analytics_ctx") or {})
    analytics_ctx.setdefault("request_id", job_data.get("request_id"))
    analytics_ctx.setdefault("user_email", job_data.get("user_email"))
    analytics_ctx.setdefault("endpoint", "/process-pdf-async")
    analytics_ctx.setdefault("auth_method", job_data.get("auth_method"))
    analytics_ctx.setdefault("authenticated_via", job_data.get("authenticated_via"))
    analytics_ctx.setdefault("api_key_owner", job_data.get("api_key_owner"))
    analytics_ctx.setdefault("prompt", job_data.get("prompt"))
    analytics_ctx.setdefault("ocr_only", bool(job_data.get("ocr_only")))
    analytics_ctx.setdefault("notebook_mode", bool(job_data.get("notebook_mode")))
    analytics_ctx.setdefault("include_wfo", bool(job_data.get("include_wfo", True)))
    analytics_ctx.setdefault("include_cop90", bool(job_data.get("include_cop90", True)))
    analytics_ctx.setdefault("llm_model_name", job_data.get("llm_model_name"))
    return analytics_ctx


def _build_pdf_job_process_kwargs(job_data: dict) -> dict:
    return {
        "engine_options": list(job_data.get("engine_options") or []),
        "prompt": job_data.get("prompt"),
        "ocr_only": bool(job_data.get("ocr_only")),
        "include_wfo": bool(job_data.get("include_wfo", True)),
        "include_cop90": bool(job_data.get("include_cop90", True)),
        "llm_model_name": job_data.get("llm_model_name"),
        "url_source": "",
        "notebook_mode": bool(job_data.get("notebook_mode")),
        "skip_label_collage": bool(job_data.get("skip_label_collage")),
        "user_api_key": None,
        "user_vertex_project": job_data.get("user_vertex_project"),
        "user_vertex_region": job_data.get("user_vertex_region"),
    }


def _create_pdf_job_xlsx_bytes(page_outputs: list[dict]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "results"

    all_fields = []
    seen_fields = set()
    for page_output in page_outputs:
        formatted_json = page_output.get("formatted_json")
        if isinstance(formatted_json, dict):
            for key in formatted_json.keys():
                if key not in seen_fields:
                    seen_fields.add(key)
                    all_fields.append(key)

    headers = ["page_index", "filename"] + all_fields
    sheet.append(headers)

    for page_output in page_outputs:
        formatted_json = page_output.get("formatted_json") if isinstance(page_output.get("formatted_json"), dict) else {}
        row = [
            _coerce_int(page_output.get("page_index")),
            page_output.get("filename") or "",
        ]
        for field_name in all_fields:
            value = formatted_json.get(field_name, "")
            row.append("" if value is None else str(value))
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _load_pdf_job_pages(job_id: str) -> list[dict]:
    pages = []
    for page_doc in db.collection("pdf_jobs").document(job_id).collection("pages").stream():
        payload = page_doc.to_dict() or {}
        payload["page_id"] = page_doc.id
        pages.append(payload)
    return sorted(pages, key=lambda item: _coerce_int(item.get("page_index")))


def _mark_pdf_job_failed(job_id: str, error_message: str, *, phase: str) -> dict | None:
    job_ref = db.collection("pdf_jobs").document(job_id)
    job_ref.set(
        {
            "status": "failed",
            "phase": phase,
            "error_summary": _sanitize_error_message(error_message),
            "updated_at": firestore.SERVER_TIMESTAMP,
            "finished_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return _get_pdf_job_or_404(job_id)


def _maybe_enqueue_pdf_finalize(job_data: dict) -> bool:
    job_id = job_data["job_id"]
    job_ref = db.collection("pdf_jobs").document(job_id)

    @_gc_firestore.transactional
    def _txn(transaction):
        current_doc = job_ref.get(transaction=transaction)
        if not current_doc.exists:
            return False
        current_data = current_doc.to_dict() or {}
        if current_data.get("finalize_enqueued_at"):
            return False
        if current_data.get("status") not in {"running", "finalizing"}:
            return False
        page_count = _coerce_int(current_data.get("page_count"))
        terminal_count = _coerce_int(current_data.get("successful_pages")) + _coerce_int(current_data.get("failed_pages"))
        if page_count <= 0 or terminal_count < page_count:
            return False
        transaction.update(
            job_ref,
            {
                "status": "finalizing",
                "phase": "finalizing",
                "updated_at": firestore.SERVER_TIMESTAMP,
                "finalize_enqueued_at": firestore.SERVER_TIMESTAMP,
            },
        )
        return True

    should_enqueue = _txn(db.transaction())
    if should_enqueue:
        refreshed = _get_pdf_job_or_404(job_id)
        if refreshed:
            _enqueue_pdf_finalize_task(refreshed)
    return should_enqueue


def _refresh_pdf_job_counters(job_id: str) -> dict | None:
    pages = _load_pdf_job_pages(job_id)
    page_count = len(pages)
    successful_pages = sum(1 for page in pages if page.get("status") == "completed")
    failed_pages = sum(1 for page in pages if page.get("status") == "failed")
    completed_pages = successful_pages + failed_pages
    job_ref = db.collection("pdf_jobs").document(job_id)
    status = "running"
    phase = "processing_pages"
    if page_count and completed_pages >= page_count:
        status = "finalizing"
        phase = "finalizing"
    job_ref.set(
        {
            "page_count": page_count,
            "successful_pages": successful_pages,
            "failed_pages": failed_pages,
            "completed_pages": completed_pages,
            "status": status,
            "phase": phase,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    job_data = _get_pdf_job_or_404(job_id)
    if job_data:
        _maybe_enqueue_pdf_finalize(job_data)
    return job_data


def _reserve_pdf_page_pro_quota_if_needed(job_data: dict) -> tuple[bool, bool, int, int]:
    user_email = _normalize_email_identity(job_data.get("user_email"))
    if not user_email:
        return True, False, 0, GEMINI_PRO_DEFAULT_LIMIT
    user_pays = bool(job_data.get("user_vertex_project"))
    if user_pays or not is_pro_request(job_data.get("engine_options"), job_data.get("llm_model_name")):
        return True, False, 0, GEMINI_PRO_DEFAULT_LIMIT
    allowed, count, limit = check_and_reserve_gemini_pro_quota(user_email)
    return allowed, True, count, limit

# Authentication middleware function
def authenticate_request(request):
    """Verify Firebase ID token from various sources."""
    id_token = _get_id_token_from_request(request)
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
        api_key = _get_api_key_from_request(request)
        if api_key:
            # Get the API key document
            api_key_doc = db.collection('api_keys').document(api_key).get()
            
            if api_key_doc.exists:
                key_data = api_key_doc.to_dict()
                user_email = key_data.get('owner', 'unknown')
                logger.debug(f"API key auth: {user_email}")
                return user_email
        
        id_token = _get_id_token_from_request(request)
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


def _is_admin_email(user_email: str) -> bool:
    user_email = _normalize_email_identity(user_email)
    if not user_email:
        return False
    admin_doc = db.collection("admins").document(user_email).get()
    return admin_doc.exists


def _get_api_key_access_state(user_email: str) -> dict:
    user_email = _normalize_email_identity(user_email)
    if not user_email:
        return {
            "allowed": False,
            "is_admin": False,
            "status_code": 401,
            "error": "User not properly authenticated",
            "code": "not_authenticated",
        }

    if _is_admin_email(user_email):
        return {
            "allowed": True,
            "is_admin": True,
            "is_approved": True,
            "has_api_key_access": True,
        }

    app_doc = db.collection("user_applications").document(user_email).get()
    if not app_doc.exists:
        return {
            "allowed": False,
            "is_admin": False,
            "status_code": 404,
            "error": "User application not found",
            "code": "application_not_found",
        }

    app_data = app_doc.to_dict() or {}
    is_approved = app_data.get("status") == "approved"
    has_api_key_access = bool(app_data.get("api_key_access", False))
    if not is_approved:
        return {
            "allowed": False,
            "is_admin": False,
            "is_approved": False,
            "has_api_key_access": has_api_key_access,
            "status_code": 403,
            "error": "Your account is not approved yet",
            "code": "not_approved",
        }

    if not has_api_key_access:
        return {
            "allowed": False,
            "is_admin": False,
            "is_approved": True,
            "has_api_key_access": False,
            "status_code": 403,
            "error": "You do not have permission to create API keys. Please contact an administrator.",
            "code": "no_api_key_permission",
        }

    return {
        "allowed": True,
        "is_admin": False,
        "is_approved": True,
        "has_api_key_access": True,
    }


def _claim_or_reactivate_vertex_project(
    *,
    project_id: str,
    owner_email: str,
    actor_email: str,
    nickname: str = "",
) -> tuple[dict, int]:
    owner_email = _normalize_email_identity(owner_email)
    actor_email = _normalize_email_identity(actor_email)
    project_ref = db.collection("vertex_projects").document(project_id)
    create_payload = {
        "project_id": project_id,
        "owner_email": owner_email,
        "nickname": nickname,
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_by_actor": actor_email,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "revoked_at": None,
        "revoked_by": None,
    }

    try:
        project_ref.create(create_payload)
        project_doc = project_ref.get()
        return {
            "status": "success",
            "message": f"Linked Vertex project '{project_id}'.",
            "project": _serialize_vertex_project(project_doc),
        }, 201
    except google_exceptions.AlreadyExists:
        project_doc = project_ref.get()

    if not project_doc.exists:
        raise RuntimeError(f"Vertex project '{project_id}' exists but could not be fetched after create conflict.")

    project_data = project_doc.to_dict() or {}
    if project_data.get("owner_email") != owner_email:
        return {
            "error": (
                f"Vertex project '{project_id}' is already linked to another "
                f"VoucherVisionGO account."
            )
        }, 409

    update_payload = {
        "nickname": nickname,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }

    if bool(project_data.get("active")):
        project_ref.update(update_payload)
        project_doc = project_ref.get()
        return {
            "status": "success",
            "message": f"Vertex project '{project_id}' is already linked to your account.",
            "project": _serialize_vertex_project(project_doc),
        }, 200

    update_payload.update({
        "active": True,
        "revoked_at": None,
        "revoked_by": None,
    })
    project_ref.update(update_payload)
    project_doc = project_ref.get()
    return {
        "status": "success",
        "message": f"Reactivated Vertex project '{project_id}'.",
        "project": _serialize_vertex_project(project_doc),
    }, 200

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
        api_key = _get_api_key_from_request(request)
        
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
    
    def perform_ocr(self, file_path, engine_options, ocr_prompt_option, user_api_key=None,
                    user_vertex_project=None, user_vertex_region=None):
        """Perform OCR on the provided image"""
        ocr_packet = {}
        ocr_all = ""
        ocr_tokens_total = 0

        for i, ocr_opt in enumerate(engine_options):
            ocr_packet[ocr_opt] = {}
            self._log(f"ocr_opt {ocr_opt}", "info")

            if user_vertex_project:
                # Per-request throwaway engine billed to the user's GCP project
                OCR_Engine = OCRGeminiProVision(
                    None,
                    model_name=ocr_opt,
                    max_output_tokens=32768,
                    temperature=1.0,
                    top_p=0.95,
                    seed=123456,
                    do_resize_img=False,
                    vertex_project=user_vertex_project,
                    vertex_region=user_vertex_region,
                )
            elif user_api_key:
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
    
    def get_thread_local_vv(self, prompt, llm_model_name, user_api_key=None,
                            user_vertex_project=None, user_vertex_region=None):
        """Get or create a thread-local VoucherVision instance with the specified prompt"""
        # Cache key includes every input that changes the LLM handler's identity.
        # Keying on these (rather than just "did this request bring creds")
        # prevents a previously per-user handler from being silently reused on a
        # later no-credentials request.
        incoming_key = (
            user_api_key,
            user_vertex_project,
            user_vertex_region,
            prompt,
            llm_model_name,
        )
        needs_new = (
            not hasattr(self.thread_local, 'vv')
            or getattr(self.thread_local, 'cache_key', None) != incoming_key
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

            self.thread_local.llm_model = GoogleGeminiHandler(
                self.cfg, self.logger, llm_model_name,
                self.thread_local.vv.JSON_dict_structure,
                config_vals_for_permutation=None,
                exit_early_for_JSON=True,
                api_key=user_api_key,  # None = use env, key = use theirs
                vertex_project=user_vertex_project,
                vertex_region=user_vertex_region,
            )
            self.thread_local.cache_key = incoming_key
            self._log(f"Created new thread-local VV instance with prompt: {prompt}", "info")

        return self.thread_local.vv, self.thread_local.llm_model
    
    def process_voucher_vision(self, ocr_text, prompt, llm_model_name, LLM_name_cost, user_api_key=None,
                               user_vertex_project=None, user_vertex_region=None):
        """Process the OCR text with VoucherVision using a thread-local instance"""
        # Get thread-local VoucherVision instance with the correct prompt
        vv, llm_model = self.get_thread_local_vv(
            prompt, llm_model_name,
            user_api_key=user_api_key,
            user_vertex_project=user_vertex_project,
            user_vertex_region=user_vertex_region,
        )

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

        # Sum estimated cost across all successful pages so the route handler
        # can persist a single total for the request (not just the last page).
        pdf_cost_total_usd = 0.0
        for r in page_results:
            try:
                pdf_cost_total_usd += float(r.get("total_request_cost_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass

        return OrderedDict([
            ('source_pdf', pdf_filename),
            ('page_count', len(page_files)),
            ('pages', page_results),
            ('total_request_cost_usd', pdf_cost_total_usd),
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
                              user_api_key=None,
                              user_vertex_project=None,
                              user_vertex_region=None):
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
                        engine_options = ["gemini-2.5-flash"]
                    else:
                        engine_options = ["gemini-2.5-flash"]

                if ocr_prompt_option is None:
                    if notebook_mode:
                        ocr_prompt_option = "verbatim_notebook"
                    elif ocr_only:
                        ocr_prompt_option = "verbatim_with_annotations"
                    else:
                        ocr_prompt_option = None

                # Simpler alternative approach
                if llm_model_name is None:
                    llm_model_name = "gemini-2.5-flash"

                # Direct mapping from API model names to cost constants
                api_to_cost_mapping = {
                    "gemini-2.0-flash": "GEMINI_2_0_FLASH",
                    "gemini-1.5-flash": "GEMINI_1_5_FLASH",
                    "gemini-1.5-pro": "GEMINI_1_5_PRO",
                    "gemini-2.5-flash": "GEMINI_2_5_FLASH",
                    "gemini-2.5-pro": "GEMINI_2_5_PRO",
                    "gemini-3-pro-preview": "GEMINI_3_PRO",
                    "gemini-3-flash-preview": "GEMINI_3_FLASH",
                    "gemini-3-flash": "GEMINI_3_FLASH",

                    "gemini-3.1-pro-preview": "GEMINI_3_1_PRO",
                    "gemini-3.1-pro": "GEMINI_3_1_PRO",
                    
                    "gemini-3.1-flash-lite-preview": "GEMINI_3_1_FLASH_LITE",
                    "gemini-3.1-flash-lite": "GEMINI_3_1_FLASH_LITE",
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
                                                                   user_api_key=user_api_key,
                                                                   user_vertex_project=user_vertex_project,
                                                                   user_vertex_region=user_vertex_region)

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
                                                                                                       user_api_key=user_api_key,
                                                                                                       user_vertex_project=user_vertex_project,
                                                                                                       user_vertex_region=user_vertex_region)

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

                # Aggregate the per-request estimated cost so the route handler
                # can persist it on the user's usage doc. OCR costs come from
                # each engine in ocr_info; LLM cost comes from parsing_info.
                # Token-derived estimate, not authoritative billing.
                try:
                    ocr_cost_sum = 0.0
                    for v in (results.get("ocr_info") or {}).values():
                        if isinstance(v, dict):
                            ocr_cost_sum += float(v.get("total_cost", 0.0) or 0.0)
                    parsing = results.get("parsing_info") or {}
                    parsing_cost = float(parsing.get("cost_in", 0.0) or 0.0) + float(parsing.get("cost_out", 0.0) or 0.0)
                    results["total_request_cost_usd"] = ocr_cost_sum + parsing_cost
                except Exception as cost_err:
                    self._log(f"Could not compute total_request_cost_usd: {cost_err}", "warning")
                    results["total_request_cost_usd"] = 0.0

                self._log(f"Processing completed successfully", "info")
                return results, 200
            
            except Exception as e:
                self._log(f"Error processing request: {e}", "error")
                import traceback
                self._log(f"Traceback: {traceback.format_exc()}", "error")
                if user_vertex_project and _is_vertex_permission_error(e):
                    return {'error': _vertex_permission_error_message(user_vertex_project)}, 403
                if user_vertex_project and _is_vertex_model_not_found_error(e):
                    return {
                        'error': _vertex_model_not_found_message(
                            user_vertex_project, user_vertex_region, llm_model_name
                        )
                    }, 404
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
@authenticated_route
def auth_check():
    """Simple endpoint to verify authentication status"""
    # If we get here, authentication was successful
    return jsonify({
        'status': 'authenticated',
        'message': 'Your authentication token is valid.'
    }), 200
    
@app.route('/process', methods=['POST', 'OPTIONS'])
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
    payment_auth = get_payment_auth_context(request)
    user_gemini_key = payment_auth["gemini_api_key"]
    user_vertex_project = payment_auth["vertex_project"]
    user_vertex_region = payment_auth["vertex_region"]

    err, err_status = _validate_vertex_params(user_gemini_key, user_vertex_project, user_vertex_region)
    if err:
        resp = make_response(jsonify({'error': err}), err_status)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp
    if user_vertex_project:
        user_vertex_project, project_error = _validate_vertex_project_id(user_vertex_project)
        if project_error:
            resp = make_response(jsonify({'error': project_error}), 400)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp
        binding_error = _validate_vertex_project_binding(user_vertex_project, user_email)
        if binding_error:
            resp = make_response(jsonify({'error': binding_error}), 403)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp

    auth_method = payment_auth["auth_method"]
    logger.info(
        "Resolved payment auth for /process user=%s method=%s vertex=%s gemini_key=%s",
        user_email,
        auth_method,
        bool(user_vertex_project),
        bool(user_gemini_key),
    )
    request_id = str(uuid.uuid4())
    analytics_ctx = build_request_analytics_context(
        request,
        user_email=user_email,
        endpoint="/process",
        auth_ctx=payment_auth,
        request_id=request_id,
        prompt=prompt,
        ocr_only=ocr_only,
        notebook_mode=notebook_mode,
        include_wfo=include_wfo,
        include_cop90=include_cop90,
        llm_model_name=llm_model_name,
    )

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
        user_vertex_project=user_vertex_project,
        user_vertex_region=user_vertex_region,
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

        if status_code == 200:
            page_events = []
            page_count = _coerce_int(results.get('page_count'))
            for idx, page_result in enumerate(results.get('pages', []), start=1):
                page_status_code = _coerce_int(page_result.get('status_code'), 200)
                page_events.append(
                    build_usage_event(
                        analytics_ctx=analytics_ctx,
                        result=page_result,
                        status_code=page_status_code,
                        source_type="pdf_page",
                        filename=page_result.get("filename"),
                        source_pdf=results.get("source_pdf"),
                        page_index=idx,
                        page_count=page_count,
                        include_in_rollup="impact" in page_result,
                    )
                )
            if page_events:
                try:
                    persist_usage_events_and_rollups(page_events, route_label="/process:pdf")
                except Exception:
                    logger.exception(
                        "usage_events write failed route=/process request_id=%s; skipped rollup mutation",
                        request_id,
                    )

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

        # ── Gemini Pro rate-limit gate (skip if user is paying via own API key OR Vertex project) ──
        pro_quota_reserved = False
        user_pays = bool(user_gemini_key) or bool(user_vertex_project)
        if is_pro_request(engine_options, llm_model_name) and not user_pays:
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

        event = build_usage_event(
            analytics_ctx=analytics_ctx,
            result=results,
            status_code=status_code,
            source_type="upload",
            filename=getattr(file, "filename", None),
            include_in_rollup=True,
        )

        if status_code == 200:
            try:
                persist_usage_events_and_rollups([event], route_label="/process:upload")
            except Exception:
                logger.exception(
                    "usage_events write failed route=/process request_id=%s; skipped rollup mutation",
                    request_id,
                )
            # Advisory email: nudge users toward flash-lite / own API key (max 1/day)
            if pro_quota_reserved:
                _, count, limit = check_gemini_pro_rate_limit(user_email)
                _send_pro_migration_advisory(user_email, count, limit)
        else:
            # Release the reserved pro quota on failure
            if pro_quota_reserved:
                release_gemini_pro_quota(user_email)
            try:
                persist_usage_events_and_rollups([event], route_label="/process:upload")
            except Exception:
                logger.exception(
                    "usage_events write failed route=/process request_id=%s; skipped rollup mutation",
                    request_id,
                )

    # Always return JSON
    response = make_response(json.dumps(results, cls=OrderedJsonEncoder), status_code)
    response.headers['Content-Type'] = 'application/json'
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/process-url', methods=['POST', 'OPTIONS'])
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
        payment_auth = get_payment_auth_context(request)
        user_gemini_key = payment_auth["gemini_api_key"]
        user_vertex_project = payment_auth["vertex_project"]
        user_vertex_region = payment_auth["vertex_region"]

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
        payment_auth = get_payment_auth_context(request)
        user_gemini_key = payment_auth["gemini_api_key"]
        user_vertex_project = payment_auth["vertex_project"]
        user_vertex_region = payment_auth["vertex_region"]

    err, err_status = _validate_vertex_params(user_gemini_key, user_vertex_project, user_vertex_region)
    if err:
        resp = make_response(jsonify({'error': err}), err_status)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp
    if user_vertex_project:
        user_vertex_project, project_error = _validate_vertex_project_id(user_vertex_project)
        if project_error:
            resp = make_response(jsonify({'error': project_error}), 400)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp
        binding_error = _validate_vertex_project_binding(user_vertex_project, user_email)
        if binding_error:
            resp = make_response(jsonify({'error': binding_error}), 403)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp

    auth_method = payment_auth["auth_method"]
    logger.info(
        "Resolved payment auth for /process-url user=%s method=%s vertex=%s gemini_key=%s",
        user_email,
        auth_method,
        bool(user_vertex_project),
        bool(user_gemini_key),
    )
    request_id = str(uuid.uuid4())
    analytics_ctx = build_request_analytics_context(
        request,
        user_email=user_email,
        endpoint="/process-url",
        auth_ctx=payment_auth,
        request_id=request_id,
        prompt=prompt,
        ocr_only=ocr_only,
        notebook_mode=notebook_mode,
        include_wfo=include_wfo,
        include_cop90=include_cop90,
        llm_model_name=llm_model_name,
    )

    # ── Gemini Pro rate-limit gate (skip if user is paying via own API key OR Vertex project) ──
    pro_quota_reserved = False
    user_pays = bool(user_gemini_key) or bool(user_vertex_project)
    if is_pro_request(engine_options, llm_model_name) and not user_pays:
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
                filename = filename_from_url
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
        failure_event = build_usage_event(
            analytics_ctx=analytics_ctx,
            result=error_response_data,
            status_code=200,
            source_type="url",
            filename=extract_filename_from_url(image_url),
            url_source=image_url,
            success=False,
            include_in_rollup=False,
            error_type="fetch_failure",
            error_message_safe=str(last_exception),
        )
        try:
            record_usage_event(failure_event)
        except Exception:
            logger.exception(
                "usage_events write failed route=/process-url request_id=%s; skipped rollup mutation",
                request_id,
            )
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
            user_api_key=user_gemini_key,
            user_vertex_project=user_vertex_project,
            user_vertex_region=user_vertex_region,
        )

        event = build_usage_event(
            analytics_ctx=analytics_ctx,
            result=results,
            status_code=status_code,
            source_type="url",
            filename=getattr(file_obj, "filename", None) or filename,
            url_source=image_url,
            include_in_rollup=True,
        )

        if status_code == 200:
            try:
                persist_usage_events_and_rollups([event], route_label="/process-url")
            except Exception:
                logger.exception(
                    "usage_events write failed route=/process-url request_id=%s; skipped rollup mutation",
                    request_id,
                )
            # Advisory email: nudge users toward flash-lite / own API key (max 1/day)
            if pro_quota_reserved:
                _, count, limit = check_gemini_pro_rate_limit(user_email)
                _send_pro_migration_advisory(user_email, count, limit)
        else:
            # Release the reserved pro quota on failure
            if pro_quota_reserved:
                release_gemini_pro_quota(user_email)
            try:
                persist_usage_events_and_rollups([event], route_label="/process-url")
            except Exception:
                logger.exception(
                    "usage_events write failed route=/process-url request_id=%s; skipped rollup mutation",
                    request_id,
                )

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
    

@app.route('/process-pdf-async', methods=['POST', 'OPTIONS'])
@authenticated_route
def process_pdf_async():
    user_email = _normalize_email_identity(get_user_email_from_request(request))
    if not user_email or user_email == 'unknown':
        resp = make_response(jsonify({'error': 'Unable to resolve the authenticated user.'}), 401)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    if 'file' not in request.files:
        resp = make_response(jsonify({'error': 'No PDF file provided.'}), 400)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    file = request.files['file']
    filename = secure_filename(file.filename or "")
    if not filename.lower().endswith('.pdf'):
        resp = make_response(jsonify({'error': 'Only PDF uploads are supported for async PDF jobs.'}), 400)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    engine_options = request.form.getlist('engines') if 'engines' in request.form else None
    prompt = request.form.get('prompt') if 'prompt' in request.form else None
    ocr_only = request.form.get('ocr_only', 'false').lower() == 'true'
    notebook_mode = request.form.get('notebook_mode', 'false').lower() == 'true'
    skip_label_collage = request.form.get('skip_label_collage', 'false').lower() == 'true'
    include_wfo = request.form.get('include_wfo', 'true').lower() == 'true'
    include_cop90 = request.form.get('include_cop90', 'true').lower() == 'true'
    llm_model_name = request.form.get('llm_model') if 'llm_model' in request.form else None
    payment_auth = get_payment_auth_context(request)
    user_gemini_key = payment_auth["gemini_api_key"]
    user_vertex_project = payment_auth["vertex_project"]
    user_vertex_region = payment_auth["vertex_region"]

    err, err_status = _validate_vertex_params(user_gemini_key, user_vertex_project, user_vertex_region)
    if err:
        resp = make_response(jsonify({'error': err}), err_status)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    if user_gemini_key:
        resp = make_response(
            jsonify({'error': 'Async PDF jobs do not support gemini_api_key yet. Use server billing or a linked Vertex project.'}),
            400,
        )
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    if user_vertex_project:
        user_vertex_project, project_error = _validate_vertex_project_id(user_vertex_project)
        if project_error:
            resp = make_response(jsonify({'error': project_error}), 400)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp
        binding_error = _validate_vertex_project_binding(user_vertex_project, user_email)
        if binding_error:
            resp = make_response(jsonify({'error': binding_error}), 403)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp

    if payment_auth["auth_method"] not in PDF_JOB_ALLOWED_SOURCE_TYPES:
        resp = make_response(
            jsonify({'error': f"Async PDF jobs support only {sorted(PDF_JOB_ALLOWED_SOURCE_TYPES)} billing modes."}),
            400,
        )
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    try:
        pdf_bytes = file.read()
    except Exception as e:
        logger.exception("Unable to read uploaded PDF for async processing")
        resp = make_response(jsonify({'error': 'Unable to read the uploaded PDF.'}), 400)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    if not pdf_bytes:
        resp = make_response(jsonify({'error': 'The uploaded PDF is empty.'}), 400)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    request_id = str(uuid.uuid4())
    analytics_ctx = build_request_analytics_context(
        request,
        user_email=user_email,
        endpoint="/process-pdf-async",
        auth_ctx=payment_auth,
        request_id=request_id,
        prompt=prompt,
        ocr_only=ocr_only,
        notebook_mode=notebook_mode,
        include_wfo=include_wfo,
        include_cop90=include_cop90,
        llm_model_name=llm_model_name,
    )

    job_id = str(uuid.uuid4())
    expires_at = _pdf_job_expiration_time()
    public_base_url = _resolve_pdf_job_public_base_url()
    task_base_url = _resolve_pdf_job_task_base_url()
    original_blob_path = _pdf_job_blob_path(job_id, "original", filename)

    try:
        _upload_pdf_job_bytes(original_blob_path, pdf_bytes, content_type="application/pdf")
    except Exception as e:
        logger.exception("Failed to upload PDF job source %s", job_id)
        resp = make_response(jsonify({'error': 'Failed to store PDF for async processing.'}), 500)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    job_payload = {
        "job_id": job_id,
        "request_id": request_id,
        "user_email": user_email,
        "status": "queued",
        "phase": "queued",
        "source_pdf_filename": filename,
        "original_pdf_blob_path": original_blob_path,
        "page_count": 0,
        "completed_pages": 0,
        "successful_pages": 0,
        "failed_pages": 0,
        "engine_options": list(engine_options or []),
        "prompt": prompt,
        "ocr_only": bool(ocr_only),
        "notebook_mode": bool(notebook_mode),
        "skip_label_collage": bool(skip_label_collage),
        "include_wfo": bool(include_wfo),
        "include_cop90": bool(include_cop90),
        "llm_model_name": llm_model_name,
        "auth_method": payment_auth["auth_method"],
        "user_vertex_project": user_vertex_project,
        "user_vertex_region": user_vertex_region,
        "authenticated_via": analytics_ctx.get("authenticated_via"),
        "api_key_owner": analytics_ctx.get("api_key_owner"),
        "analytics_ctx": analytics_ctx,
        "download_token": uuid.uuid4().hex,
        "public_base_url": public_base_url,
        "task_base_url": task_base_url,
        "bundle_blob_path": None,
        "xlsx_blob_path": None,
        "manifest_blob_path": None,
        "email_status": "pending",
        "error_summary": None,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "started_at": None,
        "finished_at": None,
        "expires_at": expires_at,
    }

    db.collection("pdf_jobs").document(job_id).set(job_payload)

    try:
        _enqueue_pdf_split_task(job_payload)
    except Exception as e:
        logger.exception("Failed to enqueue split task for PDF job %s", job_id)
        _mark_pdf_job_failed(job_id, f"Queue submission failed: {e}", phase="queue_error")
        resp = make_response(jsonify({'error': 'Unable to queue PDF job.'}), 500)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    response_payload = _serialize_pdf_job(_get_pdf_job_doc(job_id))
    response_payload["status_url"] = f"{public_base_url}/pdf-jobs/{job_id}" if public_base_url else f"/pdf-jobs/{job_id}"
    resp = make_response(json.dumps(response_payload, cls=OrderedJsonEncoder), 202)
    resp.headers['Content-Type'] = 'application/json'
    resp.headers.add('Access-Control-Allow-Origin', '*')
    return resp


@app.route('/pdf-jobs', methods=['GET', 'OPTIONS'])
@authenticated_route
def list_pdf_jobs():
    user_email = _normalize_email_identity(get_user_email_from_request(request))
    limit = min(max(_coerce_int(request.args.get("limit"), 10), 1), PDF_JOB_MAX_LIST)
    jobs = []
    expired_job_ids = []

    for job_doc in db.collection("pdf_jobs").stream():
        payload = job_doc.to_dict() or {}
        payload["job_id"] = job_doc.id
        if _normalize_email_identity(payload.get("user_email")) != user_email and not _is_admin_email(user_email):
            continue
        if _is_pdf_job_expired(payload):
            expired_job_ids.append(job_doc.id)
            continue
        jobs.append(payload)

    for job_id in expired_job_ids:
        _purge_expired_pdf_job(job_id)

    jobs.sort(
        key=lambda item: _firestore_timestamp_to_datetime(item.get("created_at")) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=True,
    )
    serialized_jobs = []
    for job in jobs[:limit]:
        serialized = _serialize_pdf_job(job)
        serialized["download_url"] = _build_pdf_job_download_url(job)
        serialized_jobs.append(serialized)
    payload = {"jobs": serialized_jobs}
    resp = make_response(json.dumps(payload, cls=OrderedJsonEncoder), 200)
    resp.headers['Content-Type'] = 'application/json'
    resp.headers.add('Access-Control-Allow-Origin', '*')
    return resp


@app.route('/pdf-jobs/<job_id>', methods=['GET', 'OPTIONS'])
@authenticated_route
def get_pdf_job(job_id):
    user_email = _normalize_email_identity(get_user_email_from_request(request))
    job_data = _get_pdf_job_or_404(job_id)
    if not job_data:
        resp = make_response(jsonify({'error': 'PDF job not found.'}), 404)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp
    if _is_pdf_job_expired(job_data):
        _purge_expired_pdf_job(job_id)
        resp = make_response(jsonify({'error': 'PDF job has expired.'}), 410)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    allowed, error_message = _assert_pdf_job_owner_or_admin(job_data, user_email)
    if not allowed:
        resp = make_response(jsonify({'error': error_message}), 403)
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp

    pages = [_serialize_pdf_job_page(page) for page in _load_pdf_job_pages(job_id)]
    payload = {
        "job": {
            **_serialize_pdf_job(job_data),
            "download_url": _build_pdf_job_download_url(job_data),
        },
        "pages": pages,
        "download_url": _build_pdf_job_download_url(job_data),
    }
    resp = make_response(json.dumps(payload, cls=OrderedJsonEncoder), 200)
    resp.headers['Content-Type'] = 'application/json'
    resp.headers.add('Access-Control-Allow-Origin', '*')
    return resp


@app.route('/pdf-jobs/<job_id>/download', methods=['GET'])
def download_pdf_job_bundle(job_id):
    job_data = _get_pdf_job_or_404(job_id)
    if not job_data:
        return jsonify({'error': 'PDF job not found.'}), 404
    if _is_pdf_job_expired(job_data):
        _purge_expired_pdf_job(job_id)
        return jsonify({'error': 'PDF job has expired.'}), 410

    token = request.args.get("token")
    token_authorized = bool(token and token == job_data.get("download_token"))

    user_email = _normalize_email_identity(get_user_email_from_request(request))
    owner_authorized = False
    if user_email and user_email != 'unknown':
        owner_authorized, _ = _assert_pdf_job_owner_or_admin(job_data, user_email)

    if not token_authorized and not owner_authorized:
        return jsonify({'error': 'You do not have access to this PDF job download.'}), 403

    bundle_blob_path = job_data.get("bundle_blob_path")
    if not bundle_blob_path:
        return jsonify({'error': 'The ZIP bundle is not ready yet.'}), 409

    try:
        bundle_bytes = _download_pdf_job_bytes(bundle_blob_path)
    except FileNotFoundError:
        return jsonify({'error': 'The ZIP bundle is no longer available.'}), 410
    except Exception as e:
        logger.exception("Failed to download PDF job bundle %s", job_id)
        return jsonify({'error': 'Unable to download ZIP bundle.'}), 500

    basename = Path(job_data.get("source_pdf_filename") or f"{job_id}.pdf").stem
    download_name = f"{basename}_VoucherVisionGO.zip"
    response = make_response(bundle_bytes)
    response.headers['Content-Type'] = 'application/zip'
    response.headers['Content-Disposition'] = f'attachment; filename="{download_name}"'
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/internal/pdf-jobs/<job_id>/split', methods=['POST'])
@internal_pdf_task_route
def internal_split_pdf_job(job_id):
    job_data = _get_pdf_job_or_404(job_id)
    if not job_data:
        return jsonify({'error': 'PDF job not found.'}), 404

    try:
        db.collection("pdf_jobs").document(job_id).set(
            {
                "status": "running",
                "phase": "splitting",
                "started_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "error_summary": None,
            },
            merge=True,
        )
        pdf_bytes = _download_pdf_job_bytes(job_data["original_pdf_blob_path"])
        page_files = convert_pdf_to_page_images(pdf_bytes, job_data["source_pdf_filename"])

        if len(page_files) > PDF_JOB_MAX_PAGES:
            _mark_pdf_job_failed(
                job_id,
                f"PDF has {len(page_files)} pages, exceeding the limit of {PDF_JOB_MAX_PAGES}.",
                phase="splitting",
            )
            return jsonify({'error': 'PDF exceeds the maximum supported page count.'}), 400

        expires_at = job_data.get("expires_at") or _pdf_job_expiration_time()
        batch = db.batch()
        for page_index, page_file in enumerate(page_files, start=1):
            page_file.stream.seek(0)
            page_bytes = page_file.read()
            page_blob_path = _pdf_job_blob_path(job_id, "pages", page_file.filename)
            _upload_pdf_job_bytes(page_blob_path, page_bytes, content_type="image/jpeg")
            page_ref = db.collection("pdf_jobs").document(job_id).collection("pages").document(f"{page_index:04d}")
            batch.set(
                page_ref,
                {
                    "page_index": page_index,
                    "status": "queued",
                    "attempt_count": 0,
                    "filename": page_file.filename,
                    "page_image_blob_path": page_blob_path,
                    "result_blob_path": None,
                    "status_code": 0,
                    "error_message": None,
                    "total_request_cost_usd": 0.0,
                    "total_tokens_all": 0,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "expires_at": expires_at,
                },
            )
        batch.commit()

        db.collection("pdf_jobs").document(job_id).set(
            {
                "page_count": len(page_files),
                "status": "running",
                "phase": "processing_pages",
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        refreshed = _get_pdf_job_or_404(job_id)
        if refreshed:
            for page_index in range(1, len(page_files) + 1):
                _enqueue_pdf_page_task(refreshed, page_index)

        return jsonify({'ok': True, 'page_count': len(page_files)}), 200
    except Exception as e:
        logger.exception("Failed to split async PDF job %s", job_id)
        _mark_pdf_job_failed(job_id, str(e), phase="splitting")
        return jsonify({'error': 'Failed to split the PDF job.'}), 500


@app.route('/internal/pdf-jobs/<job_id>/pages/<int:page_index>/process', methods=['POST'])
@internal_pdf_task_route
def internal_process_pdf_job_page(job_id, page_index):
    job_data = _get_pdf_job_or_404(job_id)
    if not job_data:
        return jsonify({'error': 'PDF job not found.'}), 404

    page_ref = db.collection("pdf_jobs").document(job_id).collection("pages").document(f"{page_index:04d}")
    page_doc = page_ref.get()
    if not page_doc.exists:
        return jsonify({'error': 'PDF job page not found.'}), 404
    page_data = page_doc.to_dict() or {}

    page_ref.set(
        {
            "status": "running",
            "attempt_count": firestore.Increment(1),
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    quota_reserved = False
    try:
        allowed, quota_reserved, count, limit = _reserve_pdf_page_pro_quota_if_needed(job_data)
        if not allowed:
            raise RuntimeError(
                f"Gemini Pro rate limit exceeded for {job_data.get('user_email')}: {count}/{limit}."
            )

        page_bytes = _download_pdf_job_bytes(page_data["page_image_blob_path"])
        file_obj = FileStorage(
            stream=BytesIO(page_bytes),
            filename=page_data.get("filename") or f"page_{page_index:04d}.jpg",
            content_type="image/jpeg",
        )
        results, status_code = app.config['processor'].process_image_request(
            file=file_obj,
            **_build_pdf_job_process_kwargs(job_data),
        )

        result_blob_path = _pdf_job_blob_path(job_id, "results", f"page_{page_index:04d}.json")
        _upload_pdf_job_json(result_blob_path, results)

        event = build_usage_event(
            analytics_ctx=_build_pdf_job_analytics_context(job_data),
            result=results,
            status_code=status_code,
            source_type="pdf_page",
            filename=page_data.get("filename"),
            source_pdf=job_data.get("source_pdf_filename"),
            page_index=page_index,
            page_count=_coerce_int(job_data.get("page_count")),
            include_in_rollup="impact" in (results or {}),
        )

        try:
            persist_usage_events_and_rollups([event], route_label="/process-pdf-async:page")
        except Exception:
            logger.exception(
                "usage_events write failed route=/process-pdf-async request_id=%s page=%s",
                job_data.get("request_id"),
                page_index,
            )

        page_status = "completed" if event.get("success") else "failed"
        if page_status != "completed" and quota_reserved:
            release_gemini_pro_quota(job_data.get("user_email"))
            quota_reserved = False

        page_ref.set(
            {
                "status": page_status,
                "result_blob_path": result_blob_path,
                "status_code": status_code,
                "error_message": event.get("error_message_safe"),
                "total_request_cost_usd": event.get("total_request_cost_usd"),
                "total_tokens_all": event.get("total_tokens_all"),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        _refresh_pdf_job_counters(job_id)
        return jsonify({'ok': True, 'status': page_status}), 200
    except Exception as e:
        logger.exception("Failed to process PDF job %s page %s", job_id, page_index)
        if quota_reserved:
            release_gemini_pro_quota(job_data.get("user_email"))
        failure_result = OrderedDict([
            ("filename", page_data.get("filename") or f"page_{page_index:04d}.jpg"),
            ("prompt", job_data.get("prompt")),
            ("ocr_info", {"error": _sanitize_error_message(str(e)) or "Page processing failed."}),
            ("WFO_info", ""),
            ("COP90_elevation_m", ""),
            ("ocr", ""),
            ("formatted_json", ""),
            ("parsing_info", OrderedDict([
                ("model", job_data.get("llm_model_name") or ""),
                ("input", 0),
                ("output", 0),
                ("cost_in", 0),
                ("cost_out", 0),
            ])),
            ("impact", {}),
            ("collage_info", {"error": "Page processing failed."}),
            ("collage_image_format", ""),
            ("success", {
                "image_available": "True",
                "text_collage": "False",
                "text_collage_resize": "False",
                "ocr": "False",
                "llm": "False",
            }),
        ])
        failure_event = build_usage_event(
            analytics_ctx=_build_pdf_job_analytics_context(job_data),
            result=failure_result,
            status_code=500,
            source_type="pdf_page",
            filename=page_data.get("filename"),
            source_pdf=job_data.get("source_pdf_filename"),
            page_index=page_index,
            page_count=_coerce_int(job_data.get("page_count")),
            success=False,
            include_in_rollup=False,
            error_type="processing_failure",
            error_message_safe=_sanitize_error_message(str(e)) or "Page processing failed.",
        )
        try:
            record_usage_event(failure_event)
        except Exception:
            logger.exception(
                "usage_events write failed route=/process-pdf-async request_id=%s page=%s failure",
                job_data.get("request_id"),
                page_index,
            )
        page_ref.set(
            {
                "status": "failed",
                "status_code": 500,
                "error_message": _sanitize_error_message(str(e)),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        _refresh_pdf_job_counters(job_id)
        return jsonify({'error': 'Failed to process the PDF job page.'}), 500


@app.route('/internal/pdf-jobs/<job_id>/finalize', methods=['POST'])
@internal_pdf_task_route
def internal_finalize_pdf_job(job_id):
    job_data = _get_pdf_job_or_404(job_id)
    if not job_data:
        return jsonify({'error': 'PDF job not found.'}), 404

    try:
        pages = _load_pdf_job_pages(job_id)
        successful_outputs = []
        manifest_pages = []

        for page in pages:
            page_summary = {
                "page_index": _coerce_int(page.get("page_index")),
                "filename": page.get("filename"),
                "status": page.get("status"),
                "status_code": _coerce_int(page.get("status_code")),
                "error_message": page.get("error_message"),
                "result_blob_path": page.get("result_blob_path"),
            }
            manifest_pages.append(page_summary)

            result_blob_path = page.get("result_blob_path")
            if page.get("status") == "completed" and result_blob_path:
                try:
                    result_payload = json.loads(_download_pdf_job_bytes(result_blob_path).decode("utf-8"))
                except Exception as e:
                    logger.warning("Unable to load page result for job %s page %s: %s", job_id, page.get("page_index"), e)
                    continue
                result_payload["page_index"] = _coerce_int(page.get("page_index"))
                result_payload.setdefault("filename", page.get("filename"))
                successful_outputs.append(result_payload)

        manifest = {
            "job_id": job_id,
            "request_id": job_data.get("request_id"),
            "source_pdf_filename": job_data.get("source_pdf_filename"),
            "status": "completed_with_errors" if _coerce_int(job_data.get("failed_pages")) else "completed",
            "page_count": len(pages),
            "successful_pages": sum(1 for page in pages if page.get("status") == "completed"),
            "failed_pages": sum(1 for page in pages if page.get("status") == "failed"),
            "created_at": _format_event_timestamp(job_data.get("created_at")),
            "expires_at": _format_event_timestamp(job_data.get("expires_at")),
            "pages": manifest_pages,
        }

        manifest_blob_path = _pdf_job_blob_path(job_id, "bundle", "manifest.json")
        xlsx_blob_path = _pdf_job_blob_path(job_id, "bundle", "results.xlsx")
        bundle_blob_path = _pdf_job_blob_path(job_id, "bundle", "results.zip")

        _upload_pdf_job_json(manifest_blob_path, manifest)
        xlsx_bytes = _create_pdf_job_xlsx_bytes(successful_outputs)
        _upload_pdf_job_bytes(
            xlsx_blob_path,
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("manifest.json", json.dumps(manifest, cls=OrderedJsonEncoder, ensure_ascii=False, indent=2))
            zip_file.writestr("results.xlsx", xlsx_bytes)
            for page in pages:
                result_blob_path = page.get("result_blob_path")
                page_label = f"page_{_coerce_int(page.get('page_index')):04d}"
                if result_blob_path:
                    try:
                        zip_file.writestr(
                            f"results/{page_label}.json",
                            _download_pdf_job_bytes(result_blob_path),
                        )
                        continue
                    except Exception:
                        logger.exception("Unable to include page result %s in ZIP", result_blob_path)
                zip_file.writestr(
                    f"results/{page_label}_error.json",
                    json.dumps(
                        {
                            "page_index": _coerce_int(page.get("page_index")),
                            "filename": page.get("filename"),
                            "status": page.get("status"),
                            "error_message": page.get("error_message"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        _upload_pdf_job_bytes(bundle_blob_path, zip_buffer.getvalue(), content_type="application/zip")

        final_status = "completed_with_errors" if manifest["failed_pages"] else "completed"
        db.collection("pdf_jobs").document(job_id).set(
            {
                "status": final_status,
                "phase": "completed",
                "bundle_blob_path": bundle_blob_path,
                "xlsx_blob_path": xlsx_blob_path,
                "manifest_blob_path": manifest_blob_path,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "finished_at": firestore.SERVER_TIMESTAMP,
                "email_status": "queued",
            },
            merge=True,
        )
        refreshed = _get_pdf_job_or_404(job_id)
        if refreshed:
            try:
                _enqueue_pdf_email_task(refreshed)
            except Exception as e:
                logger.exception("Failed to enqueue PDF completion email for job %s", job_id)
                db.collection("pdf_jobs").document(job_id).set(
                    {
                        "email_status": "failed",
                        "updated_at": firestore.SERVER_TIMESTAMP,
                        "error_summary": _sanitize_error_message(
                            refreshed.get("error_summary") or f"Email queue error: {e}"
                        ),
                    },
                    merge=True,
                )
        return jsonify({'ok': True, 'status': final_status}), 200
    except Exception as e:
        logger.exception("Failed to finalize PDF job %s", job_id)
        _mark_pdf_job_failed(job_id, str(e), phase="finalizing")
        return jsonify({'error': 'Failed to finalize the PDF job.'}), 500


@app.route('/internal/pdf-jobs/<job_id>/send-email', methods=['POST'])
@internal_pdf_task_route
def internal_send_pdf_job_email(job_id):
    job_data = _get_pdf_job_or_404(job_id)
    if not job_data:
        return jsonify({'error': 'PDF job not found.'}), 404

    try:
        email_sent = _send_pdf_job_completion_email(job_data)
        db.collection("pdf_jobs").document(job_id).set(
            {
                "email_status": "sent" if email_sent else "failed",
                "email_sent_at": firestore.SERVER_TIMESTAMP if email_sent else None,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return jsonify({'ok': True, 'email_sent': email_sent}), 200
    except Exception as e:
        logger.exception("Failed to send PDF job email %s", job_id)
        db.collection("pdf_jobs").document(job_id).set(
            {
                "email_status": "failed",
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return jsonify({'error': 'Failed to send the PDF job email.'}), 500


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


def _parse_bool_query_arg(name: str):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _parse_date_query_arg(name: str, *, end_exclusive: bool = False):
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        parsed = datetime.datetime.strptime(raw.strip(), "%Y-%m-%d")
        if end_exclusive:
            parsed += datetime.timedelta(days=1)
        return parsed
    except ValueError:
        return None


def _firestore_timestamp_to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)
    if hasattr(value, "to_datetime"):
        try:
            return value.to_datetime()
        except Exception:
            return None
    if hasattr(value, "_seconds"):
        try:
            return datetime.datetime.fromtimestamp(value._seconds, tz=datetime.timezone.utc)
        except Exception:
            return None
    return None


def _format_event_timestamp(value):
    dt = _firestore_timestamp_to_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize_usage_event(event_doc_or_dict):
    if hasattr(event_doc_or_dict, "to_dict"):
        payload = event_doc_or_dict.to_dict() or {}
        payload.setdefault("event_id", getattr(event_doc_or_dict, "id", None))
    else:
        payload = dict(event_doc_or_dict or {})

    payload["created_at"] = _format_event_timestamp(payload.get("created_at"))
    payload["total_request_cost_usd"] = _coerce_float(payload.get("total_request_cost_usd"))
    payload["total_tokens_all"] = _coerce_int(payload.get("total_tokens_all"))
    payload["total_watt_hours"] = _coerce_float(payload.get("total_watt_hours"))
    payload["total_grams_CO2"] = _coerce_float(payload.get("total_grams_CO2"))
    payload["total_mL_water"] = _coerce_float(payload.get("total_mL_water"))
    payload["page_index"] = _coerce_int(payload.get("page_index")) if payload.get("page_index") else None
    payload["page_count"] = _coerce_int(payload.get("page_count")) if payload.get("page_count") else None
    payload["ocr_models"] = payload.get("ocr_models") if isinstance(payload.get("ocr_models"), list) else []
    payload["success"] = bool(payload.get("success"))
    payload["ocr_only"] = bool(payload.get("ocr_only"))
    payload["notebook_mode"] = bool(payload.get("notebook_mode"))
    return payload


def _build_usage_events_query(
    *,
    user_email: str | None = None,
    auth_method: str | None = None,
    endpoint: str | None = None,
    source_type: str | None = None,
    success: bool | None = None,
    ocr_only: bool | None = None,
    notebook_mode: bool | None = None,
    parsing_model: str | None = None,
    ocr_model: str | None = None,
    prompt: str | None = None,
    date_from=None,
    date_to=None,
    order_desc: bool = True,
):
    query = db.collection("usage_events")
    if user_email:
        query = query.where(filter=FieldFilter("user_email", "==", user_email))
    if auth_method:
        query = query.where(filter=FieldFilter("auth_method", "==", auth_method))
    if endpoint:
        query = query.where(filter=FieldFilter("endpoint", "==", endpoint))
    if source_type:
        query = query.where(filter=FieldFilter("source_type", "==", source_type))
    if success is not None:
        query = query.where(filter=FieldFilter("success", "==", success))
    if ocr_only is not None:
        query = query.where(filter=FieldFilter("ocr_only", "==", ocr_only))
    if notebook_mode is not None:
        query = query.where(filter=FieldFilter("notebook_mode", "==", notebook_mode))
    if parsing_model:
        query = query.where(filter=FieldFilter("parsing_model", "==", parsing_model))
    if ocr_model:
        query = query.where(filter=FieldFilter("ocr_models", "array_contains", ocr_model))
    if prompt:
        query = query.where(filter=FieldFilter("prompt", "==", prompt))
    if date_from:
        query = query.where(filter=FieldFilter("created_at", ">=", date_from))
    if date_to:
        query = query.where(filter=FieldFilter("created_at", "<", date_to))
    direction = firestore.Query.DESCENDING if order_desc else firestore.Query.ASCENDING
    return query.order_by("created_at", direction=direction)


def _get_usage_event_filters_from_request():
    return {
        "user_email": request.args.get("user_email") or None,
        "auth_method": request.args.get("auth_method") or None,
        "endpoint": request.args.get("endpoint") or None,
        "source_type": request.args.get("source_type") or None,
        "success": _parse_bool_query_arg("success"),
        "ocr_only": _parse_bool_query_arg("ocr_only"),
        "notebook_mode": _parse_bool_query_arg("notebook_mode"),
        "parsing_model": request.args.get("parsing_model") or None,
        "ocr_model": request.args.get("ocr_model") or None,
        "prompt": request.args.get("prompt") or None,
        "date_from": _parse_date_query_arg("date_from"),
        "date_to": _parse_date_query_arg("date_to", end_exclusive=True),
    }


def _dimension_value_for_event(event: dict, dimension: str, value: str | None = None):
    if dimension == "ocr_model":
        models = event.get("ocr_models") if isinstance(event.get("ocr_models"), list) else []
        return models if value is None else value in models
    if dimension in {"ocr_only", "notebook_mode", "success"}:
        current = bool(event.get(dimension))
        if value is None:
            return current
        wanted = str(value).strip().lower() in {"true", "1", "yes"}
        return current == wanted
    current = event.get(dimension)
    if value is None:
        return current
    return current == value


def _event_matches_filters(event: dict, filters: dict) -> bool:
    if filters.get("user_email") and event.get("user_email") != filters["user_email"]:
        return False
    if filters.get("auth_method") and event.get("auth_method") != filters["auth_method"]:
        return False
    if filters.get("endpoint") and event.get("endpoint") != filters["endpoint"]:
        return False
    if filters.get("source_type") and event.get("source_type") != filters["source_type"]:
        return False
    if filters.get("success") is not None and bool(event.get("success")) != filters["success"]:
        return False
    if filters.get("ocr_only") is not None and bool(event.get("ocr_only")) != filters["ocr_only"]:
        return False
    if filters.get("notebook_mode") is not None and bool(event.get("notebook_mode")) != filters["notebook_mode"]:
        return False
    if filters.get("parsing_model") and event.get("parsing_model") != filters["parsing_model"]:
        return False
    if filters.get("prompt") and event.get("prompt") != filters["prompt"]:
        return False
    if filters.get("ocr_model"):
        models = event.get("ocr_models") if isinstance(event.get("ocr_models"), list) else []
        if filters["ocr_model"] not in models:
            return False

    created_at = _firestore_timestamp_to_datetime(event.get("created_at"))
    if filters.get("date_from") and (created_at is None or created_at < filters["date_from"].replace(tzinfo=datetime.timezone.utc)):
        return False
    if filters.get("date_to") and (created_at is None or created_at >= filters["date_to"].replace(tzinfo=datetime.timezone.utc)):
        return False
    return True


def _load_usage_events_filtered(filters: dict, *, order_desc: bool = True):
    docs = db.collection("usage_events").stream()
    events = []
    for doc in docs:
        event = (doc.to_dict() or {}) | {"event_id": doc.id}
        if _event_matches_filters(event, filters):
            events.append(event)
    events.sort(
        key=lambda e: _firestore_timestamp_to_datetime(e.get("created_at")) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=order_desc,
    )
    return events


def _fetch_usage_events_for_overview(scope: str, dimension: str | None, value: str | None):
    filters = _get_usage_event_filters_from_request()
    if scope == "user":
        filters["user_email"] = request.args.get("user_email") or filters["user_email"]
    elif scope == "dimension" and dimension:
        if dimension == "ocr_model":
            filters["ocr_model"] = value
        elif dimension in {"ocr_only", "notebook_mode", "success"}:
            filters[dimension] = str(value).strip().lower() in {"true", "1", "yes"}
        else:
            filters[dimension] = value

    return _load_usage_events_filtered(filters, order_desc=True)


def _summarize_usage_events(events: list[dict]) -> dict:
    daily = {}
    weekly = {}
    auth_method_split = {}
    ocr_model_mix = {}
    parsing_model_mix = {}
    success_count = 0
    failure_count = 0
    total_cost = 0.0
    total_tokens = 0
    total_pdf_pages = 0
    unique_users = set()
    first_tracked_event_at = None
    recent_sorted = sorted(
        events,
        key=lambda e: _firestore_timestamp_to_datetime(e.get("created_at")) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=True,
    )

    for event in events:
        dt = _firestore_timestamp_to_datetime(event.get("created_at"))
        if dt:
            day_key = dt.strftime("%Y-%m-%d")
            iso_year, iso_week, _ = dt.isocalendar()
            week_key = f"{iso_year}-W{iso_week:02d}"
            day_bucket = daily.setdefault(day_key, {"events": 0, "cost_usd": 0.0, "tokens": 0})
            week_bucket = weekly.setdefault(week_key, {"events": 0, "cost_usd": 0.0, "tokens": 0})
            if first_tracked_event_at is None or dt < first_tracked_event_at:
                first_tracked_event_at = dt
        else:
            day_bucket = None
            week_bucket = None

        success = bool(event.get("success"))
        if success:
            success_count += 1
        else:
            failure_count += 1

        cost = _coerce_float(event.get("total_request_cost_usd"))
        tokens = _coerce_int(event.get("total_tokens_all"))
        total_cost += cost
        total_tokens += tokens
        if event.get("source_type") == "pdf_page":
            total_pdf_pages += 1

        user_email = event.get("user_email")
        if user_email:
            unique_users.add(user_email)

        if day_bucket is not None:
            day_bucket["events"] += 1
            day_bucket["cost_usd"] += cost
            day_bucket["tokens"] += tokens
        if week_bucket is not None:
            week_bucket["events"] += 1
            week_bucket["cost_usd"] += cost
            week_bucket["tokens"] += tokens

        auth_key = event.get("auth_method") or "unknown"
        auth_bucket = auth_method_split.setdefault(auth_key, {"events": 0, "cost_usd": 0.0, "tokens": 0})
        auth_bucket["events"] += 1
        auth_bucket["cost_usd"] += cost
        auth_bucket["tokens"] += tokens

        for model_name, ocr_payload in (event.get("ocr_info") or {}).items():
            if model_name == "error" or not isinstance(ocr_payload, dict):
                continue
            model_bucket = ocr_model_mix.setdefault(model_name, {"events": 0, "cost_usd": 0.0, "tokens": 0})
            model_bucket["events"] += 1
            model_bucket["cost_usd"] += _coerce_float(ocr_payload.get("total_cost"))
            model_bucket["tokens"] += _coerce_int(ocr_payload.get("total_tokens"))

        parsing_model = event.get("parsing_model") or "none"
        parsing_bucket = parsing_model_mix.setdefault(parsing_model, {"events": 0, "cost_usd": 0.0, "tokens": 0})
        parsing_bucket["events"] += 1
        parsing_bucket["cost_usd"] += _coerce_float(event.get("parsing_cost_total_usd"))
        parsing_bucket["tokens"] += _coerce_int(event.get("parsing_tokens_total"))

    return {
        "headline": {
            "total_events": len(events),
            "success_count": success_count,
            "failure_count": failure_count,
            "total_cost_usd": round(total_cost, 10),
            "average_cost_usd": round(total_cost / len(events), 10) if events else 0.0,
            "total_tokens_all": total_tokens,
            "total_pdf_pages": total_pdf_pages,
            "unique_users": len(unique_users),
        },
        "timeseries": {
            "daily": [
                {"date": key, **value}
                for key, value in sorted(daily.items())
            ],
            "weekly": [
                {"week": key, **value}
                for key, value in sorted(weekly.items())
            ],
        },
        "auth_method_split": auth_method_split,
        "ocr_model_mix": ocr_model_mix,
        "parsing_model_mix": parsing_model_mix,
        "recent_events": [
            _serialize_usage_event(event)
            for event in recent_sorted[:25]
        ],
        "first_tracked_event_at": _format_event_timestamp(first_tracked_event_at),
    }


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

            # The Firestore doc ID is the user's email. Older docs (pre-carbon-impact
            # commit) don't carry user_email in the body, so fall back to the doc ID
            # to avoid rendering "Unknown" in the dashboard.
            stat_data.setdefault('user_email', stat_doc.id)

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


@app.route('/admin/usage-events', methods=['GET'])
@authenticated_route
def get_usage_events():
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = user.get('email')
    if not db.collection('admins').document(admin_email).get().exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    try:
        filters = _get_usage_event_filters_from_request()
        limit = max(1, min(_coerce_int(request.args.get("limit"), 50), 200))
        cursor = request.args.get("cursor")

        all_events = _load_usage_events_filtered(filters, order_desc=True)
        start_idx = 0
        if cursor:
            for idx, event in enumerate(all_events):
                if event.get("event_id") == cursor:
                    start_idx = idx + 1
                    break
        page_events = all_events[start_idx:start_idx + limit + 1]
        has_more = len(page_events) > limit
        page_events = page_events[:limit]
        events = [_serialize_usage_event(event) for event in page_events]
        next_cursor = events[-1]["event_id"] if has_more and events else None

        return jsonify({
            "status": "success",
            "count": len(events),
            "events": events,
            "next_cursor": next_cursor,
        })
    except Exception as e:
        logger.error(f"Error getting usage events: {str(e)}")
        return jsonify({'error': f'Failed to get usage events: {str(e)}'}), 500


@app.route('/admin/usage-events/facets', methods=['GET'])
@authenticated_route
def get_usage_event_facets():
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = user.get('email')
    if not db.collection('admins').document(admin_email).get().exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    try:
        filters = _get_usage_event_filters_from_request()
        facets = {
            "users": set(),
            "ocr_models": set(),
            "parsing_models": set(),
            "prompts": set(),
            "endpoints": set(),
            "source_types": set(),
            "auth_methods": set(),
        }

        for event in _load_usage_events_filtered(filters, order_desc=False):
            if event.get("user_email"):
                facets["users"].add(event["user_email"])
            if event.get("parsing_model"):
                facets["parsing_models"].add(event["parsing_model"])
            if event.get("prompt"):
                facets["prompts"].add(event["prompt"])
            if event.get("endpoint"):
                facets["endpoints"].add(event["endpoint"])
            if event.get("source_type"):
                facets["source_types"].add(event["source_type"])
            if event.get("auth_method"):
                facets["auth_methods"].add(event["auth_method"])
            for model_name in event.get("ocr_models") or []:
                if model_name:
                    facets["ocr_models"].add(model_name)

        earliest_docs = list(
            db.collection("usage_events")
            .order_by("created_at", direction=firestore.Query.ASCENDING)
            .limit(1)
            .stream()
        )
        first_tracked_event_at = None
        if earliest_docs:
            first_tracked_event_at = _format_event_timestamp(
                (earliest_docs[0].to_dict() or {}).get("created_at")
            )

        return jsonify({
            "status": "success",
            "dimensions": list(USAGE_EVENT_DIMENSIONS),
            "facets": {key: sorted(values) for key, values in facets.items()},
            "first_tracked_event_at": first_tracked_event_at,
            "tracking_note": "Event-level analytics are forward-only from this feature's deployment.",
        })
    except Exception as e:
        logger.error(f"Error getting usage event facets: {str(e)}")
        return jsonify({'error': f'Failed to get usage event facets: {str(e)}'}), 500


@app.route('/admin/usage-events/overview', methods=['GET'])
@authenticated_route
def get_usage_events_overview():
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = user.get('email')
    if not db.collection('admins').document(admin_email).get().exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    try:
        scope = request.args.get("scope", "user")
        if scope not in {"user", "dimension"}:
            return jsonify({"error": "scope must be 'user' or 'dimension'"}), 400

        dimension = request.args.get("dimension")
        value = request.args.get("value")
        if scope == "user" and not (request.args.get("user_email") or "").strip():
            return jsonify({"error": "user_email is required for scope=user"}), 400
        if scope == "dimension":
            if dimension not in USAGE_EVENT_DIMENSIONS:
                return jsonify({"error": "Unsupported dimension"}), 400
            if value in (None, ""):
                return jsonify({"error": "value is required for scope=dimension"}), 400

        events = _fetch_usage_events_for_overview(scope, dimension, value)
        summary = _summarize_usage_events(events)

        return jsonify({
            "status": "success",
            "scope": scope,
            "dimension": dimension,
            "value": value,
            "filters": {
                key: request.args.get(key)
                for key in (
                    "user_email",
                    "auth_method",
                    "endpoint",
                    "source_type",
                    "success",
                    "ocr_only",
                    "notebook_mode",
                    "parsing_model",
                    "ocr_model",
                    "prompt",
                    "date_from",
                    "date_to",
                )
                if request.args.get(key) is not None
            },
            **summary,
        })
    except Exception as e:
        logger.error(f"Error building usage event overview: {str(e)}")
        return jsonify({'error': f'Failed to build usage event overview: {str(e)}'}), 500


@app.route('/admin/backfill-usage-statistics', methods=['POST'])
@authenticated_route
def backfill_usage_statistics():
    """Bulk one-shot backfill across all usage_statistics docs.

    Two independent, idempotent fixes applied per doc:
      1. Set user_email field from doc.id when missing (legacy docs).
      2. Apply the historical impact rollup (water/CO2/Wh/tokens) when
         backfill_applied_v2 is False and total_images_processed > 0.

    Returns a JSON summary. Safe to re-run.
    """
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = user.get('email')
    if not db.collection('admins').document(admin_email).get().exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    docs_scanned = 0
    emails_filled = 0
    impacts_backfilled = 0
    impacts_marked_no_op = 0
    errors = []

    try:
        for stat_doc in db.collection('usage_statistics').stream():
            docs_scanned += 1
            try:
                data = stat_doc.to_dict() or {}
                user_ref = stat_doc.reference

                # Fix 1: backfill missing user_email from the doc ID.
                if not data.get('user_email'):
                    user_ref.update({"user_email": stat_doc.id})
                    data['user_email'] = stat_doc.id
                    emails_filled += 1

                # Fix 2: apply impact backfill (helper is idempotent).
                bf = _apply_impact_backfill(user_ref, data, backfill_tokens=5000)
                if bf.get('applied'):
                    impacts_backfilled += 1
                elif bf.get('reason') == 'no_prior_uses':
                    impacts_marked_no_op += 1
            except Exception as e:
                logger.error(f"Bulk backfill error for {stat_doc.id}: {e}")
                errors.append({"doc_id": stat_doc.id, "error": str(e)})

        logger.info(
            f"Bulk backfill complete: scanned={docs_scanned} "
            f"emails_filled={emails_filled} impacts_backfilled={impacts_backfilled} "
            f"errors={len(errors)} (admin={admin_email})"
        )
        return jsonify({
            'status': 'success',
            'docs_scanned': docs_scanned,
            'emails_filled': emails_filled,
            'impacts_backfilled': impacts_backfilled,
            'impacts_marked_no_op': impacts_marked_no_op,
            'errors': errors,
        })
    except Exception as e:
        logger.error(f"Bulk backfill failed: {e}")
        return jsonify({'error': f'Bulk backfill failed: {e}'}), 500


@app.route('/admin/cost-analytics', methods=['GET'])
@authenticated_route
def get_cost_analytics():
    """Return merged GCP-invoice + Firestore-usage cost report for the admin dashboard.

    Invoices are read from gs://vouchervision-cop90-rasters/invoices/*.csv.
    Firestore usage_statistics is queried for per-user specimen + model counts.
    Response is cached for ~60s keyed on invoice blob etags.
    """
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = user.get('email')
    admin_doc = db.collection('admins').document(admin_email).get()
    if not admin_doc.exists:
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    try:
        import cost_analytics

        usage_docs = []
        for stat_doc in db.collection('usage_statistics').stream():
            usage_docs.append(stat_doc.to_dict())

        storage_client = cost_analytics.build_storage_client()
        report = cost_analytics.load_report_from_gcs(storage_client, usage_docs)
        report['status'] = 'success'
        return jsonify(report)

    except cost_analytics._CredentialError:
        # Message is already sanitized; still do not include it in the response.
        logger.error("Cost analytics: credential error (see prior log lines)")
        return jsonify({'error': 'Cost analytics credential error (see server logs)'}), 500
    except Exception:
        # Never interpolate the exception into the log or response body — upstream
        # libraries sometimes embed raw credential JSON in exception messages.
        logger.exception("Cost analytics: unexpected error")
        return jsonify({'error': 'Failed to build cost analytics (see server logs)'}), 500


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
def cors_test():
    """Simple endpoint to test CORS configuration"""
    return jsonify({
        'status': 'ok',
        'cors': 'enabled',
        'message': 'If you can see this response in your browser or JavaScript app, CORS is working correctly.'
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
    """Health check endpoint that reports server status"""
    
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
    
    # Create the response
    response = jsonify({
        'status': 'ok',
        'active_requests': active_requests,
        'max_concurrent_requests': max_requests,
        'server_load': f"{(active_requests / max_requests) * 100:.1f}%",
        'api_status': 'available'
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


@app.route('/admin/vertex-projects', methods=['GET'])
@authenticated_route
def list_all_vertex_projects():
    """List all Vertex project bindings (admin only)."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = _normalize_email_identity(user.get('email'))
    if not _is_admin_email(admin_email):
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    try:
        project_docs = db.collection('vertex_projects').stream()
        projects = [_serialize_vertex_project(doc) for doc in project_docs]
        projects.sort(
            key=lambda project: (
                project.get('created_at') or '',
                project.get('owner_email') or '',
                project.get('project_id') or '',
            ),
            reverse=True,
        )
        return jsonify({
            'status': 'success',
            'count': len(projects),
            'vertex_projects': projects,
        })
    except Exception as e:
        logger.error(f"Error listing all vertex projects: {str(e)}")
        return jsonify({'error': f'Failed to list Vertex projects: {str(e)}'}), 500


@app.route('/admin/vertex-projects', methods=['POST'])
@authenticated_route
def admin_create_vertex_project():
    """Create or reactivate a Vertex project binding on behalf of a user."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = _normalize_email_identity(user.get('email'))
    if not _is_admin_email(admin_email):
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    try:
        data = request.get_json() or {}
        owner_email = _clean_optional_request_value(data.get('owner_email'))
        if not owner_email:
            return jsonify({'error': 'Owner email is required.'}), 400
        owner_email = owner_email.strip().lower()

        normalized_project_id, validation_error = _validate_vertex_project_id(data.get('project_id'))
        if validation_error:
            return jsonify({'error': validation_error}), 400

        nickname = _clean_optional_request_value(data.get('nickname')) or ''
        if len(nickname) > 100:
            return jsonify({'error': 'Nickname must be 100 characters or fewer.'}), 400

        payload, status_code = _claim_or_reactivate_vertex_project(
            project_id=normalized_project_id,
            owner_email=owner_email,
            actor_email=admin_email,
            nickname=nickname,
        )
        return jsonify(payload), status_code
    except Exception as e:
        logger.error(f"Error creating admin vertex project binding: {str(e)}")
        return jsonify({'error': f'Failed to create Vertex project binding: {str(e)}'}), 500


@app.route('/admin/vertex-projects/<project_id>/revoke', methods=['POST'])
@authenticated_route
def admin_revoke_vertex_project(project_id):
    """Revoke any Vertex project binding (admin only)."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    admin_email = _normalize_email_identity(user.get('email'))
    if not _is_admin_email(admin_email):
        return jsonify({'error': 'Unauthorized - Admin access required'}), 403

    normalized_project_id, validation_error = _validate_vertex_project_id(project_id)
    if validation_error:
        return jsonify({'error': validation_error}), 400

    try:
        project_ref = db.collection('vertex_projects').document(normalized_project_id)
        project_doc = project_ref.get()
        if not project_doc.exists:
            return jsonify({'error': 'Vertex project not found'}), 404

        project_data = project_doc.to_dict() or {}
        if not bool(project_data.get('active')):
            return jsonify({'error': 'Vertex project is already revoked'}), 400

        project_ref.update({
            'active': False,
            'revoked_at': firestore.SERVER_TIMESTAMP,
            'revoked_by': admin_email,
            'updated_at': firestore.SERVER_TIMESTAMP,
        })

        return jsonify({
            'status': 'success',
            'message': f"Vertex project '{normalized_project_id}' has been revoked.",
        })
    except Exception as e:
        logger.error(f"Error revoking admin vertex project binding: {str(e)}")
        return jsonify({'error': f'Failed to revoke Vertex project: {str(e)}'}), 500

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
    
    user_email = _normalize_email_identity(user.get('email'))
    
    try:
        access_state = _get_api_key_access_state(user_email)
        if not access_state.get('allowed'):
            logger.warning(
                "User %s attempted to create API key without permission code=%s",
                user_email,
                access_state.get('code'),
            )
            return jsonify({
                'error': access_state.get('error', 'Unauthorized'),
                'code': access_state.get('code')
            }), access_state.get('status_code', 403)

        logger.info(
            "User %s authorized to create API key (%s)",
            user_email,
            "admin" if access_state.get('is_admin') else "approved user",
        )
        
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


@app.route('/vertex-projects', methods=['GET'])
@authenticated_route
def list_vertex_projects():
    """List Vertex project bindings for the authenticated user."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    user_email = _normalize_email_identity(user.get('email'))
    access_state = _get_api_key_access_state(user_email)
    if not access_state.get('allowed'):
        return jsonify({
            'error': access_state.get('error', 'Unauthorized'),
            'code': access_state.get('code'),
        }), access_state.get('status_code', 403)

    try:
        project_docs = db.collection('vertex_projects').where(
            filter=FieldFilter('owner_email', '==', user_email)
        ).stream()
        projects = [_serialize_vertex_project(doc) for doc in project_docs]
        projects.sort(
            key=lambda project: (
                project.get('created_at') or '',
                project.get('project_id') or '',
            ),
            reverse=True,
        )
        return jsonify({
            'status': 'success',
            'count': len(projects),
            'vertex_projects': projects,
        })
    except Exception as e:
        logger.error(f"Error listing vertex projects for {user_email}: {str(e)}")
        return jsonify({'error': f'Failed to list Vertex projects: {str(e)}'}), 500


@app.route('/vertex-projects/link', methods=['POST'])
@authenticated_route
def link_vertex_project():
    """Link a Google Cloud project ID to the authenticated user."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    user_email = _normalize_email_identity(user.get('email'))
    access_state = _get_api_key_access_state(user_email)
    if not access_state.get('allowed'):
        return jsonify({
            'error': access_state.get('error', 'Unauthorized'),
            'code': access_state.get('code'),
        }), access_state.get('status_code', 403)

    try:
        data = request.get_json() or {}
        normalized_project_id, validation_error = _validate_vertex_project_id(data.get('project_id'))
        if validation_error:
            return jsonify({'error': validation_error}), 400

        nickname = _clean_optional_request_value(data.get('nickname')) or ''
        if len(nickname) > 100:
            return jsonify({'error': 'Nickname must be 100 characters or fewer.'}), 400

        payload, status_code = _claim_or_reactivate_vertex_project(
            project_id=normalized_project_id,
            owner_email=user_email,
            actor_email=user_email,
            nickname=nickname,
        )
        return jsonify(payload), status_code
    except Exception as e:
        logger.error(f"Error linking vertex project for {user_email}: {str(e)}")
        return jsonify({'error': f'Failed to link Vertex project: {str(e)}'}), 500


@app.route('/vertex-projects/<project_id>/revoke', methods=['POST'])
@authenticated_route
def revoke_vertex_project(project_id):
    """Revoke a linked Vertex project owned by the authenticated user."""
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401

    user_email = _normalize_email_identity(user.get('email'))
    access_state = _get_api_key_access_state(user_email)
    if not access_state.get('allowed'):
        return jsonify({
            'error': access_state.get('error', 'Unauthorized'),
            'code': access_state.get('code'),
        }), access_state.get('status_code', 403)

    normalized_project_id, validation_error = _validate_vertex_project_id(project_id)
    if validation_error:
        return jsonify({'error': validation_error}), 400

    try:
        project_ref = db.collection('vertex_projects').document(normalized_project_id)
        project_doc = project_ref.get()
        if not project_doc.exists:
            return jsonify({'error': 'Vertex project not found'}), 404

        project_data = project_doc.to_dict() or {}
        if _normalize_email_identity(project_data.get('owner_email')) != user_email:
            return jsonify({'error': 'You do not have permission to revoke this Vertex project'}), 403
        if not bool(project_data.get('active')):
            return jsonify({'error': 'Vertex project is already revoked'}), 400

        project_ref.update({
            'active': False,
            'revoked_at': firestore.SERVER_TIMESTAMP,
            'revoked_by': user_email,
            'updated_at': firestore.SERVER_TIMESTAMP,
        })

        return jsonify({
            'status': 'success',
            'message': f"Vertex project '{normalized_project_id}' revoked successfully.",
        })
    except Exception as e:
        logger.error(f"Error revoking vertex project for {user_email}: {str(e)}")
        return jsonify({'error': f'Failed to revoke Vertex project: {str(e)}'}), 500

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
        access_state = _get_api_key_access_state(user_email)
        logger.info(
            "User %s API key permission check: allowed=%s is_admin=%s code=%s",
            user_email,
            access_state.get('allowed'),
            access_state.get('is_admin'),
            access_state.get('code'),
        )
        payload = {
            'status': 'success' if access_state.get('allowed') else 'error',
            'has_api_key_permission': bool(access_state.get('allowed')),
            'is_approved': bool(access_state.get('is_approved', access_state.get('allowed'))),
            'is_admin': bool(access_state.get('is_admin')),
            'debug_info': {
                'email': user_email,
                'approved': bool(access_state.get('is_approved', access_state.get('allowed'))),
                'api_key_access': bool(access_state.get('has_api_key_access', access_state.get('allowed'))),
            }
        }
        if not access_state.get('allowed'):
            payload['message'] = access_state.get('error')
            payload['code'] = access_state.get('code')
            return jsonify(payload), access_state.get('status_code', 403)
        return jsonify(payload)
        
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
    port = int(os.environ.get('PORT', 8080))
    logger.info('VoucherVision service is starting up directly (not under Gunicorn)...')
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
else:
    app.logger.propagate = True
    logger.info('VoucherVision service starting under Gunicorn')
