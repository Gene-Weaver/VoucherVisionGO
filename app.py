import os
import sys
import json
import tempfile
import threading
from flask import Flask, request, jsonify
import logging
from werkzeug.utils import secure_filename
from collections import OrderedDict

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
    from vouchervision_main.vouchervision.directory_structure_VV import Dir_Structure
    from vouchervision_main.vouchervision.LM2_logger import start_logging
    from vouchervision_main.vouchervision.vouchervision_main import load_custom_cfg
    from vouchervision_main.vouchervision.data_project import Project_Info
    from vouchervision_main.vouchervision.utils_VoucherVision import VoucherVision
    from vouchervision_main.vouchervision.LLM_GoogleGemini import GoogleGeminiHandler
    from vouchervision_main.vouchervision.model_maps import ModelMaps
    from vouchervision_main.vouchervision.general_utils import calculate_cost
except:
    from vouchervision.OCR_Gemini import OCRGeminiProVision # type: ignore
    from vouchervision.directory_structure_VV import Dir_Structure # type: ignore
    from vouchervision.LM2_logger import start_logging # type: ignore
    from vouchervision.vouchervision_main import load_custom_cfg # type: ignore
    from vouchervision.data_project import Project_Info # type: ignore
    from vouchervision.utils_VoucherVision import VoucherVision # type: ignore
    from vouchervision.LLM_GoogleGemini import GoogleGeminiHandler # type: ignore
    from vouchervision.model_maps import ModelMaps # type: ignore
    from vouchervision.general_utils import calculate_cost # type: ignore

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
    
    def process_image_request(self, file, engine_options=None, prompt=None):
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
                if not engine_options:
                    engine_options = ["gemini-1.5-pro", "gemini-2.0-flash"]
                
                # Use default prompt if none specified
                current_prompt = prompt if prompt else self.default_prompt
                logger.info(f"Using prompt file: {current_prompt}")
                
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

# Initialize processor once at startup
try:
    processor = VoucherVisionProcessor()
    app.config['processor'] = processor
    logger.info("VoucherVision processor initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize VoucherVision processor: {str(e)}")
    raise

@app.route('/process', methods=['POST'])
def process_image():
    """API endpoint to process an image"""
    # Check if file is present in the request
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    # Get engine options from request if specified
    engine_options = request.form.getlist('engines') or None

    # Get prompt from request if specified, otherwise None (use default)
    prompt = request.form.get('prompt') or None
    
    # Process the image using the initialized processor
    results, status_code = app.config['processor'].process_image_request(file, engine_options, prompt)
    
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

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)