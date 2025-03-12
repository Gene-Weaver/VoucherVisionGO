import os
import requests
import sys
import json
import datetime
import tempfile
import threading
from flask import Flask, request, jsonify, render_template_string, redirect, make_response, render_template
from flask_cors import CORS
import logging
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from collections import OrderedDict
from pathlib import Path
import yaml
import re
from functools import wraps
from io import BytesIO

import firebase_admin
from firebase_admin import credentials, auth, firestore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup paths and imports
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

submodule_path = os.path.join(project_root, "vouchervision_main")
sys.path.insert(0, submodule_path)

vouchervision_path = os.path.join(submodule_path, "vouchervision")
sys.path.insert(0, vouchervision_path)

component_detector_path = os.path.join(vouchervision_path, "component_detector")
sys.path.insert(0, component_detector_path)

# Import VoucherVision modules
try:
    from vouchervision_main.vouchervision.OCR_Gemini import OCRGeminiProVision
    from vouchervision_main.vouchervision.vouchervision_main import load_custom_cfg
    from vouchervision_main.vouchervision.utils_VoucherVision import VoucherVision
    from vouchervision_main.vouchervision.LLM_GoogleGemini import GoogleGeminiHandler
    from vouchervision_main.vouchervision.model_maps import ModelMaps
    from vouchervision_main.vouchervision.general_utils import calculate_cost
    from send_email import SimpleEmailSender
    
except:
    from vouchervision.OCR_Gemini import OCRGeminiProVision # type: ignore
    from vouchervision.vouchervision_main import load_custom_cfg # type: ignore
    from vouchervision.utils_VoucherVision import VoucherVision # type: ignore
    from vouchervision.LLM_GoogleGemini import GoogleGeminiHandler # type: ignore
    from vouchervision.model_maps import ModelMaps # type: ignore
    from vouchervision.general_utils import calculate_cost # type: ignore
    from send_email import SimpleEmailSender

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
        # Fallback to default initialization
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "vouchervision-387816")
        firebase_admin.initialize_app(options={"projectId": project_id})
        logger.info(f"Firebase Admin SDK initialized with default options for project: {project_id}")
except ValueError as e:
    # Already initialize
    logger.info(f"Firebase Admin SDK already initialized: {e}")
except Exception as e:
    logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
    # Log but continue - better to try to operate than to crash completely
    logger.error(f"Continuing despite initialization error")

# Initialize Firestore client
db = firestore.client()


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
    
    # If not in header, check in query parameters
    if not id_token:
        id_token = request.args.get('token')
    
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

def authenticated_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for API key first in header
        api_key = request.headers.get('X-API-Key')
        
        # Also check for API key in query parameters (for easier testing)
        if not api_key:
            api_key = request.args.get('api_key')
        
        if api_key and validate_api_key(api_key):
            # API key is valid
            logger.info(f"Request authenticated via API key: {api_key[:8]}...")
            return f(*args, **kwargs)
        
        # Fall back to Firebase token authentication
        user = authenticate_request(request)
        if user:
            logger.info(f"Request authenticated via Firebase: {user.get('email', 'unknown')}") 
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
                logger.info(f"Request acquired. Active requests: {self.active_count}/{self.max_concurrent}")
        return acquired
        
    def release(self):
        """Release a processing slot"""
        self.semaphore.release()
        with self.lock:
            self.active_count -= 1
            logger.info(f"Request completed. Active requests: {self.active_count}/{self.max_concurrent}")
    
    def get_active_count(self):
        """Get the current count of active requests"""
        with self.lock:
            return self.active_count
        
