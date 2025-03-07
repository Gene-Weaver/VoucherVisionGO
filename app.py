import os
import requests
import sys
import json
import datetime
import tempfile
import threading
from flask import Flask, request, jsonify, render_template_string, redirect
import logging
from werkzeug.utils import secure_filename
from collections import OrderedDict
from pathlib import Path
import yaml
import re
from functools import wraps

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
except:
    from vouchervision.OCR_Gemini import OCRGeminiProVision # type: ignore
    from vouchervision.vouchervision_main import load_custom_cfg # type: ignore
    from vouchervision.utils_VoucherVision import VoucherVision # type: ignore
    from vouchervision.LLM_GoogleGemini import GoogleGeminiHandler # type: ignore
    from vouchervision.model_maps import ModelMaps # type: ignore
    from vouchervision.general_utils import calculate_cost # type: ignore

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
    """Validate an API key against the Firestore database"""
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
                now = datetime.datetime.now()
                expires_at = key_data['expires_at']
                
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
    """Verify Firebase ID token in authorization header."""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    
    id_token = auth_header.split('Bearer ')[1]
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
app = Flask(__name__)

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
except Exception as e:
    logger.error(f"Failed to initialize VoucherVision processor: {str(e)}")
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
    
@app.route('/process', methods=['POST'])
@authenticated_route
def process_image():
    """API endpoint to process an image"""
    # Check if file is present in the request
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    # Get engine options from request if specified
    engine_options = request.form.getlist('engines') if 'engines' in request.form else None

    # Get prompt from request if specified, otherwise None (use default)
    prompt = request.form.get('prompt')  if 'prompt' in request.form else None
    
    # Process the image using the initialized processor
    results, status_code = app.config['processor'].process_image_request(file=file, engine_options=engine_options, prompt=prompt)
    
    # return jsonify(results), status_code
    return json.dumps(results, cls=OrderedJsonEncoder), status_code, {'Content-Type': 'application/json'}

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