class VoucherVisionProcessor:
    """
    Class to handle VoucherVision processing with initialization done once.
    """
    def __init__(self, max_concurrent=32, LLM_name_cost='GEMINI_2_0_FLASH'): 
        # Configuration
        self.ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'tif', 'tiff'}
        self.MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB max upload size
        self.LLM_name_cost = LLM_name_cost
        
        # Initialize request throttler
        self.throttler = RequestThrottler(max_concurrent)
        
        # Get API key for Gemini
        self.api_key = self._get_api_key()
        
        # Initialize OCR engines 
        self.ocr_engines = {}
        self.ocr_engines_lock = threading.Lock()
        for model_name in ["gemini-1.5-pro", "gemini-2.0-flash"]:
            self.ocr_engines[model_name] = OCRGeminiProVision(
                self.api_key, 
                model_name=model_name, 
                max_output_tokens=1024, 
                temperature=0.5, 
                top_p=0.3, 
                top_k=3, 
                seed=123456, 
                do_resize_img=False
            )
        
        # Initialize VoucherVision components
        self.config_file = os.path.join(os.path.dirname(__file__), 'VoucherVision.yaml')
        
        # Validate config file exists
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"Configuration file not found at {self.config_file}")

        # Load configuration
        self.cfg = load_custom_cfg(self.config_file)
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.dir_home = os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main"))

        self.Voucher_Vision = VoucherVision(
            self.cfg, self.logger, self.dir_home, None, None, None, 
            is_hf=False, skip_API_keys=True
        )

        self.Voucher_Vision.initialize_token_counters()
        # Default prompt file
        self.default_prompt = "SLTPvM_default.yaml"
        self.custom_prompts_dir = os.path.join(self.dir_home, 'custom_prompts')

        self.Voucher_Vision.path_custom_prompts = os.path.join(
            self.dir_home, 
            'custom_prompts', 
            self.default_prompt
        )

        # Initialize LLM model handler
        self.model_name = ModelMaps.get_API_name(self.Voucher_Vision.model_name)
        self.Voucher_Vision.setup_JSON_dict_structure()
        
        self.llm_model = GoogleGeminiHandler(
            self.cfg, self.logger, self.model_name, self.Voucher_Vision.JSON_dict_structure, 
            config_vals_for_permutation=None, exit_early_for_JSON=True
        )

        # Thread-local storage for handling per-request VoucherVision instances
        self.thread_local = threading.local()
    
    def _get_api_key(self):
        """Get API key from environment variable"""
        api_key = os.environ.get("API_KEY")
        if not api_key:
            raise ValueError("API_KEY environment variable not set")
        return api_key
    
    def allowed_file(self, filename):
        """Check if file has allowed extension"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS
    
    def perform_ocr(self, file_path, engine_options):
        """Perform OCR on the provided image"""
        ocr_packet = {}
        ocr_all = ""
        
        for ocr_opt in engine_options:
            ocr_packet[ocr_opt] = {}
            logger.info(f"ocr_opt {ocr_opt}")
            
            # Thread-safe access to OCR engines
            with self.ocr_engines_lock:
                # Use pre-initialized OCR engine if available, or create a new one
                if ocr_opt not in self.ocr_engines:
                    self.ocr_engines[ocr_opt] = OCRGeminiProVision(
                        self.api_key, 
                        model_name=ocr_opt, 
                        max_output_tokens=1024, 
                        temperature=0.5, 
                        top_p=0.3, 
                        top_k=3, 
                        seed=123456, 
                        do_resize_img=False
                    )
                
                OCR_Engine = self.ocr_engines[ocr_opt]
            
            # Execute OCR (this API call can run concurrently)
            response, cost_in, cost_out, total_cost, rates_in, rates_out, tokens_in, tokens_out = OCR_Engine.ocr_gemini(file_path)
            
            ocr_packet[ocr_opt]["ocr_text"] = response
            ocr_packet[ocr_opt]["cost_in"] = cost_in
            ocr_packet[ocr_opt]["cost_out"] = cost_out
            ocr_packet[ocr_opt]["total_cost"] = total_cost
            ocr_packet[ocr_opt]["rates_in"] = rates_in
            ocr_packet[ocr_opt]["rates_out"] = rates_out
            ocr_packet[ocr_opt]["tokens_in"] = tokens_in
            ocr_packet[ocr_opt]["tokens_out"] = tokens_out

            ocr_all += f"\n{ocr_opt} OCR:\n{response}"

        return ocr_packet, ocr_all
    
    def get_thread_local_vv(self, prompt):
        """Get or create a thread-local VoucherVision instance with the specified prompt"""
        # Always create a new instance when a prompt is explicitly specified
        if prompt != self.default_prompt or not hasattr(self.thread_local, 'vv'):
            # Clone the base VoucherVision object for this thread
            self.thread_local.vv = VoucherVision(
                self.cfg, self.logger, self.dir_home, None, None, None, 
                is_hf=False, skip_API_keys=True
            )
            self.thread_local.vv.initialize_token_counters()
            
            # Set the custom prompt path
            self.thread_local.vv.path_custom_prompts = os.path.join(
                self.custom_prompts_dir,
                prompt
            )
            self.thread_local.vv.setup_JSON_dict_structure()
            self.thread_local.prompt = prompt
            
            # Create a thread-local LLM model handler
            self.thread_local.llm_model = GoogleGeminiHandler(
                self.cfg, self.logger, self.model_name, self.thread_local.vv.JSON_dict_structure, 
                config_vals_for_permutation=None, exit_early_for_JSON=True
            )
            
            self.logger.info(f"Created new thread-local VV instance with prompt: {prompt}")
        
        return self.thread_local.vv, self.thread_local.llm_model
    
    def process_voucher_vision(self, ocr_text, prompt):
        """Process the OCR text with VoucherVision using a thread-local instance"""
        # Get thread-local VoucherVision instance with the correct prompt
        vv, llm_model = self.get_thread_local_vv(prompt)
        
        # Update OCR text for processing
        vv.OCR = ocr_text
        prompt_text = vv.setup_prompt()
        
        # Call the LLM to process the OCR text
        response_candidate, nt_in, nt_out, _, _, _ = llm_model.call_llm_api_GoogleGemini(
            prompt_text, json_report=None, paths=None
        )
        logger.info(f"response_candidate\n{response_candidate}")
        cost_in, cost_out, parsing_cost, rate_in, rate_out = calculate_cost(self.LLM_name_cost, os.path.join(self.dir_home, 'api_cost', 'api_cost.yaml'), nt_in, nt_out)

        return response_candidate, nt_in, nt_out, cost_in, cost_out
    
    def process_image_request(self, file, engine_options=["gemini-1.5-pro", "gemini-2.0-flash"], prompt=None):
        """Process an image from a request file"""
        # Check if we can accept this request based on throttling
        if not self.throttler.acquire():
            return {'error': 'Server is at maximum capacity. Please try again later.'}, 429
            
        try:
            # Check if the file is valid
            if file.filename == '':
                return {'error': 'No file selected'}, 400
            
            if not self.allowed_file(file.filename):
                return {'error': f'File type not allowed. Supported types: {", ".join(self.ALLOWED_EXTENSIONS)}'}, 400
            
            # Save uploaded file to a temporary location
            temp_dir = tempfile.mkdtemp()
            file_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(file_path)
            
            try:
                # Get engine options (default to gemini models if not specified)
                if engine_options is None:
                    engine_options = ["gemini-1.5-pro", "gemini-2.0-flash"]
                
                # Use default prompt if none specified
                current_prompt = prompt if prompt else self.default_prompt
                logger.info(f"Using prompt file: {current_prompt}")
                logger.info(f"file_path: {file_path}")
                logger.info(f"engine_options: {engine_options}")
                
                # Perform OCR
                ocr_info, ocr = self.perform_ocr(file_path, engine_options)
                
                # Process with VoucherVision
                vv_results, tokens_in, tokens_out, cost_in, cost_out = self.process_voucher_vision(ocr, current_prompt)
                
                # Combine results
                # results = {
                #     "ocr_info": ocr_info,
                #     "vvgo_json": vv_results,
                #     "parsing_info": {
                #         "input": tokens_in,
                #         "output": tokens_out
                #     }
                # }
                # Combine results
                if "GEMINI" in self.LLM_name_cost:
                    model_print = self.LLM_name_cost.lower().replace("_", "-").replace("gemini", "gemini", 1)

                results = OrderedDict([
                    ("filename", ""),
                    ("ocr_info", ocr_info),
                    ("parsing_info", OrderedDict([
                        ("model", model_print),
                        ("input", tokens_in),
                        ("output", tokens_out),
                        ("cost_in", cost_in),
                        ("cost_out", cost_out),
                    ])),
                    ("ocr", ocr),
                    ("formatted_json", vv_results),
                    
                ])
                
                logger.warning(results)
                return results, 200
            
            except Exception as e:
                self.logger.exception("Error processing request")
                return {'error': str(e)}, 500
            
            finally:
                # Clean up the temporary file
                try:
                    os.remove(file_path)
                    os.rmdir(temp_dir)
                except:
                    pass
        finally:
            # Release the throttling semaphore
            self.throttler.release()


# Initialize Flask app
app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)  # This enables CORS for all routes

# Create a custom encoder that preserves order
class OrderedJsonEncoder(json.JSONEncoder):
    def __init__(self, **kwargs):
        kwargs['sort_keys'] = False
        super(OrderedJsonEncoder, self).__init__(**kwargs)

# Set the encoder immediately after creating the Flask app
app.json_encoder = OrderedJsonEncoder

# Add this to your app initialization code
try:
    # Create initial admin if specified
    initial_admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    if initial_admin_email:
        create_initial_admin(initial_admin_email)
except Exception as e:
    logger.error(f"Failed to create initial admin: {str(e)}")

# Initialize processor once at startup
try:
    processor = VoucherVisionProcessor()
    app.config['processor'] = processor
    logger.info("VoucherVision processor initialized successfully")

    # Initialize email sender
    email_sender = SimpleEmailSender()
    app.config['email_sender'] = email_sender
    if email_sender.is_enabled:
        logger.info("Email sender initialized successfully")
    else:
        logger.warning("Email sender initialized but email sending is disabled due to missing configuration")
except Exception as e:
    logger.error(f"Failed to initialize application components: {str(e)}")
    raise

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
    """API endpoint to process an image with explicit CORS headers"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response
    
    # For POST requests, authenticate first
    if not authenticate_request(request):
        # Create a response with authentication error
        response = make_response(jsonify({'error': 'Unauthorized - Valid authentication required'}), 401)
        # Add CORS headers to error response too
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    # Now proceed with the actual request handling
    # Check if file is present in the request
    if 'file' not in request.files:
        response = make_response(jsonify({'error': 'No file provided'}), 400)
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    file = request.files['file']
    
    # Get engine options from request if specified
    engine_options = request.form.getlist('engines') if 'engines' in request.form else None

    # Get prompt from request if specified, otherwise None (use default)
    prompt = request.form.get('prompt') if 'prompt' in request.form else None
    
    # Process the image using the initialized processor
    results, status_code = app.config['processor'].process_image_request(file=file, engine_options=engine_options, prompt=prompt)
    
    # Create response with CORS headers
    response = make_response(json.dumps(results, cls=OrderedJsonEncoder), status_code)
    response.headers['Content-Type'] = 'application/json'
    response.headers.add('Access-Control-Allow-Origin', '*')
    
    return response

@app.route('/process-url', methods=['POST', 'OPTIONS'])
@authenticated_route
def process_image_by_url():
    """API endpoint to process an image from a URL with CORS support"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        response.headers.add('Access-Control-Max-Age', '3600')  # Cache preflight for 1 hour
        return response
    
    # Get JSON data from request
    data = request.get_json()
    
    if not data or 'image_url' not in data:
        response = make_response(jsonify({'error': 'No image URL provided'}), 400)
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    image_url = data['image_url']
    
    # Get engine options from request if specified
    engines = data.get('engines') if 'engines' in data else None

    # Get prompt from request if specified, otherwise None (use default)
    prompt = data.get('prompt')
    
    try:
        # Download the image to a temporary location
        import tempfile
        import requests
        from werkzeug.utils import secure_filename
        import os
        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        
        # Get the filename from the URL
        filename = os.path.basename(image_url.split('?')[0])  # Remove query params if any
        if not filename:
            filename = "image.jpg"
        
        # Download the image
        image_response = requests.get(image_url, stream=True)
        if image_response.status_code != 200:
            error_response = make_response(jsonify({
                'error': f'Failed to download image from URL: {image_response.status_code}'
            }), 400)
            error_response.headers.add('Access-Control-Allow-Origin', '*')
            return error_response
        
        # Save to a temporary file
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, secure_filename(filename))
        
        with open(file_path, 'wb') as f:
            for chunk in image_response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        file_obj = FileStorage(
            stream=BytesIO(file_content),
            filename=filename,
            content_type=image_response.headers.get('Content-Type', 'image/jpeg')
        )
        
        # Process the image using the processor
        results, status_code = app.config['processor'].process_image_request(
            file=file_obj, 
            engine_options=engines, 
            prompt=prompt
        )
        
        # Clean up the temporary file
        try:
            os.remove(file_path)
            os.rmdir(temp_dir)
        except:
            pass
        
        # Create response with CORS headers
        response = make_response(json.dumps(results, cls=OrderedJsonEncoder), status_code)
        response.headers['Content-Type'] = 'application/json'
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
        
    except Exception as e:
        logger.exception(f"Error processing image from URL: {e}")
        error_response = make_response(jsonify({'error': str(e)}), 500)
        error_response.headers.add('Access-Control-Allow-Origin', '*')
        return error_response

@app.route('/api-demo', methods=['GET', 'POST'])
def api_demo_page():
    """Serve the API demo HTML page with improved authentication handling"""
    # For POST requests, get token from form data and set in cookie
    if request.method == 'POST':
        # Log all form data for debugging
        logger.info(f"POST to /api-demo with form keys: {list(request.form.keys())}")
        
        # Get the auth token from the form data
        auth_token = request.form.get('auth_token')
        logger.info(f"Auth token from form: {auth_token[:10]}... (length: {len(auth_token) if auth_token else 0})")
        
        if auth_token:
            try:
                # Verify the token is valid
                decoded_token = auth.verify_id_token(auth_token)
                user_email = decoded_token.get('email', 'unknown')
                
                logger.info(f"Token verified successfully for: {user_email}")
                
                # Create response that redirects to the same page via GET
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
                return jsonify({'error': f'Authentication failed: {str(e)}'}), 401
        else:
            logger.warning("POST to /api-demo without auth_token")
            # Improved error response
            error_html = """
            <html>
            <head><title>Authentication Error</title></head>
            <body>
                <h1>Authentication Error</h1>
                <p>No authentication token was provided.</p>
                <p>Please return to the <a href="/auth-success">authentication page</a> and try again.</p>
            </body>
            </html>
            """
            return error_html, 400, {'Content-Type': 'text/html'}
    
    # For GET requests, use existing authentication mechanism
    user = authenticate_request(request)
    if not user or not user.get('email'):
        logger.warning(f"Unauthenticated GET request to /api-demo from {request.remote_addr}")
        # Redirect to login instead of showing an error
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
        logger.warning(f"Error checking for API keys: {str(e)}")
    
    # Get the base URL from the request
    base_url = request.url_root.rstrip('/')
    # Force HTTPS
    if base_url.startswith('http:'):
        base_url = 'https:' + base_url[5:]
    
    # Get Firebase configuration
    firebase_config = get_firebase_config()
    
    # Pass all necessary data to the template
    return render_template(
        'api_demo.html',
        server_url=base_url,
        user_email=user_email,
        auth_token=auth_token,
        api_key=api_key,
        has_api_keys=has_api_keys,
        api_key_firebase=firebase_config["apiKey"],
        auth_domain=firebase_config["authDomain"],
        project_id=firebase_config["projectId"],
        storage_bucket=firebase_config.get("storageBucket", ""),
        messaging_sender_id=firebase_config.get("messagingSenderId", ""),
        app_id=firebase_config["appId"]
    )

@app.route('/cors-test', methods=['GET', 'OPTIONS'])
def cors_test():
    """Simple endpoint to test CORS configuration"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        response.headers.add('Access-Control-Max-Age', '3600')
        return response
        
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

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    # Get the active request count from the processor
    active_requests = app.config['processor'].throttler.get_active_count()
    max_requests = app.config['processor'].throttler.max_concurrent
    
    return jsonify({
        'status': 'ok',
        'active_requests': active_requests,
        'max_concurrent_requests': max_requests,
        'server_load': f"{(active_requests / max_requests) * 100:.1f}%"
    }), 200

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
        
        # Create an application record in Firestore
        application_data = {
            'email': user_email,
            'organization': data.get('organization'),
            'purpose': data.get('purpose'),
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
        
        # Return success response
        return jsonify({
            'status': 'success',
            'message': 'Application submitted successfully',
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
    # For POST requests, get token from form data
    auth_token = None
    if request.method == 'POST':
        auth_token = request.form.get('auth_token')
        if auth_token:
            # Store in cookie for future requests
            response = make_response(redirect('/admin'))
            response.set_cookie('auth_token', auth_token, httponly=True, secure=True)
            return response
    
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
    # For POST requests, get token from form data and set in cookie
    if request.method == 'POST':
        # Log all form data for debugging
        logger.info(f"POST to /api-key-management with form keys: {list(request.form.keys())}")
        
        auth_token = request.form.get('auth_token')
        if auth_token:
            try:
                # Verify the token is valid
                logger.info(f"Received auth_token of length: {len(auth_token)}")
                # Log first and last few characters for debugging (don't log the whole token!)
                logger.info(f"Token prefix: {auth_token[:10]}..., suffix: ...{auth_token[-10:]}")
                
                decoded_token = auth.verify_id_token(auth_token)
                user_email = decoded_token.get('email', 'unknown')
                
                logger.info(f"Token verified successfully for: {user_email}")
                
                # Create response that redirects to the same page via GET
                response = make_response(redirect('/api-key-management'))
                
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
                logger.error(f"Error verifying token in /api-key-management POST: {str(e)}")
                return jsonify({'error': f'Authentication failed: {str(e)}'}), 401
        else:
            logger.warning("POST to /api-key-management without auth_token")
            return jsonify({'error': 'Missing authentication token'}), 400
    
    # For GET requests, use existing authentication mechanism
    user = authenticate_request(request)
    if not user or not user.get('email'):
        logger.warning(f"Unauthenticated GET request to /api-key-management from {request.remote_addr}")
        # Redirect to login instead of showing an error
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


if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)