@app.route('/signup', methods=['GET'])
def signup_page():
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>VoucherVision Signup</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          /* Existing styles remain the same */
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h2>Apply for an Account</h2>
            <p>Submit your application to access the VoucherVision API</p>
          </div>
          
          <div id="signup-form">
            <div class="form-group">
              <label for="email">Email</label>
              <input type="email" id="email" class="form-control" placeholder="Email address">
            </div>
            <div class="form-group">
              <label for="password">Password</label>
              <input type="password" id="password" class="form-control" placeholder="Password (at least 6 characters)">
            </div>
            <div class="form-group">
              <label for="confirm-password">Confirm Password</label>
              <input type="password" id="confirm-password" class="form-control" placeholder="Confirm password">
            </div>
            <div class="form-group">
              <label for="organization">Organization</label>
              <input type="text" id="organization" class="form-control" placeholder="Your organization or institution">
            </div>
            <div class="form-group">
              <label for="purpose">Intended Use</label>
              <textarea id="purpose" class="form-control" placeholder="Briefly describe how you plan to use the VoucherVision API" rows="3"></textarea>
            </div>
            <button id="signup-button" class="btn btn-primary">Submit Application</button>
            <div id="error-message" class="error-message"></div>
            <div id="success-message" class="success-message"></div>
            
            <div class="toggle-link">
              <p>Already have an account? <a href="/login">Sign In</a></p>
            </div>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // Set persistence to LOCAL (survives browser restarts)
          firebase.auth().setPersistence(firebase.auth.Auth.Persistence.LOCAL);
          
          // Check if user is already signed in
          firebase.auth().onAuthStateChanged(function(user) {
            if (user) {
              // Check if user is approved
              checkApprovalStatus(user);
            }
          });
          
          // Function to check user approval status
          async function checkApprovalStatus(user) {
            try {
              // Get ID token for API call
              const idToken = await user.getIdToken();
              
              // Check user status
              const response = await fetch('/check-approval-status', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (response.ok) {
                const data = await response.json();
                
                if (data.status === 'approved') {
                  // Redirect to success page if approved
                  window.location.href = '/auth-success';
                } else if (data.status === 'pending') {
                  // Redirect to pending approval page
                  window.location.href = '/pending-approval';
                } else {
                  // Rejected or unknown status
                  window.location.href = '/application-rejected';
                }
              } else {
                // Default to pending page for new users
                window.location.href = '/pending-approval';
              }
            } catch (error) {
              console.error('Error checking approval status:', error);
            }
          }
          
          // Email/Password signup
          document.getElementById('signup-button').addEventListener('click', function() {
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            const confirmPassword = document.getElementById('confirm-password').value;
            const organization = document.getElementById('organization').value;
            const purpose = document.getElementById('purpose').value;
            const errorElement = document.getElementById('error-message');
            const successElement = document.getElementById('success-message');
            
            errorElement.style.display = 'none';
            successElement.style.display = 'none';
            
            if (!email || !password || !confirmPassword || !organization || !purpose) {
              errorElement.textContent = 'Please fill in all fields';
              errorElement.style.display = 'block';
              return;
            }
            
            if (password !== confirmPassword) {
              errorElement.textContent = 'Passwords do not match';
              errorElement.style.display = 'block';
              return;
            }
            
            if (password.length < 6) {
              errorElement.textContent = 'Password must be at least 6 characters';
              errorElement.style.display = 'block';
              return;
            }
            
            // Create user account
            firebase.auth().createUserWithEmailAndPassword(email, password)
              .then((userCredential) => {
                const user = userCredential.user;
                
                // Submit additional registration info
                submitRegistrationInfo(user, organization, purpose);
              })
              .catch((error) => {
                errorElement.textContent = error.message;
                errorElement.style.display = 'block';
              });
          });
          
          // Submit additional registration info
          async function submitRegistrationInfo(user, organization, purpose) {
            const errorElement = document.getElementById('error-message');
            const successElement = document.getElementById('success-message');
            
            try {
              // Get ID token
              const idToken = await user.getIdToken();
              
              // Submit application data
              const response = await fetch('/submit-application', {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`,
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  organization,
                  purpose,
                  email: user.email
                })
              });
              
              if (response.ok) {
                successElement.textContent = 'Your application has been submitted. You will be notified when it is approved.';
                successElement.style.display = 'block';
                
                // Redirect to pending page after a short delay
                setTimeout(() => {
                  window.location.href = '/pending-approval';
                }, 3000);
              } else {
                const data = await response.json();
                throw new Error(data.error || 'Failed to submit application');
              }
            } catch (error) {
              console.error('Error submitting application:', error);
              errorElement.textContent = error.message;
              errorElement.style.display = 'block';
            }
          }
        </script>
      </body>
    </html>
    """, 
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"])

@app.route('/pending-approval', methods=['GET'])
def pending_approval_page():
    firebase_config = get_firebase_config()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>Application Pending</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 0; 
            background-color: #f5f5f5; 
          }
          .container { 
            max-width: 600px; 
            margin: 100px auto; 
            padding: 30px; 
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
          }
          .status-icon {
            font-size: 64px;
            color: #ffc107;
            margin-bottom: 20px;
          }
          h1 {
            color: #333;
          }
          p {
            font-size: 16px;
            color: #666;
            margin-bottom: 20px;
          }
          .btn-logout {
            background-color: #f8f9fa;
            color: #333;
            border: 1px solid #ddd;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
          }
          .btn-logout:hover {
            background-color: #e9ecef;
          }
          .user-info {
            margin-top: 30px;
            font-size: 14px;
            color: #888;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="status-icon">⏳</div>
          <h1>Application Pending</h1>
          <p>Your application to access the VoucherVision API is currently being reviewed.</p>
          <p>You will receive a notification when your application has been approved.</p>
          
          <div class="user-info">
            <p>Signed in as: <span id="user-email">Loading...</span></p>
            <button id="logout-btn" class="btn-logout">Sign Out</button>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // Check if user is signed in
          firebase.auth().onAuthStateChanged(function(user) {
            if (user) {
              // Display user email
              document.getElementById('user-email').textContent = user.email;
              
              // Check approval status periodically
              checkApprovalStatus(user);
              setInterval(() => checkApprovalStatus(user), 60000); // Check every minute
            } else {
              // Not signed in, redirect to login
              window.location.href = '/login';
            }
          });
          
          // Function to check approval status
          async function checkApprovalStatus(user) {
            try {
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Check status
              const response = await fetch('/check-approval-status', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (response.ok) {
                const data = await response.json();
                
                if (data.status === 'approved') {
                  // Redirect to success page if approved
                  window.location.href = '/auth-success';
                } else if (data.status === 'rejected') {
                  // Redirect to rejected page
                  window.location.href = '/application-rejected';
                }
                // If still pending, stay on this page
              }
            } catch (error) {
              console.error('Error checking approval status:', error);
            }
          }
          
          // Logout button
          document.getElementById('logout-btn').addEventListener('click', function() {
            firebase.auth().signOut().then(function() {
              window.location.href = '/login';
            }).catch(function(error) {
              console.error('Error signing out:', error);
            });
          });
        </script>
      </body>
    </html>
    """,
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"])

@app.route('/application-rejected', methods=['GET'])
def application_rejected_page():
    firebase_config = get_firebase_config()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>Application Rejected</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 0; 
            background-color: #f5f5f5; 
          }
          .container { 
            max-width: 600px; 
            margin: 100px auto; 
            padding: 30px; 
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
          }
          .status-icon {
            font-size: 64px;
            color: #dc3545;
            margin-bottom: 20px;
          }
          h1 {
            color: #333;
          }
          p {
            font-size: 16px;
            color: #666;
            margin-bottom: 20px;
          }
          .btn-logout {
            background-color: #f8f9fa;
            color: #333;
            border: 1px solid #ddd;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            margin-right: 10px;
          }
          .btn-logout:hover {
            background-color: #e9ecef;
          }
          .user-info {
            margin-top: 30px;
            font-size: 14px;
            color: #888;
          }
          .rejection-reason {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            text-align: left;
          }
          .contact-info {
            margin-top: 20px;
            font-size: 14px;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="status-icon">❌</div>
          <h1>Application Denied</h1>
          <p>Unfortunately, your application to access the VoucherVision API has been denied.</p>
          
          <div class="rejection-reason">
            <strong>Reason:</strong>
            <p id="rejection-reason">Loading rejection reason...</p>
          </div>
          
          <div class="contact-info">
            <p>If you believe this is an error or would like to provide additional information, please contact our support team.</p>
          </div>
          
          <div class="user-info">
            <p>Signed in as: <span id="user-email">Loading...</span></p>
            <button id="logout-btn" class="btn-logout">Sign Out</button>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // Check if user is signed in
          firebase.auth().onAuthStateChanged(function(user) {
            if (user) {
              // Display user email
              document.getElementById('user-email').textContent = user.email;
              
              // Get rejection reason
              getRejectionReason(user);
            } else {
              // Not signed in, redirect to login
              window.location.href = '/login';
            }
          });
          
          // Function to get rejection reason
          async function getRejectionReason(user) {
            try {
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Check status and get rejection reason
              const response = await fetch('/check-approval-status', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (response.ok) {
                const data = await response.json();
                
                if (data.status === 'rejected') {
                  document.getElementById('rejection-reason').textContent = 
                    data.reason || 'No specific reason provided.';
                } else if (data.status === 'approved') {
                  // Redirect to success page if actually approved
                  window.location.href = '/auth-success';
                } else if (data.status === 'pending') {
                  // Redirect to pending page if actually pending
                  window.location.href = '/pending-approval';
                }
              }
            } catch (error) {
              console.error('Error getting rejection reason:', error);
              document.getElementById('rejection-reason').textContent = 
                'Could not retrieve rejection reason. Please contact support.';
            }
          }
          
          // Logout button
          document.getElementById('logout-btn').addEventListener('click', function() {
            firebase.auth().signOut().then(function() {
              window.location.href = '/login';
            }).catch(function(error) {
              console.error('Error signing out:', error);
            });
          });
        </script>
      </body>
    </html>
    """,
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"])



@app.route('/login', methods=['GET'])
def login_page():
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>VoucherVision Login</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          /* Styles remain the same */
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h2>VoucherVision API</h2>
            <p>Sign in to access the API</p>
          </div>
          
          <div id="login-form">
            <div class="form-group">
              <label for="email">Email</label>
              <input type="email" id="email" class="form-control" placeholder="Email address">
            </div>
            <div class="form-group">
              <label for="password">Password</label>
              <input type="password" id="password" class="form-control" placeholder="Password">
            </div>
            <div class="form-check mb-3">
              <input class="form-check-input" type="checkbox" id="remember-me" checked>
              <label class="form-check-label" for="remember-me">
                Remember me
              </label>
            </div>
            <button id="login-button" class="btn btn-primary">Sign In</button>
            <div id="error-message" class="error-message"></div>
            <div id="success-message" class="success-message"></div>
            
            <div class="toggle-link">
              <p>Don't have an account? <a href="/signup">Apply for Access</a></p>
              <p><a href="#" id="forgot-password">Forgot Password?</a></p>
            </div>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // Set persistence based on remember me checkbox
          // Default to LOCAL persistence (survives browser restarts)
          firebase.auth().setPersistence(firebase.auth.Auth.Persistence.LOCAL);
          
          // Check if user is already signed in
          firebase.auth().onAuthStateChanged(function(user) {
            if (user) {
              // Check the user's approval status
              checkApprovalStatus(user);
            }
          });
          
          // Function to check user approval status
          async function checkApprovalStatus(user) {
            try {
              // Get ID token for API call
              const idToken = await user.getIdToken();
              
              // Check user status
              const response = await fetch('/check-approval-status', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (response.ok) {
                const data = await response.json();
                
                if (data.status === 'approved') {
                  // Store user info
                  localStorage.setItem('auth_user_email', user.email);
                  
                  // Get the latest ID token and save refresh token
                  user.getIdToken(true).then(function(idToken) {
                    localStorage.setItem('auth_id_token', idToken);
                    
                    // Also store user refresh token for later use
                    if (user.refreshToken) {
                      localStorage.setItem('auth_refresh_token', user.refreshToken);
                    }
                    
                    // Redirect to success page
                    window.location.href = '/auth-success';
                  });
                } else if (data.status === 'pending') {
                  // Redirect to pending approval page
                  window.location.href = '/pending-approval';
                } else if (data.status === 'rejected') {
                  // Redirect to rejected page
                  window.location.href = '/application-rejected';
                }
              }
            } catch (error) {
              console.error('Error checking approval status:', error);
            }
          }
          
          // Email/Password login
          document.getElementById('login-button').addEventListener('click', function() {
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            const rememberMe = document.getElementById('remember-me').checked;
            const errorElement = document.getElementById('error-message');
            const successElement = document.getElementById('success-message');
            
            errorElement.style.display = 'none';
            successElement.style.display = 'none';
            
            if (!email || !password) {
              errorElement.textContent = 'Please enter both email and password';
              errorElement.style.display = 'block';
              return;
            }
            
            // Set persistence type based on remember me
            const persistenceType = rememberMe 
              ? firebase.auth.Auth.Persistence.LOCAL  // Survives browser restart
              : firebase.auth.Auth.Persistence.SESSION; // Until tab is closed
            
            firebase.auth().setPersistence(persistenceType)
              .then(() => {
                return firebase.auth().signInWithEmailAndPassword(email, password);
              })
              .then((userCredential) => {
                // Success - will redirect via checkApprovalStatus
                successElement.textContent = 'Login successful, checking account status...';
                successElement.style.display = 'block';
                
                // Check approval status
                checkApprovalStatus(userCredential.user);
              })
              .catch((error) => {
                // Show error message
                errorElement.textContent = error.message;
                errorElement.style.display = 'block';
              });
          });
          
          // Forgot password - remains the same
        </script>
      </body>
    </html>
    """, 
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"])

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

@app.route('/auth-success', methods=['GET'])
def auth_success():
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>Authentication Successful</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 0; 
            background-color: #f5f5f5; 
          }
          .container { 
            max-width: 800px; 
            margin: 50px auto; 
            padding: 30px; 
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
          }
          .header { 
            text-align: center;
            margin-bottom: 30px;
          }
          h1 {
            color: #4285f4;
            margin-bottom: 20px;
          }
          .token-container {
            background-color: #f8f9fa;
            border-radius: 4px;
            padding: 20px;
            margin-bottom: 20px;
          }
          pre {
            white-space: pre-wrap;
            word-break: break-all;
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            font-size: 14px;
            max-height: 200px;
            overflow-y: auto;
          }
          .expiry-info {
            color: #6c757d;
            font-size: 14px;
            margin-top: 10px;
          }
          .copy-btn {
            background-color: #4285f4;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
          }
          .copy-btn:hover {
            background-color: #3367d6;
          }
          .success-message {
            display: none;
            color: #28a745;
            margin-top: 5px;
            font-size: 14px;
          }
          .error-message {
            display: none;
            color: #dc3545;
            margin-top: 5px;
            font-size: 14px;
          }
          .user-info {
            margin-bottom: 20px;
            padding: 15px;
            background-color: #e9f5ff;
            border-radius: 4px;
          }
          .btn-logout {
            background-color: #f44336;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
          }
          .btn-logout:hover {
            background-color: #d32f2f;
          }
          .btn-admin {
            background-color: #4285f4;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            margin-left: 10px;
          }
          .btn-admin:hover {
            background-color: #3367d6;
          }
          .usage-instructions {
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 4px;
            margin-top: 30px;
          }
          code {
            background-color: #e9ecef;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 14px;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h1>Authentication Successful</h1>
            <p>You are now authenticated to use the VoucherVision API.</p>
          </div>
          
          <div class="user-info">
            <p><strong>Signed in as:</strong> <span id="user-email">Loading...</span></p>
            <div>
              <button id="logout-btn" class="btn-logout">Sign Out</button>
            </div>
          </div>
          
          <div class="token-container">
            <h3>Your API Authentication Token</h3>
            <p>Use this token in your API requests by setting the Authorization header to: <code>Bearer YOUR_TOKEN</code></p>
            <pre id="token">Loading your token...</pre>
            <div class="expiry-info">Token valid for 60 minutes. The token will auto-refresh while this page is open.</div>
            <div class="error-message" id="error-message"></div>
            <div class="success-message" id="success-message"></div>
            <button id="copy-token-btn" class="copy-btn">Copy Token</button>
            <button id="refresh-token-btn" class="copy-btn ms-2">Refresh Token</button>
          </div>
          
          <div class="usage-instructions">
            <h3>Using the API</h3>
            <p>To use this token with the VoucherVision API:</p>
            <ol>
              <li>Add an Authorization header to your requests: <code>Authorization: Bearer YOUR_TOKEN</code></li>
              <li>Make requests to the API endpoints (e.g., <code>POST /process</code>)</li>
            </ol>
            <h4>Example with cURL:</h4>
            <pre>curl -X POST "{{ server_url }}/process" \\
     -H "Authorization: Bearer YOUR_TOKEN" \\
     -F "file=@your_image.jpg"</pre>
            
            <h4>Example with Python client:</h4>
            <pre>python client.py --server {{ server_url }} --auth-token YOUR_TOKEN --image "path/to/image.jpg" --output-dir "./results"</pre>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // Token refresh interval (45 minutes = 2,700,000 milliseconds)
          // We'll refresh before the 60-minute expiration
          const TOKEN_REFRESH_INTERVAL = 2700000;
          let tokenRefreshTimer;
          
          // Initialize the page
          function initPage() {
            const tokenElement = document.getElementById('token');
            const userEmailElement = document.getElementById('user-email');
            const errorElement = document.getElementById('error-message');
            const successElement = document.getElementById('success-message');
            
            // Check if user is authenticated
            firebase.auth().onAuthStateChanged(function(user) {
              if (user) {
                // User is signed in, display their email
                userEmailElement.textContent = user.email;
                
                // Check if user is approved and/or an admin
                checkUserApproval(user)
                  .then(isApproved => {
                    if (isApproved) {
                      // Check if user is admin and show admin button if they are
                      checkIsAdmin(user)
                        .then(isAdmin => {
                          if (isAdmin) {
                            // Add an admin dashboard link
                            const adminButton = document.createElement('button');
                            adminButton.className = 'btn-admin';
                            adminButton.textContent = 'Admin Dashboard';
                            adminButton.onclick = function() {
                              window.location.href = '/admin';
                            };
                            document.querySelector('.user-info div').appendChild(adminButton);
                          }
                        });
                      
                      // Continue with token display
                      updateTokenDisplay(user);
                      setupTokenRefresh(user);
                    } else {
                      // Not approved, redirect to pending page
                      window.location.href = '/pending-approval';
                    }
                  });
              } else {
                // Not signed in, redirect to login page
                window.location.href = '/login';
              }
            });
            
            // Copy token button
            document.getElementById('copy-token-btn').addEventListener('click', function() {
              const token = tokenElement.textContent;
              navigator.clipboard.writeText(token)
                .then(() => {
                  successElement.textContent = 'Token copied to clipboard!';
                  successElement.style.display = 'block';
                  errorElement.style.display = 'none';
                  setTimeout(() => {
                    successElement.style.display = 'none';
                  }, 3000);
                })
                .catch(err => {
                  errorElement.textContent = 'Failed to copy: ' + err;
                  errorElement.style.display = 'block';
                  successElement.style.display = 'none';
                });
            });
            
            // Refresh token button
            document.getElementById('refresh-token-btn').addEventListener('click', function() {
              const currentUser = firebase.auth().currentUser;
              
              if (currentUser) {
                refreshToken(currentUser);
              } else {
                errorElement.textContent = 'Not signed in. Please log in again.';
                errorElement.style.display = 'block';
                successElement.style.display = 'none';
              }
            });
            
            // Logout button
            document.getElementById('logout-btn').addEventListener('click', function() {
              firebase.auth().signOut().then(function() {
                // Clear localStorage items
                localStorage.removeItem('auth_id_token');
                localStorage.removeItem('auth_refresh_token');
                localStorage.removeItem('auth_user_email');
                
                // Clear any refresh timers
                clearTimeout(tokenRefreshTimer);
                
                // Redirect to login page
                window.location.href = '/login';
              }).catch(function(error) {
                errorElement.textContent = 'Error signing out: ' + error.message;
                errorElement.style.display = 'block';
              });
            });
          }
          
          // Update token display
          function updateTokenDisplay(user) {
            const tokenElement = document.getElementById('token');
            const errorElement = document.getElementById('error-message');
            
            user.getIdToken(true).then(function(idToken) {
              // Store the token in localStorage for persistence
              localStorage.setItem('auth_id_token', idToken);
              
              // Display the token
              tokenElement.textContent = idToken;
            }).catch(function(error) {
              errorElement.textContent = 'Error getting token: ' + error.message;
              errorElement.style.display = 'block';
              
              // Try to use cached token if available
              const cachedToken = localStorage.getItem('auth_id_token');
              if (cachedToken) {
                tokenElement.textContent = cachedToken;
              }
            });
          }
          
          // Set up automatic token refresh
          function setupTokenRefresh(user) {
            // Clear any existing timer
            clearTimeout(tokenRefreshTimer);
            
            // Setup new timer to refresh the token
            tokenRefreshTimer = setTimeout(() => {
              refreshToken(user);
            }, TOKEN_REFRESH_INTERVAL);
          }
          
          // Refresh the token
          function refreshToken(user) {
            const tokenElement = document.getElementById('token');
            const errorElement = document.getElementById('error-message');
            const successElement = document.getElementById('success-message');
            
            errorElement.style.display = 'none';
            successElement.style.display = 'none';
            
            // Force token refresh
            user.getIdToken(true).then(function(idToken) {
              // Update the token in localStorage
              localStorage.setItem('auth_id_token', idToken);
              
              // Update displayed token
              tokenElement.textContent = idToken;
              
              // Show success message
              successElement.textContent = 'Token refreshed successfully';
              successElement.style.display = 'block';
              
              // Set up the next refresh
              setupTokenRefresh(user);
            }).catch(function(error) {
              errorElement.textContent = 'Error refreshing token: ' + error.message;
              errorElement.style.display = 'block';
              
              // If error, try again in 1 minute
              tokenRefreshTimer = setTimeout(() => {
                const currentUser = firebase.auth().currentUser;
                if (currentUser) {
                  refreshToken(currentUser);
                }
              }, 60000);
            });
          }
          
          // New function to check approval status
          async function checkUserApproval(user) {
            try {
              const idToken = await user.getIdToken();
              const response = await fetch('/check-approval-status', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (response.ok) {
                const data = await response.json();
                if (data.status === 'approved') {
                  return true;
                } else if (data.status === 'pending') {
                  window.location.href = '/pending-approval';
                  return false;
                } else if (data.status === 'rejected') {
                  window.location.href = '/application-rejected';
                  return false;
                }
              }
              return false;
            } catch (error) {
              console.error('Error checking approval status:', error);
              return false;
            }
          }
          
          // New function to check if user is admin
          async function checkIsAdmin(user) {
            try {
              const idToken = await user.getIdToken();
              const response = await fetch('/check-admin-status', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (response.ok) {
                const data = await response.json();
                return data.is_admin === true;
              }
              return false;
            } catch (error) {
              console.error('Error checking admin status:', error);
              return false;
            }
          }
          
          // Start the page initialization when the DOM is ready
          document.addEventListener('DOMContentLoaded', initPage);
        </script>
      </body>
    </html>
    """,
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"],
    server_url=request.url_root.rstrip('/'))  # Add server URL for examples

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
    
@app.route('/admin', methods=['GET'])
@authenticated_route
def admin_dashboard():
    """Admin dashboard for managing user applications"""
    # Get the authenticated user from the token
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
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>VoucherVision Admin Dashboard</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 0; 
            background-color: #f5f5f5; 
          }
          .container { 
            max-width: 1200px; 
            margin: 30px auto; 
            padding: 0;
          }
          .header { 
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding: 15px 20px;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
          }
          .header h2 {
            margin: 0;
            color: #333;
          }
          .user-info {
            display: flex;
            align-items: center;
          }
          .user-email {
            margin-right: 15px;
            font-size: 14px;
          }
          .btn-primary, .btn-success, .btn-danger, .btn-secondary {
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
          }
          .btn-primary {
            background-color: #4285f4;
            color: white;
          }
          .btn-primary:hover {
            background-color: #3367d6;
          }
          .btn-success {
            background-color: #34a853;
            color: white;
          }
          .btn-success:hover {
            background-color: #2d8644;
          }
          .btn-danger {
            background-color: #ea4335;
            color: white;
          }
          .btn-danger:hover {
            background-color: #d33426;
          }
          .btn-secondary {
            background-color: #f8f9fa;
            color: #333;
            border: 1px solid #ddd;
          }
          .btn-secondary:hover {
            background-color: #e9ecef;
          }
          .tab-container {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
          }
          .tab-buttons {
            display: flex;
            margin-bottom: 20px;
            border-bottom: 1px solid #ddd;
          }
          .tab-button {
            padding: 10px 20px;
            background: none;
            border: none;
            cursor: pointer;
            font-size: 16px;
            color: #666;
            border-bottom: 3px solid transparent;
          }
          .tab-button.active {
            color: #4285f4;
            border-bottom: 3px solid #4285f4;
            font-weight: bold;
          }
          .tab-content {
            display: none;
          }
          .tab-content.active {
            display: block;
          }
          table {
            width: 100%;
            border-collapse: collapse;
          }
          table th, table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
          }
          table th {
            background-color: #f8f9fa;
            color: #333;
            font-weight: bold;
          }
          .badge {
            padding: 6px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: normal;
            color: white;
          }
          .badge-pending {
            background-color: #f9a825;
          }
          .badge-approved {
            background-color: #34a853;
          }
          .badge-rejected {
            background-color: #ea4335;
          }
          .modal {
            display: none;
            position: fixed;
            z-index: 100;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
          }
          .modal-content {
            background-color: white;
            margin: 10% auto;
            padding: 30px;
            width: 50%;
            max-width: 600px;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
          }
          .close {
            float: right;
            font-size: 24px;
            font-weight: bold;
            cursor: pointer;
            color: #aaa;
          }
          .close:hover {
            color: #333;
          }
          .form-group {
            margin-bottom: 20px;
          }
          .alert {
            padding: 12px 15px;
            margin-bottom: 20px;
            border-radius: 4px;
          }
          .alert-success {
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
          }
          .alert-danger {
            background-color: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
          }
          .user-details {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
          }
          .action-buttons {
            display: flex;
            gap: 10px;
          }
          .search-container {
            margin-bottom: 20px;
          }
          .search-input {
            padding: 8px 12px;
            width: 300px;
            border: 1px solid #ddd;
            border-radius: 4px;
          }
          .pagination {
            display: flex;
            justify-content: center;
            margin-top: 20px;
          }
          .pagination button {
            padding: 5px 10px;
            margin: 0 5px;
            border: 1px solid #ddd;
            background-color: white;
            cursor: pointer;
            border-radius: 4px;
          }
          .pagination button.active {
            background-color: #4285f4;
            color: white;
            border-color: #4285f4;
          }
          .loading {
            text-align: center;
            padding: 20px;
            font-style: italic;
            color: #666;
          }
          .status-filter {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
          }
          .filter-btn {
            padding: 5px 10px;
            border: 1px solid #ddd;
            background-color: white;
            cursor: pointer;
            border-radius: 4px;
          }
          .filter-btn.active {
            background-color: #4285f4;
            color: white;
            border-color: #4285f4;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h2>VoucherVision Admin Dashboard</h2>
            <div class="user-info">
              <span class="user-email">Admin: <strong id="user-email">Loading...</strong></span>
              <button id="logout-btn" class="btn-secondary">Sign Out</button>
            </div>
          </div>
          
          <div class="tab-container">
            <div class="tab-buttons">
              <button class="tab-button active" data-tab="user-applications">User Applications</button>
              <button class="tab-button" data-tab="api-keys">API Keys</button>
              <button class="tab-button" data-tab="admins">Manage Admins</button>
            </div>
            
            <div id="user-applications" class="tab-content active">
              <h3>User Applications</h3>
              
              <div class="status-filter">
                <button class="filter-btn active" data-status="all">All</button>
                <button class="filter-btn" data-status="pending">Pending</button>
                <button class="filter-btn" data-status="approved">Approved</button>
                <button class="filter-btn" data-status="rejected">Rejected</button>
              </div>
              
              <div class="search-container">
                <input type="text" class="search-input" id="application-search" placeholder="Search by email or organization...">
              </div>
              
              <div id="applications-table-container">
                <div id="applications-loading" class="loading">Loading applications...</div>
                <table id="applications-table" style="display: none;">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Organization</th>
                      <th>Purpose</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody id="applications-list">
                    <!-- Applications will be listed here -->
                  </tbody>
                </table>
              </div>
              
              <div id="applications-pagination" class="pagination">
                <!-- Pagination buttons will be generated here -->
              </div>
            </div>
            
            <div id="api-keys" class="tab-content">
              <h3>API Key Management</h3>
              
              <div class="search-container">
                <input type="text" class="search-input" id="api-key-search" placeholder="Search by email or key name...">
              </div>
              
              <div id="api-keys-table-container">
                <div id="api-keys-loading" class="loading">Loading API keys...</div>
                <table id="api-keys-table" style="display: none;">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Key Name</th>
                      <th>Created</th>
                      <th>Expires</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody id="api-keys-list">
                    <!-- API keys will be listed here -->
                  </tbody>
                </table>
              </div>
              
              <div id="api-keys-pagination" class="pagination">
                <!-- Pagination buttons will be generated here -->
              </div>
            </div>
            
            <div id="admins" class="tab-content">
              <h3>Admin Management</h3>
              
              <div class="mb-4">
                <button id="add-admin-btn" class="btn-primary">Add New Admin</button>
              </div>
              
              <div id="admins-table-container">
                <div id="admins-loading" class="loading">Loading admins...</div>
                <table id="admins-table" style="display: none;">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Added By</th>
                      <th>Added Date</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody id="admins-list">
                    <!-- Admins will be listed here -->
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Application Details Modal -->
        <div id="application-modal" class="modal">
          <div class="modal-content">
            <span class="close">&times;</span>
            <h3>Application Details</h3>
            
            <div id="application-details" class="user-details">
              <!-- Application details will be displayed here -->
            </div>
            
            <div id="application-actions" class="action-buttons">
              <button id="approve-btn" class="btn-success">Approve</button>
              <button id="reject-btn" class="btn-danger">Reject</button>
            </div>
            
            <div id="rejection-form" style="display: none;" class="mt-3">
              <div class="form-group">
                <label for="rejection-reason">Rejection Reason</label>
                <textarea id="rejection-reason" class="form-control" rows="3" placeholder="Provide a reason for rejecting this application"></textarea>
              </div>
              <button id="confirm-reject-btn" class="btn-danger">Confirm Rejection</button>
              <button id="cancel-reject-btn" class="btn-secondary">Cancel</button>
            </div>
            
            <div id="application-status-message" class="mt-3"></div>
          </div>
        </div>
        
        <!-- Add Admin Modal -->
        <div id="add-admin-modal" class="modal">
          <div class="modal-content">
            <span class="close">&times;</span>
            <h3>Add New Admin</h3>
            
            <div class="form-group">
              <label for="admin-email">Email Address</label>
              <input type="email" id="admin-email" class="form-control" placeholder="Enter email address">
            </div>
            
            <div id="add-admin-error" class="alert alert-danger" style="display: none;"></div>
            <div id="add-admin-success" class="alert alert-success" style="display: none;"></div>
            
            <button id="confirm-add-admin-btn" class="btn-primary">Add as Admin</button>
          </div>
        </div>
        
        <!-- Revoke API Key Modal -->
        <div id="revoke-key-modal" class="modal">
          <div class="modal-content">
            <span class="close">&times;</span>
            <h3>Revoke API Key</h3>
            
            <div class="user-details">
              <p><strong>User:</strong> <span id="key-user-email"></span></p>
              <p><strong>Key Name:</strong> <span id="key-name"></span></p>
              <p><strong>Created:</strong> <span id="key-created"></span></p>
            </div>
            
            <div class="alert alert-danger">
              <p><strong>Warning:</strong> Revoking an API key is permanent and cannot be undone. The user will no longer be able to access the API with this key.</p>
            </div>
            
            <div class="form-group">
              <label for="revocation-reason">Reason (Optional)</label>
              <textarea id="revocation-reason" class="form-control" rows="2" placeholder="Reason for revoking this key"></textarea>
            </div>
            
            <div id="revoke-key-error" class="alert alert-danger" style="display: none;"></div>
            <div id="revoke-key-success" class="alert alert-success" style="display: none;"></div>
            
            <button id="confirm-revoke-key-btn" class="btn-danger">Revoke API Key</button>
            <button id="cancel-revoke-key-btn" class="btn-secondary">Cancel</button>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // Variables to store current application or API key being viewed
          let currentApplicationEmail = null;
          let currentKeyId = null;
          
          // Initialize pagination variables
          const itemsPerPage = 10;
          let currentApplicationsPage = 1;
          let currentApiKeysPage = 1;
          let filteredApplications = [];
          let filteredApiKeys = [];
          let allApplications = [];
          let allApiKeys = [];
          let currentStatusFilter = 'all';
          
          // DOM elements
          const tabButtons = document.querySelectorAll('.tab-button');
          const tabContents = document.querySelectorAll('.tab-content');
          const filterButtons = document.querySelectorAll('.filter-btn');
          const applicationModal = document.getElementById('application-modal');
          const addAdminModal = document.getElementById('add-admin-modal');
          const revokeKeyModal = document.getElementById('revoke-key-modal');
          const closeButtons = document.querySelectorAll('.close');
          
          // Initialize the page
          function initPage() {
            // Check if user is authenticated and is an admin
            firebase.auth().onAuthStateChanged(function(user) {
              if (user) {
                // Display user email
                document.getElementById('user-email').textContent = user.email;
                
                // Load data for active tab
                const activeTab = document.querySelector('.tab-button.active').dataset.tab;
                loadDataForTab(activeTab, user);
                
                // Set up search functionality
                setupSearch();
              } else {
                // Not signed in, redirect to login
                window.location.href = '/login';
              }
            });
            
            // Tab switching
            tabButtons.forEach(button => {
              button.addEventListener('click', () => {
                // Remove active class from all tabs
                tabButtons.forEach(btn => btn.classList.remove('active'));
                tabContents.forEach(content => content.classList.remove('active'));
                
                // Add active class to the clicked tab
                button.classList.add('active');
                const tabId = button.dataset.tab;
                document.getElementById(tabId).classList.add('active');
                
                // Load data for the selected tab
                const user = firebase.auth().currentUser;
                if (user) {
                  loadDataForTab(tabId, user);
                }
              });
            });
            
            // Status filter
            filterButtons.forEach(button => {
              button.addEventListener('click', () => {
                // Remove active class from all filter buttons
                filterButtons.forEach(btn => btn.classList.remove('active'));
                
                // Add active class to the clicked button
                button.classList.add('active');
                
                // Apply filter
                currentStatusFilter = button.dataset.status;
                applyFiltersToApplications();
              });
            });
            
            // Application modal
            document.getElementById('approve-btn').addEventListener('click', approveApplication);
            document.getElementById('reject-btn').addEventListener('click', () => {
              document.getElementById('application-actions').style.display = 'none';
              document.getElementById('rejection-form').style.display = 'block';
            });
            document.getElementById('confirm-reject-btn').addEventListener('click', rejectApplication);
            document.getElementById('cancel-reject-btn').addEventListener('click', () => {
              document.getElementById('rejection-form').style.display = 'none';
              document.getElementById('application-actions').style.display = 'flex';
            });
            
            // Add admin modal
            document.getElementById('add-admin-btn').addEventListener('click', () => {
              addAdminModal.style.display = 'block';
              document.getElementById('admin-email').value = '';
              document.getElementById('add-admin-error').style.display = 'none';
              document.getElementById('add-admin-success').style.display = 'none';
            });
            document.getElementById('confirm-add-admin-btn').addEventListener('click', addAdmin);
            
            // Revoke API key modal
            document.getElementById('confirm-revoke-key-btn').addEventListener('click', revokeApiKey);
            document.getElementById('cancel-revoke-key-btn').addEventListener('click', () => {
              revokeKeyModal.style.display = 'none';
            });
            
            // Close modals
            closeButtons.forEach(btn => {
              btn.addEventListener('click', () => {
                applicationModal.style.display = 'none';
                addAdminModal.style.display = 'none';
                revokeKeyModal.style.display = 'none';
              });
            });
            
            // Close modals when clicking outside
            window.addEventListener('click', (event) => {
              if (event.target === applicationModal) {
                applicationModal.style.display = 'none';
              }
              if (event.target === addAdminModal) {
                addAdminModal.style.display = 'none';
              }
              if (event.target === revokeKeyModal) {
                revokeKeyModal.style.display = 'none';
              }
            });
            
            // Logout button
            document.getElementById('logout-btn').addEventListener('click', () => {
              firebase.auth().signOut().then(() => {
                window.location.href = '/login';
              });
            });
          }
          
          // Load data based on the selected tab
          function loadDataForTab(tabId, user) {
            switch (tabId) {
              case 'user-applications':
                loadApplications(user);
                break;
              case 'api-keys':
                loadApiKeys(user);
                break;
              case 'admins':
                loadAdmins(user);
                break;
            }
          }
          
          // Setup search functionality
          function setupSearch() {
            const applicationSearch = document.getElementById('application-search');
            applicationSearch.addEventListener('input', () => {
              applyFiltersToApplications();
            });
            
            const apiKeySearch = document.getElementById('api-key-search');
            apiKeySearch.addEventListener('input', () => {
              const searchTerm = apiKeySearch.value.toLowerCase();
              filteredApiKeys = allApiKeys.filter(key => {
                return key.owner.toLowerCase().includes(searchTerm) || 
                       (key.name && key.name.toLowerCase().includes(searchTerm));
              });
              renderApiKeysPage(1);
            });
          }
          
          // Apply filters to applications
          function applyFiltersToApplications() {
            const searchTerm = document.getElementById('application-search').value.toLowerCase();
            
            filteredApplications = allApplications.filter(app => {
              // Status filter
              if (currentStatusFilter !== 'all' && app.status !== currentStatusFilter) {
                return false;
              }
              
              // Search term filter
              if (searchTerm) {
                return app.email.toLowerCase().includes(searchTerm) || 
                       (app.organization && app.organization.toLowerCase().includes(searchTerm));
              }
              
              return true;
            });
            
            renderApplicationsPage(1);
          }
          
          // Load user applications
          async function loadApplications(user) {
            try {
              // Show loading indicator
              document.getElementById('applications-loading').style.display = 'block';
              document.getElementById('applications-table').style.display = 'none';
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Fetch applications
              const response = await fetch('/admin/applications', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Store all applications
                allApplications = data.applications;
                
                // Apply initial filters
                applyFiltersToApplications();
              } else {
                throw new Error(data.error || 'Failed to load applications');
              }
            } catch (error) {
              console.error('Error loading applications:', error);
              document.getElementById('applications-loading').textContent = 
                'Error loading applications: ' + error.message;
            }
          }
          
          // Render applications page
          function renderApplicationsPage(page) {
            // Update current page
            currentApplicationsPage = page;
            
            // Calculate pagination
            const startIndex = (page - 1) * itemsPerPage;
            const endIndex = startIndex + itemsPerPage;
            const pageApplications = filteredApplications.slice(startIndex, endIndex);
            
            // Hide loading, show table
            document.getElementById('applications-loading').style.display = 'none';
            document.getElementById('applications-table').style.display = 'table';
            
            // Populate table
            const applicationsListElem = document.getElementById('applications-list');
            applicationsListElem.innerHTML = '';
            
            pageApplications.forEach(app => {
              // Format dates
              const createdDate = app.created_at ? new Date(app.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
              
              // Status badge
              let statusBadge = '';
              switch (app.status) {
                case 'pending':
                  statusBadge = '<span class="badge badge-pending">Pending</span>';
                  break;
                case 'approved':
                  statusBadge = '<span class="badge badge-approved">Approved</span>';
                  break;
                case 'rejected':
                  statusBadge = '<span class="badge badge-rejected">Rejected</span>';
                  break;
                default:
                  statusBadge = '<span class="badge">Unknown</span>';
              }
              
              const row = document.createElement('tr');
              row.innerHTML = `
                <td>${app.email}</td>
                <td>${app.organization || 'N/A'}</td>
                <td>${app.purpose ? (app.purpose.length > 50 ? app.purpose.substring(0, 50) + '...' : app.purpose) : 'N/A'}</td>
                <td>${statusBadge}</td>
                <td>${createdDate}</td>
                <td>
                  <button class="btn-primary view-application-btn" data-email="${app.email}">View</button>
                </td>
              `;
              
              applicationsListElem.appendChild(row);
            });
            
            // Setup view buttons
            document.querySelectorAll('.view-application-btn').forEach(btn => {
              btn.addEventListener('click', () => {
                const email = btn.getAttribute('data-email');
                viewApplicationDetails(email);
              });
            });
            
            // Generate pagination
            generatePagination(
              filteredApplications.length, 
              currentApplicationsPage, 
              'applications-pagination', 
              renderApplicationsPage
            );
          }
          
          // View application details
          async function viewApplicationDetails(email) {
            try {
              // Set current application email
              currentApplicationEmail = email;
              
              // Find application in the list
              const application = allApplications.find(app => app.email === email);
              
              if (!application) {
                throw new Error('Application not found');
              }
              
              // Format dates
              const createdDate = application.created_at ? 
                new Date(application.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
              const updatedDate = application.updated_at ? 
                new Date(application.updated_at._seconds * 1000).toLocaleDateString() : 'N/A';
              
              // Generate details HTML
              let detailsHtml = `
                <p><strong>Email:</strong> ${application.email}</p>
                <p><strong>Organization:</strong> ${application.organization || 'N/A'}</p>
                <p><strong>Purpose:</strong> ${application.purpose || 'N/A'}</p>
                <p><strong>Status:</strong> ${application.status || 'N/A'}</p>
                <p><strong>Created:</strong> ${createdDate}</p>
                <p><strong>Last Updated:</strong> ${updatedDate}</p>
              `;
              
              // Add approval/rejection info if available
              if (application.status === 'approved' && application.approved_by) {
                detailsHtml += `<p><strong>Approved By:</strong> ${application.approved_by}</p>`;
              } else if (application.status === 'rejected') {
                detailsHtml += `
                  <p><strong>Rejected By:</strong> ${application.rejected_by || 'N/A'}</p>
                  <p><strong>Rejection Reason:</strong> ${application.rejection_reason || 'No reason provided'}</p>
                `;
              }
              
              // Update modal content
              document.getElementById('application-details').innerHTML = detailsHtml;
              
              // Show/hide action buttons based on status
              if (application.status === 'pending') {
                document.getElementById('application-actions').style.display = 'flex';
                document.getElementById('rejection-form').style.display = 'none';
              } else {
                document.getElementById('application-actions').style.display = 'none';
                document.getElementById('rejection-form').style.display = 'none';
              }
              
              // Clear status message
              document.getElementById('application-status-message').innerHTML = '';
              
              // Show the modal
              applicationModal.style.display = 'block';
              
            } catch (error) {
              console.error('Error viewing application details:', error);
              alert('Error viewing application details: ' + error.message);
            }
          }
          
          // Approve application
          async function approveApplication() {
            if (!currentApplicationEmail) return;
            
            try {
              const user = firebase.auth().currentUser;
              if (!user) throw new Error('Not authenticated');
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Send approval request
              const response = await fetch(`/admin/applications/${currentApplicationEmail}/approve`, {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Show success message
                document.getElementById('application-status-message').innerHTML = `
                  <div class="alert alert-success">
                    Application approved successfully. The user can now access the API.
                  </div>
                `;
                
                // Hide action buttons
                document.getElementById('application-actions').style.display = 'none';
                
                // Update application in the list
                updateApplicationInList(currentApplicationEmail, 'approved');
                
                // Reload applications after a short delay
                setTimeout(() => {
                  loadApplications(user);
                }, 2000);
              } else {
                throw new Error(data.error || 'Failed to approve application');
              }
            } catch (error) {
              console.error('Error approving application:', error);
              document.getElementById('application-status-message').innerHTML = `
                <div class="alert alert-danger">
                  Error approving application: ${error.message}
                </div>
              `;
            }
          }
          
          // Reject application
          async function rejectApplication() {
            if (!currentApplicationEmail) return;
            
            try {
              const user = firebase.auth().currentUser;
              if (!user) throw new Error('Not authenticated');
              
              // Get rejection reason
              const reason = document.getElementById('rejection-reason').value;
              if (!reason) {
                throw new Error('Please provide a reason for rejection');
              }
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Send rejection request
              const response = await fetch(`/admin/applications/${currentApplicationEmail}/reject`, {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`,
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  reason: reason
                })
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Show success message
                document.getElementById('application-status-message').innerHTML = `
                  <div class="alert alert-success">
                    Application rejected successfully.
                  </div>
                `;
                
                // Hide rejection form
                document.getElementById('rejection-form').style.display = 'none';
                
                // Update application in the list
                updateApplicationInList(currentApplicationEmail, 'rejected');
                
                // Reload applications after a short delay
                setTimeout(() => {
                  loadApplications(user);
                }, 2000);
              } else {
                throw new Error(data.error || 'Failed to reject application');
              }
            } catch (error) {
              console.error('Error rejecting application:', error);
              document.getElementById('application-status-message').innerHTML = `
                <div class="alert alert-danger">
                  Error rejecting application: ${error.message}
                </div>
              `;
            }
          }
          
          // Update application in the local list
          function updateApplicationInList(email, newStatus) {
            // Find application in the list
            const appIndex = allApplications.findIndex(app => app.email === email);
            
            if (appIndex >= 0) {
              // Update application status
              allApplications[appIndex].status = newStatus;
              
              // Reapply filters
              applyFiltersToApplications();
            }
          }
          
          // Load API keys
          async function loadApiKeys(user) {
            try {
              // Show loading indicator
              document.getElementById('api-keys-loading').style.display = 'block';
              document.getElementById('api-keys-table').style.display = 'none';
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Fetch API keys
              const response = await fetch('/admin/api-keys', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Store all API keys
                allApiKeys = data.api_keys;
                filteredApiKeys = [...allApiKeys];
                
                // Render first page
                renderApiKeysPage(1);
              } else {
                throw new Error(data.error || 'Failed to load API keys');
              }
            } catch (error) {
              console.error('Error loading API keys:', error);
              document.getElementById('api-keys-loading').textContent = 
                'Error loading API keys: ' + error.message;
            }
          }
          
          // Render API keys page
          function renderApiKeysPage(page) {
            // Update current page
            currentApiKeysPage = page;
            
            // Calculate pagination
            const startIndex = (page - 1) * itemsPerPage;
            const endIndex = startIndex + itemsPerPage;
            const pageApiKeys = filteredApiKeys.slice(startIndex, endIndex);
            
            // Hide loading, show table
            document.getElementById('api-keys-loading').style.display = 'none';
            document.getElementById('api-keys-table').style.display = 'table';
            
            // Populate table
            const apiKeysListElem = document.getElementById('api-keys-list');
            apiKeysListElem.innerHTML = '';
            
            pageApiKeys.forEach(key => {
              // Format dates
              const createdDate = key.created_at ? new Date(key.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
              const expiresDate = key.expires_at ? new Date(key.expires_at._seconds * 1000).toLocaleDateString() : 'N/A';
              
              // Status badge
              const statusBadge = key.active ? 
                '<span class="badge badge-approved">Active</span>' : 
                '<span class="badge badge-rejected">Revoked</span>';
              
              const row = document.createElement('tr');
              row.innerHTML = `
                <td>${key.owner}</td>
                <td>${key.name || 'Unnamed Key'}</td>
                <td>${createdDate}</td>
                <td>${expiresDate}</td>
                <td>${statusBadge}</td>
                <td>
                  ${key.active ? `<button class="btn-danger revoke-key-btn" data-key-id="${key.key_id}">Revoke</button>` : ''}
                </td>
              `;
              
              apiKeysListElem.appendChild(row);
            });
            
            // Setup revoke buttons
            document.querySelectorAll('.revoke-key-btn').forEach(btn => {
              btn.addEventListener('click', () => {
                const keyId = btn.getAttribute('data-key-id');
                showRevokeKeyModal(keyId);
              });
            });
            
            // Generate pagination
            generatePagination(
              filteredApiKeys.length, 
              currentApiKeysPage, 
              'api-keys-pagination', 
              renderApiKeysPage
            );
          }
          
          // Show revoke key modal
          function showRevokeKeyModal(keyId) {
            // Set current key ID
            currentKeyId = keyId;
            
            // Find key in the list
            const key = allApiKeys.find(k => k.key_id === keyId);
            
            if (!key) {
              alert('API key not found');
              return;
            }
            
            // Format created date
            const createdDate = key.created_at ? 
              new Date(key.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
            
            // Update modal content
            document.getElementById('key-user-email').textContent = key.owner;
            document.getElementById('key-name').textContent = key.name || 'Unnamed Key';
            document.getElementById('key-created').textContent = createdDate;
            
            // Clear form and status messages
            document.getElementById('revocation-reason').value = '';
            document.getElementById('revoke-key-error').style.display = 'none';
            document.getElementById('revoke-key-success').style.display = 'none';
            
            // Show the modal
            revokeKeyModal.style.display = 'block';
          }
          
          // Revoke API key
          async function revokeApiKey() {
            if (!currentKeyId) return;
            
            try {
              const user = firebase.auth().currentUser;
              if (!user) throw new Error('Not authenticated');
              
              // Get revocation reason
              const reason = document.getElementById('revocation-reason').value;
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Send revocation request
              const response = await fetch(`/admin/api-keys/${currentKeyId}/revoke`, {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`,
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  reason: reason
                })
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Show success message
                document.getElementById('revoke-key-success').textContent = 'API key revoked successfully';
                document.getElementById('revoke-key-success').style.display = 'block';
                document.getElementById('revoke-key-error').style.display = 'none';
                
                // Update key in the list
                updateApiKeyInList(currentKeyId, false);
                
                // Reload API keys after a short delay
                setTimeout(() => {
                  // Close the modal
                  revokeKeyModal.style.display = 'none';
                  
                  // Reload the list
                  loadApiKeys(user);
                }, 2000);
              } else {
                throw new Error(data.error || 'Failed to revoke API key');
              }
            } catch (error) {
              console.error('Error revoking API key:', error);
              document.getElementById('revoke-key-error').textContent = 'Error: ' + error.message;
              document.getElementById('revoke-key-error').style.display = 'block';
              document.getElementById('revoke-key-success').style.display = 'none';
            }
          }
          
          // Update API key in the local list
          function updateApiKeyInList(keyId, active) {
            // Find key in the list
            const keyIndex = allApiKeys.findIndex(key => key.key_id === keyId);
            
            if (keyIndex >= 0) {
              // Update key status
              allApiKeys[keyIndex].active = active;
              
              // Apply filters (currently just copying the list)
              filteredApiKeys = [...allApiKeys];
              
              // If there's a search term, reapply it
              const searchTerm = document.getElementById('api-key-search').value.toLowerCase();
              if (searchTerm) {
                filteredApiKeys = filteredApiKeys.filter(key => {
                  return key.owner.toLowerCase().includes(searchTerm) || 
                         (key.name && key.name.toLowerCase().includes(searchTerm));
                });
              }
              
              // Re-render current page
              renderApiKeysPage(currentApiKeysPage);
            }
          }
          
          // Load admins
          async function loadAdmins(user) {
            try {
              // Show loading indicator
              document.getElementById('admins-loading').style.display = 'block';
              document.getElementById('admins-table').style.display = 'none';
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Fetch admins
              const response = await fetch('/admin/list-admins', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Hide loading, show table
                document.getElementById('admins-loading').style.display = 'none';
                document.getElementById('admins-table').style.display = 'table';
                
                // Populate table
                const adminsListElem = document.getElementById('admins-list');
                adminsListElem.innerHTML = '';
                
                data.admins.forEach(admin => {
                  // Format date
                  const addedDate = admin.added_at ? 
                    new Date(admin.added_at._seconds * 1000).toLocaleDateString() : 'N/A';
                  
                  const row = document.createElement('tr');
                  row.innerHTML = `
                    <td>${admin.email}</td>
                    <td>${admin.added_by || 'N/A'}</td>
                    <td>${addedDate}</td>
                    <td>
                      ${admin.email !== user.email ? 
                        `<button class="btn-danger remove-admin-btn" data-email="${admin.email}">Remove</button>` : 
                        '<em>Current User</em>'}
                    </td>
                  `;
                  
                  adminsListElem.appendChild(row);
                });
                
                // Setup remove buttons
                document.querySelectorAll('.remove-admin-btn').forEach(btn => {
                  btn.addEventListener('click', () => {
                    const email = btn.getAttribute('data-email');
                    if (confirm(`Are you sure you want to remove ${email} as an admin?`)) {
                      removeAdmin(email);
                    }
                  });
                });
              } else {
                throw new Error(data.error || 'Failed to load admins');
              }
            } catch (error) {
              console.error('Error loading admins:', error);
              document.getElementById('admins-loading').textContent = 
                'Error loading admins: ' + error.message;
            }
          }
          
          // Add admin
          async function addAdmin() {
            const emailElem = document.getElementById('admin-email');
            const errorElem = document.getElementById('add-admin-error');
            const successElem = document.getElementById('add-admin-success');
            const email = emailElem.value.trim();
            
            // Clear status messages
            errorElem.style.display = 'none';
            successElem.style.display = 'none';
            
            if (!email) {
              errorElem.textContent = 'Please enter an email address';
              errorElem.style.display = 'block';
              return;
            }
            
            try {
              const user = firebase.auth().currentUser;
              if (!user) throw new Error('Not authenticated');
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Send add admin request
              const response = await fetch('/admin/add-admin', {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`,
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  email: email
                })
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Show success message
                successElem.textContent = `${email} has been added as an admin`;
                successElem.style.display = 'block';
                
                // Clear input
                emailElem.value = '';
                
                // Reload admins list
                loadAdmins(user);
              } else {
                throw new Error(data.error || 'Failed to add admin');
              }
            } catch (error) {
              console.error('Error adding admin:', error);
              errorElem.textContent = 'Error: ' + error.message;
              errorElem.style.display = 'block';
            }
          }
          
          // Remove admin
          async function removeAdmin(email) {
            try {
              const user = firebase.auth().currentUser;
              if (!user) throw new Error('Not authenticated');
              
              // Get ID token
              const idToken = await user.getIdToken(true);
              
              // Send remove admin request
              const response = await fetch('/admin/remove-admin', {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`,
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  email: email
                })
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Reload admins list
                loadAdmins(user);
              } else {
                throw new Error(data.error || 'Failed to remove admin');
              }
            } catch (error) {
              console.error('Error removing admin:', error);
              alert('Error: ' + error.message);
            }
          }
          
          // Generate pagination buttons
          function generatePagination(totalItems, currentPage, containerId, clickHandler) {
            const totalPages = Math.ceil(totalItems / itemsPerPage);
            const container = document.getElementById(containerId);
            
            if (totalPages <= 1) {
              container.innerHTML = '';
              return;
            }
            
            let html = '';
            
            // Previous button
            html += `<button ${currentPage === 1 ? 'disabled' : ''} data-page="${currentPage - 1}">Prev</button>`;
            
            // Page buttons
            const maxButtons = 5;
            const startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
            const endPage = Math.min(totalPages, startPage + maxButtons - 1);
            
            for (let i = startPage; i <= endPage; i++) {
              html += `<button class="${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
            }
            
            // Next button
            html += `<button ${currentPage === totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">Next</button>`;
            
            container.innerHTML = html;
            
            // Add event listeners
            container.querySelectorAll('button:not([disabled])').forEach(btn => {
              btn.addEventListener('click', () => {
                const page = parseInt(btn.getAttribute('data-page'));
                clickHandler(page);
              });
            });
          }
          
          // Start the page initialization when the DOM is ready
          document.addEventListener('DOMContentLoaded', initPage);
        </script>
      </body>
    </html>
    """,
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"])
                                  
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
    """Approve a user application"""
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
        # Get the application
        app_doc = db.collection('user_applications').document(email).get()
        
        if not app_doc.exists:
            return jsonify({'error': 'Application not found'}), 404
        
        app_data = app_doc.to_dict()
        
        # Check if already approved
        if app_data.get('status') == 'approved':
            return jsonify({'error': 'Application is already approved'}), 400
        
        # Update the application status
        db.collection('user_applications').document(email).update({
            'status': 'approved',
            'approved_by': admin_email,
            'approved_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        return jsonify({
            'status': 'success',
            'message': f'Application for {email} has been approved'
        })
        
    except Exception as e:
        logger.error(f"Error approving application: {str(e)}")
        return jsonify({'error': f'Failed to approve application: {str(e)}'}), 500

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
# @app.route('/api-client', methods=['GET']) ######################################################################## optional? TODO
# def api_client():
#     # Get Firebase configuration from Secret Manager
#     firebase_config = get_firebase_config()
    
#     return render_template_string("""
#     <!DOCTYPE html>
#     <html>
#         <!-- HTML content remains the same except for the script block -->
#         <body>
#         <!-- Body content remains the same -->
        
#         <script>
#             // Initialize Firebase
#             const firebaseConfig = {
#             apiKey: "{{ api_key }}",
#             authDomain: "{{ auth_domain }}",
#             projectId: "{{ project_id }}",
#             storageBucket: "{{ storage_bucket }}",
#             messagingSenderId: "{{ messaging_sender_id }}",
#             appId: "{{ app_id }}"
#             };
#             firebase.initializeApp(firebaseConfig);
            
#             // Rest of the JavaScript remains the same
#         </script>
#         </body>
#     </html>
#     """, 
#     api_key=firebase_config["apiKey"],
#     auth_domain=firebase_config["authDomain"],
#     project_id=firebase_config["projectId"],
#     storage_bucket=firebase_config.get("storageBucket", ""),
#     messaging_sender_id=firebase_config.get("messagingSenderId", ""),
#     app_id=firebase_config["appId"])


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
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>VoucherVision Prompt Templates</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #2c3e50; }
        .prompt-table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        .prompt-table th, .prompt-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .prompt-table th { background-color: #f2f2f2; color: #333; }
        .prompt-table tr:nth-child(even) { background-color: #f9f9f9; }
        .prompt-table tr:hover { background-color: #f1f1f1; }
        .description { max-width: 400px; }
        .details-btn { padding: 6px 12px; background-color: #3498db; color: white; border: none; 
                     border-radius: 4px; cursor: pointer; }
        .details-btn:hover { background-color: #2980b9; }
        
        #detailsPanel {
            background-color: #fff;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            display: none; /* Hidden by default */
            position: relative;
            overflow: auto;
            max-height: 80vh;
        }
        
        .panel-close {
            position: absolute;
            top: 10px;
            right: 15px;
            font-size: 24px;
            color: #aaa;
            cursor: pointer;
            font-weight: bold;
        }
        
        .panel-close:hover {
            color: black;
        }
        
        pre { 
            background-color: #f8f8f8; 
            padding: 10px; 
            border-radius: 4px; 
            overflow-x: auto; 
            white-space: pre-wrap; 
            word-wrap: break-word;
            font-size: 14px;
            line-height: 1.4;
        }
        
        .highlight {
            background-color: #fffacd;
            transition: background-color 0.5s ease;
        }
        
        /* JSON formatting */
        .json-key { color: #881391; }
        .json-string { color: #0b7500; }
        .json-number { color: #1A01CC; }
        .json-boolean { color: #1A01CC; }
        .json-null { color: #1A01CC; }
        
        /* Styling for the hierarchical display */
        .tree-view {
            font-family: monospace;
            line-height: 1.5;
        }
        .tree-key {
            color: #333;
            font-weight: bold;
        }
        .tree-value {
            color: #0b7500;
        }
        .tree-object, .tree-array {
            margin-left: 20px;
            border-left: 1px dashed #ccc;
            padding-left: 10px;
        }
        .tree-toggle {
            cursor: pointer;
            user-select: none;
            color: #3498db;
        }
        .tree-toggle:hover {
            text-decoration: underline;
        }
        
        /* Sections */
        .section-nav {
            margin-bottom: 15px;
            padding: 10px;
            background-color: #f8f8f8;
            border-radius: 4px;
        }
        .section-nav a {
            margin-right: 15px;
            color: #3498db;
            text-decoration: none;
        }
        .section-nav a:hover {
            text-decoration: underline;
        }
        .section-heading {
            margin-top: 25px;
            padding-bottom: 8px;
            border-bottom: 1px solid #eee;
            color: #2c3e50;
        }
    </style>
</head>
<body>
    <h1>VoucherVision Prompt Templates</h1>
    
    <!-- Details panel that stays above the table -->
    <div id="detailsPanel">
        <span class="panel-close" id="closePanel">&times;</span>
        <h2 id="detailsTitle">Prompt Details</h2>
        <div id="sectionNav" class="section-nav"></div>
        <div id="promptDetails">
            <!-- Prompt details will be loaded here -->
        </div>
    </div>
    
    <div id="loading">Loading prompts...</div>
    <table class="prompt-table" id="promptTable" style="display:none;">
        <thead>
            <tr>
                <th>#</th>
                <th>Filename</th>
                <th>Name</th>
                <th class="description">Description</th>
                <th>Version</th>
                <th>Author</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="promptList">
            <!-- Prompts will be loaded here -->
        </tbody>
    </table>
    
    <script>
        // Helper function to safely get nested properties
        function getNestedValue(obj, path, defaultValue = "") {
            if (!obj) return defaultValue;
            
            const keys = path.split('.');
            let current = obj;
            
            for (const key of keys) {
                if (current && typeof current === 'object' && key in current) {
                    current = current[key];
                } else {
                    return defaultValue;
                }
            }
            
            return current ?? defaultValue;
        }
        
        // Function to render hierarchical data
        function renderHierarchical(data, level = 0) {
            if (data === null) return '<span class="tree-value">null</span>';
            if (typeof data !== 'object') {
                if (typeof data === 'string') {
                    return `<span class="tree-value">"${data}"</span>`;
                }
                return `<span class="tree-value">${data}</span>`;
            }
            
            let html = '';
            
            if (Array.isArray(data)) {
                html += '<div class="tree-array">';
                data.forEach((item, index) => {
                    html += `<div>[${index}]: ${renderHierarchical(item, level + 1)}</div>`;
                });
                html += '</div>';
            } else {
                html += '<div class="tree-object">';
                Object.keys(data).forEach(key => {
                    const value = data[key];
                    const isComplex = value !== null && typeof value === 'object';
                    
                    html += '<div>';
                    if (isComplex) {
                        const id = `tree-${level}-${key.replace(/[^a-z0-9]/gi, '')}`;
                        html += `<span class="tree-toggle" data-target="${id}">+</span> `;
                        html += `<span class="tree-key">${key}:</span> `;
                        html += `<div id="${id}" style="display: none;">`;
                        html += renderHierarchical(value, level + 1);
                        html += '</div>';
                    } else {
                        html += `<span class="tree-key">${key}:</span> ${renderHierarchical(value, level + 1)}`;
                    }
                    html += '</div>';
                });
                html += '</div>';
            }
            
            return html;
        }

        // Fetch and display the prompt list
        fetch('/prompts')
            .then(response => response.json())
            .then(data => {
                document.getElementById('loading').style.display = 'none';
                document.getElementById('promptTable').style.display = 'table';
                
                if (data.status === 'success') {
                    const promptList = document.getElementById('promptList');
                    
                    data.prompts.forEach((prompt, index) => {
                        const row = document.createElement('tr');
                        row.id = `prompt-row-${index}`;
                        
                        // Extract prompt metadata
                        const name = getNestedValue(prompt, 'name');
                        const description = getNestedValue(prompt, 'description');
                        const version = getNestedValue(prompt, 'version');
                        const author = getNestedValue(prompt, 'author');
                        
                        row.innerHTML = `
                            <td>${index + 1}</td>
                            <td>${prompt.filename}</td>
                            <td>${name}</td>
                            <td class="description">${description}</td>
                            <td>${version}</td>
                            <td>${author}</td>
                            <td><button class="details-btn" data-filename="${prompt.filename}" data-row-id="${row.id}">View Details</button></td>
                        `;
                        
                        promptList.appendChild(row);
                    });
                    
                    // Add event listeners to the buttons
                    document.querySelectorAll('.details-btn').forEach(button => {
                        button.addEventListener('click', () => {
                            const filename = button.getAttribute('data-filename');
                            const rowId = button.getAttribute('data-row-id');
                            loadPromptDetails(filename, rowId);
                        });
                    });
                } else {
                    alert('Error: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Error fetching prompts:', error);
                document.getElementById('loading').textContent = 'Error loading prompts: ' + error.message;
            });
        
        // Function to remove highlight from all rows
        function removeAllHighlights() {
            document.querySelectorAll('tr.highlight').forEach(row => {
                row.classList.remove('highlight');
            });
        }
        
        // Load prompt details
        function loadPromptDetails(filename, rowId) {
            // Highlight the selected row
            removeAllHighlights();
            const selectedRow = document.getElementById(rowId);
            if (selectedRow) {
                selectedRow.classList.add('highlight');
            }
            
            // Show loading in the panel
            const detailsPanel = document.getElementById('detailsPanel');
            detailsPanel.style.display = 'block';
            document.getElementById('detailsTitle').textContent = `Prompt: ${filename}`;
            document.getElementById('promptDetails').innerHTML = '<p>Loading prompt details...</p>';
            document.getElementById('sectionNav').innerHTML = '';
            
            // Scroll to top to show the panel
            window.scrollTo({top: 0, behavior: 'smooth'});
            
            fetch(`/prompts?prompt=${filename}`)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        const prompt = data.prompt;
                        document.getElementById('detailsTitle').textContent = `Prompt: ${filename}`;
                        
                        // Get the parsed YAML data or raw content
                        let parsedData = null;
                        let rawContent = '';
                        
                        if (prompt.details && prompt.details.parsed_data) {
                            parsedData = prompt.details.parsed_data;
                            rawContent = prompt.details.raw_content || '';
                        } else if (prompt.details) {
                            // Fallback if structure is different
                            parsedData = prompt.details;
                            rawContent = JSON.stringify(prompt.details, null, 2);
                        } else {
                            // Last resort
                            parsedData = prompt;
                            rawContent = JSON.stringify(prompt, null, 2);
                        }
                        
                        // Start building the details HTML
                        let detailsHTML = '';
                        let sectionLinks = [];
                        
                        // Build the metadata section
                        const metaFields = [
                            {key: 'prompt_name', label: 'Name'},
                            {key: 'prompt_description', label: 'Description'},
                            {key: 'prompt_version', label: 'Version'},
                            {key: 'prompt_author', label: 'Author'},
                            {key: 'prompt_author_institution', label: 'Institution'},
                            {key: 'LLM', label: 'LLM Type'}
                        ];
                        
                        detailsHTML += `<div id="section-metadata">`;
                        detailsHTML += `<h3 class="section-heading">Metadata</h3>`;
                        detailsHTML += `<table class="metadata-table">`;
                        
                        metaFields.forEach(field => {
                            const value = parsedData[field.key] || '';
                            if (value) {
                                detailsHTML += `<tr><td><strong>${field.label}:</strong></td><td>${value}</td></tr>`;
                            }
                        });
                        
                        detailsHTML += `</table></div>`;
                        sectionLinks.push({id: 'section-metadata', label: 'Metadata'});
                        
                        // Add common sections that most prompts would have
                        const commonSections = [
                            {key: 'instructions', label: 'Instructions'},
                            {key: 'json_formatting_instructions', label: 'JSON Formatting'},
                            {key: 'rules', label: 'Rules'},
                            {key: 'mapping', label: 'Mapping'},
                            {key: 'examples', label: 'Examples'}
                        ];
                        
                        commonSections.forEach(section => {
                            if (parsedData[section.key]) {
                                const sectionId = `section-${section.key}`;
                                detailsHTML += `<div id="${sectionId}">`;
                                detailsHTML += `<h3 class="section-heading">${section.label}</h3>`;
                                
                                if (typeof parsedData[section.key] === 'object') {
                                    detailsHTML += `<div class="tree-view">`;
                                    detailsHTML += renderHierarchical(parsedData[section.key]);
                                    detailsHTML += `</div>`;
                                } else {
                                    detailsHTML += `<pre>${parsedData[section.key]}</pre>`;
                                }
                                
                                detailsHTML += `</div>`;
                                sectionLinks.push({id: sectionId, label: section.label});
                            }
                        });
                        
                        // Add other sections not included in commonSections
                        Object.keys(parsedData).forEach(key => {
                            // Skip metadata fields and already processed common sections
                            if (!metaFields.some(field => field.key === key) && 
                                !commonSections.some(section => section.key === key)) {
                                
                                const sectionId = `section-${key}`;
                                const sectionLabel = key.replace(/_/g, ' ')
                                    .replace(/\b\w/g, l => l.toUpperCase());
                                
                                detailsHTML += `<div id="${sectionId}">`;
                                detailsHTML += `<h3 class="section-heading">${sectionLabel}</h3>`;
                                
                                if (typeof parsedData[key] === 'object') {
                                    detailsHTML += `<div class="tree-view">`;
                                    detailsHTML += renderHierarchical(parsedData[key]);
                                    detailsHTML += `</div>`;
                                } else {
                                    detailsHTML += `<pre>${parsedData[key]}</pre>`;
                                }
                                
                                detailsHTML += `</div>`;
                                sectionLinks.push({id: sectionId, label: sectionLabel});
                            }
                        });
                        
                        // Add raw content section
                        const rawSectionId = 'section-raw';
                        detailsHTML += `<div id="${rawSectionId}">`;
                        detailsHTML += `<h3 class="section-heading">Raw Content</h3>`;
                        detailsHTML += `<pre>${rawContent}</pre>`;
                        detailsHTML += `</div>`;
                        sectionLinks.push({id: rawSectionId, label: 'Raw Content'});
                        
                        // Create section navigation
                        let navHtml = '';
                        sectionLinks.forEach((link, index) => {
                            navHtml += `<a href="#${link.id}">${link.label}</a>`;
                            if (index < sectionLinks.length - 1) {
                                navHtml += ' | ';
                            }
                        });
                        document.getElementById('sectionNav').innerHTML = navHtml;
                        
                        // Update the details content
                        document.getElementById('promptDetails').innerHTML = detailsHTML;
                        
                        // Add event listeners for tree toggles
                        document.querySelectorAll('.tree-toggle').forEach(toggle => {
                            toggle.addEventListener('click', function() {
                                const targetId = this.getAttribute('data-target');
                                const targetElement = document.getElementById(targetId);
                                
                                if (targetElement.style.display === 'none') {
                                    targetElement.style.display = 'block';
                                    this.textContent = '-';
                                } else {
                                    targetElement.style.display = 'none';
                                    this.textContent = '+';
                                }
                            });
                        });
                    } else {
                        document.getElementById('promptDetails').innerHTML = `<div class="error">Error: ${data.message}</div>`;
                    }
                })
                .catch(error => {
                    console.error('Error fetching prompt details:', error);
                    document.getElementById('promptDetails').innerHTML = `<div class="error">Error loading details: ${error.message}</div>`;
                });
        }
        
        // Close the details panel
        document.getElementById('closePanel').addEventListener('click', () => {
            document.getElementById('detailsPanel').style.display = 'none';
            removeAllHighlights();
        });
    </script>
</body>
</html>""")

@app.route('/api-key-management', methods=['GET'])
@authenticated_route
def api_key_management_ui():
    """Web UI for API key management"""
    # Get Firebase configuration from Secret Manager
    firebase_config = get_firebase_config()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <title>VoucherVision API Key Management</title>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.0.0/firebase-auth-compat.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
        <style>
          body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 0; 
            background-color: #f5f5f5; 
          }
          .container { 
            max-width: 1000px; 
            margin: 50px auto; 
            padding: 30px; 
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
          }
          .header { 
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            border-bottom: 1px solid #eee;
            padding-bottom: 15px;
          }
          .header h2 {
            margin: 0;
          }
          .key-table {
            width: 100%;
            margin-top: 20px;
          }
          .key-table th {
            text-align: left;
            padding: 10px;
            background-color: #f8f9fa;
          }
          .key-table td {
            padding: 10px;
            border-top: 1px solid #eee;
          }
          .btn-create {
            background-color: #4285f4;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
          }
          .btn-create:hover {
            background-color: #3367d6;
          }
          .btn-revoke {
            background-color: #f44336;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
          }
          .btn-revoke:hover {
            background-color: #d32f2f;
          }
          .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
          }
          .modal-content {
            background-color: white;
            margin: 10% auto;
            padding: 30px;
            width: 80%;
            max-width: 600px;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
          }
          .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
          }
          .close:hover {
            color: black;
          }
          .key-display {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
            word-break: break-all;
            font-family: monospace;
            font-size: 16px;
          }
          .copy-btn {
            margin-top: 10px;
            background-color: #4285f4;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 4px;
            cursor: pointer;
          }
          .copy-btn:hover {
            background-color: #3367d6;
          }
          .error-message {
            color: #d93025;
            margin-top: 10px;
            display: none;
          }
          .success-message {
            color: #0f9d58;
            margin-top: 10px;
            display: none;
          }
          .loading {
            text-align: center;
            padding: 20px;
            font-style: italic;
            color: #666;
          }
          .no-keys {
            text-align: center;
            padding: 20px;
            font-style: italic;
            color: #666;
          }
          .badge-active {
            background-color: #0f9d58;
            color: white;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 12px;
          }
          .badge-inactive {
            background-color: #d93025;
            color: white;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 12px;
          }
          .form-group {
            margin-bottom: 20px;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h2>API Key Management</h2>
            <div>
              <button id="create-key-btn" class="btn-create">Create New API Key</button>
              <button id="logout-btn" class="btn btn-outline-secondary ms-2">Sign Out</button>
            </div>
          </div>
          
          <div id="user-info">
            <p><strong>Signed in as:</strong> <span id="user-email">Loading...</span></p>
          </div>
          
          <div id="keys-container">
            <div id="loading" class="loading">Loading your API keys...</div>
            <div id="error-message" class="error-message"></div>
            <div id="no-keys" class="no-keys" style="display: none;">You don't have any API keys yet. Click "Create New API Key" to get started.</div>
            <table id="keys-table" class="key-table" style="display: none;">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Created</th>
                  <th>Expires</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody id="keys-list">
                <!-- API keys will be listed here -->
              </tbody>
            </table>
          </div>
          
          <!-- Create Key Modal -->
          <div id="create-key-modal" class="modal">
            <div class="modal-content">
              <span class="close">&times;</span>
              <h3>Create New API Key</h3>
              <p>Create a new long-lived API key for programmatic access to the VoucherVision API.</p>
              
              <form id="create-key-form">
                <div class="form-group">
                  <label for="key-name">Key Name</label>
                  <input type="text" id="key-name" class="form-control" placeholder="e.g., Production Server">
                </div>
                
                <div class="form-group">
                  <label for="key-description">Description (Optional)</label>
                  <textarea id="key-description" class="form-control" placeholder="What will this key be used for?"></textarea>
                </div>
                
                <div class="form-group">
                  <label for="key-expiry">Expires After</label>
                  <select id="key-expiry" class="form-control">
                    <option value="30">30 days</option>
                    <option value="90">90 days</option>
                    <option value="180">180 days</option>
                    <option value="365" selected>1 year</option>
                    <option value="730">2 years</option>
                  </select>
                </div>
                
                <button type="submit" class="btn-create">Create API Key</button>
              </form>
              
              <div id="form-error" class="error-message"></div>
            </div>
          </div>
          
          <!-- Display Key Modal -->
          <div id="display-key-modal" class="modal">
            <div class="modal-content">
              <span class="close">&times;</span>
              <h3>Your New API Key</h3>
              <p><strong>IMPORTANT:</strong> This key will only be displayed once. Please copy it and store it securely.</p>
              
              <div id="api-key-display" class="key-display"></div>
              <button id="copy-key-btn" class="copy-btn">Copy to Clipboard</button>
              <div id="copy-success" class="success-message">API key copied to clipboard!</div>
              
              <h4 class="mt-4">Usage Example:</h4>
              <pre id="usage-example" style="background-color: #f8f9fa; padding: 15px; border-radius: 4px;">
# Using API key with Python client
python client.py --server {{ server_url }} --auth-token YOUR_API_KEY --image "path/to/image.jpg" --output-dir "./results"

# Using API key with cURL
curl -X POST "{{ server_url }}/process" \\
     -H "X-API-Key: YOUR_API_KEY" \\
     -F "file=@your_image.jpg"</pre>
            </div>
          </div>
        </div>
        
        <script>
          // Firebase configuration
          const firebaseConfig = {
            apiKey: "{{ api_key }}",
            authDomain: "{{ auth_domain }}",
            projectId: "{{ project_id }}",
            storageBucket: "{{ storage_bucket }}",
            messagingSenderId: "{{ messaging_sender_id }}",
            appId: "{{ app_id }}"
          };
          
          // Initialize Firebase
          firebase.initializeApp(firebaseConfig);
          
          // DOM elements
          const createKeyBtn = document.getElementById('create-key-btn');
          const logoutBtn = document.getElementById('logout-btn');
          const createKeyModal = document.getElementById('create-key-modal');
          const displayKeyModal = document.getElementById('display-key-modal');
          const closeButtons = document.querySelectorAll('.close');
          const createKeyForm = document.getElementById('create-key-form');
          const copyKeyBtn = document.getElementById('copy-key-btn');
          const apiKeyDisplay = document.getElementById('api-key-display');
          const copySuccess = document.getElementById('copy-success');
          const formError = document.getElementById('form-error');
          const usageExample = document.getElementById('usage-example');
          
          // Initialize the page
          function initPage() {
            // Check if user is authenticated
            firebase.auth().onAuthStateChanged(function(user) {
              if (user) {
                // User is signed in, display their email
                document.getElementById('user-email').textContent = user.email;
                
                // Get the user's API keys
                loadApiKeys(user);
              } else {
                // Not signed in, redirect to login page
                window.location.href = '/login';
              }
            });
            
            // Event listeners
            createKeyBtn.addEventListener('click', () => {
              createKeyModal.style.display = 'block';
            });
            
            closeButtons.forEach(btn => {
              btn.addEventListener('click', () => {
                createKeyModal.style.display = 'none';
                displayKeyModal.style.display = 'none';
              });
            });
            
            // Close modals when clicking outside
            window.addEventListener('click', (event) => {
              if (event.target === createKeyModal) {
                createKeyModal.style.display = 'none';
              }
              if (event.target === displayKeyModal) {
                displayKeyModal.style.display = 'none';
              }
            });
            
            // Create key form submission
            createKeyForm.addEventListener('submit', (e) => {
              e.preventDefault();
              createApiKey();
            });
            
            // Copy key button
            copyKeyBtn.addEventListener('click', () => {
              const keyText = apiKeyDisplay.textContent;
              navigator.clipboard.writeText(keyText)
                .then(() => {
                  copySuccess.style.display = 'block';
                  setTimeout(() => {
                    copySuccess.style.display = 'none';
                  }, 3000);
                })
                .catch(err => {
                  console.error('Could not copy text: ', err);
                });
            });
            
            // Logout button
            logoutBtn.addEventListener('click', () => {
              firebase.auth().signOut().then(() => {
                window.location.href = '/login';
              });
            });
          }
          
          // Load API keys
          async function loadApiKeys(user) {
            const keysContainer = document.getElementById('keys-container');
            const loadingElem = document.getElementById('loading');
            const errorMessageElem = document.getElementById('error-message');
            const noKeysElem = document.getElementById('no-keys');
            const keysTableElem = document.getElementById('keys-table');
            const keysListElem = document.getElementById('keys-list');
            
            try {
              // Get ID token for authentication
              const idToken = await user.getIdToken();
              
              // Fetch API keys from server
              const response = await fetch('/api-keys', {
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
              }
              
              const data = await response.json();
              
              // Hide loading indicator
              loadingElem.style.display = 'none';
              
              if (data.status === 'success') {
                if (data.count === 0) {
                  // No keys found
                  noKeysElem.style.display = 'block';
                  keysTableElem.style.display = 'none';
                } else {
                  // Display keys
                  noKeysElem.style.display = 'none';
                  keysTableElem.style.display = 'table';
                  
                  // Clear existing list
                  keysListElem.innerHTML = '';
                  
                  // Add each key to the table
                  data.api_keys.forEach(key => {
                    const row = document.createElement('tr');
                    
                    // Format dates
                    const createdDate = key.created_at ? new Date(key.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
                    const expiresDate = key.expires_at ? new Date(key.expires_at._seconds * 1000).toLocaleDateString() : 'N/A';
                    
                    // Status badge
                    const statusBadge = key.active 
                      ? '<span class="badge-active">Active</span>'
                      : '<span class="badge-inactive">Inactive</span>';
                    
                    row.innerHTML = `
                      <td>${key.name || 'Unnamed Key'}</td>
                      <td>${createdDate}</td>
                      <td>${expiresDate}</td>
                      <td>${statusBadge}</td>
                      <td>
                        ${key.active ? `<button class="btn-revoke" data-key-id="${key.key_id}">Revoke</button>` : ''}
                      </td>
                    `;
                    
                    keysListElem.appendChild(row);
                  });
                  
                  // Add event listeners to revoke buttons
                  document.querySelectorAll('.btn-revoke').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                      const keyId = e.target.getAttribute('data-key-id');
                      if (confirm('Are you sure you want to revoke this API key? This action cannot be undone.')) {
                        revokeApiKey(keyId);
                      }
                    });
                  });
                }
              } else {
                throw new Error(data.error || 'Failed to load API keys');
              }
            } catch (error) {
              console.error('Error loading API keys:', error);
              loadingElem.style.display = 'none';
              errorMessageElem.textContent = `Error: ${error.message}`;
              errorMessageElem.style.display = 'block';
            }
          }
          
          // Create API key
          async function createApiKey() {
            try {
              formError.style.display = 'none';
              
              // Get form values
              const name = document.getElementById('key-name').value;
              const description = document.getElementById('key-description').value;
              const expiryDays = document.getElementById('key-expiry').value;
              
              if (!name) {
                throw new Error('Please provide a name for your API key');
              }
              
              // Get current user
              const user = firebase.auth().currentUser;
              if (!user) {
                throw new Error('You must be logged in to create an API key');
              }
              
              // Get ID token for authentication
              const idToken = await user.getIdToken();
              
              // Create the API key
              const response = await fetch('/api-keys/create', {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`,
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  name: name,
                  description: description,
                  expires_days: parseInt(expiryDays, 10)
                })
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Close create modal
                createKeyModal.style.display = 'none';
                
                // Update usage example with the new key
                usageExample.textContent = usageExample.textContent.replace(/YOUR_API_KEY/g, data.api_key);
                
                // Display the API key
                apiKeyDisplay.textContent = data.api_key;
                displayKeyModal.style.display = 'block';
                
                // Reset form
                createKeyForm.reset();
                
                // Reload the API keys list
                loadApiKeys(user);
              } else {
                throw new Error(data.error || 'Failed to create API key');
              }
            } catch (error) {
              console.error('Error creating API key:', error);
              formError.textContent = error.message;
              formError.style.display = 'block';
            }
          }
          
          // Revoke API key
          async function revokeApiKey(keyId) {
            try {
              // Get current user
              const user = firebase.auth().currentUser;
              if (!user) {
                throw new Error('You must be logged in to revoke an API key');
              }
              
              // Get ID token for authentication
              const idToken = await user.getIdToken();
              
              // Revoke the API key
              const response = await fetch(`/api-keys/${keyId}/revoke`, {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${idToken}`
                }
              });
              
              if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
              }
              
              const data = await response.json();
              
              if (data.status === 'success') {
                // Reload the API keys list
                loadApiKeys(user);
              } else {
                throw new Error(data.error || 'Failed to revoke API key');
              }
            } catch (error) {
              console.error('Error revoking API key:', error);
              alert(`Error: ${error.message}`);
            }
          }
          
          // Start the page initialization when the DOM is ready
          document.addEventListener('DOMContentLoaded', initPage);
        </script>
      </body>
    </html>
    """,
    api_key=firebase_config["apiKey"],
    auth_domain=firebase_config["authDomain"],
    project_id=firebase_config["projectId"],
    storage_bucket=firebase_config.get("storageBucket", ""),
    messaging_sender_id=firebase_config.get("messagingSenderId", ""),
    app_id=firebase_config["appId"],
    server_url=request.url_root.rstrip('/'))  # Add server URL for examples

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
            
            # Don't return the full API key for security - mask it
            if 'api_key' in key_data:
                key_data['api_key'] = key_data['api_key'][:8] + '...'
                
            keys.append(key_data)
            
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
    """Create a new API key for the authenticated user"""
    # Get the authenticated user from the token
    user = authenticate_request(request)
    if not user or not user.get('email'):
        return jsonify({'error': 'User not properly authenticated'}), 401
    
    user_email = user.get('email')
    
    try:
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