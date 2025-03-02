import os
import json
import tempfile
from flask import Flask, request, jsonify
import logging
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup paths and imports
import sys
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
except:
    from vouchervision.OCR_Gemini import OCRGeminiProVision # type: ignore
    from vouchervision.directory_structure_VV import Dir_Structure # type: ignore
    from vouchervision.LM2_logger import start_logging # type: ignore
    from vouchervision.vouchervision_main import load_custom_cfg # type: ignore
    from vouchervision.data_project import Project_Info # type: ignore
    from vouchervision.utils_VoucherVision import VoucherVision # type: ignore
    from vouchervision.LLM_GoogleGemini import GoogleGeminiHandler # type: ignore
    from vouchervision.model_maps import ModelMaps # type: ignore

class VoucherVisionProcessor:
    """
    Class to handle VoucherVision processing with initialization done once.
    """
    def __init__(self):
        # Configuration
        self.ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'tif', 'tiff'}
        self.MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB max upload size
        
        # Get API key for Gemini
        self.api_key = self._get_api_key()
        
        # Initialize OCR engines 
        self.ocr_engines = {}
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
        
        self.Dirs = Dir_Structure(self.cfg)
        # self.logger = start_logging(self.Dirs, self.cfg)
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.dir_home = os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main"))
        self.Project = Project_Info(self.cfg, self.logger, self.dir_home, self.Dirs)

        self.Voucher_Vision = VoucherVision(
            self.cfg, self.logger, self.dir_home, None, self.Project, self.Dirs, 
            is_hf=False, skip_API_keys=True
        )

        self.Voucher_Vision.initialize_token_counters()
        self.Voucher_Vision.path_custom_prompts = os.path.join(
            self.dir_home, 'custom_prompts', 
            self.cfg['leafmachine']['project']['prompt_version']
        )
        
        # Initialize LLM model handler
        self.model_name = ModelMaps.get_API_name(self.Voucher_Vision.model_name)
        self.Voucher_Vision.setup_JSON_dict_structure()
        
        self.llm_model = GoogleGeminiHandler(
            self.cfg, self.logger, self.model_name, self.Voucher_Vision.JSON_dict_structure, 
            config_vals_for_permutation=None, exit_early_for_JSON=True
        )
    
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
        ocr_packet["OCR"] = ""
        
        for ocr_opt in engine_options:
            ocr_packet[ocr_opt] = {}
            
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
            response, cost_in, cost_out, total_cost, rates_in, rates_out, tokens_in, tokens_out = OCR_Engine.ocr_gemini(file_path)
            
            ocr_packet[ocr_opt]["ocr_text"] = response
            ocr_packet[ocr_opt]["cost_in"] = cost_in
            ocr_packet[ocr_opt]["cost_out"] = cost_out
            ocr_packet[ocr_opt]["total_cost"] = total_cost
            ocr_packet[ocr_opt]["rates_in"] = rates_in
            ocr_packet[ocr_opt]["rates_out"] = rates_out
            ocr_packet[ocr_opt]["tokens_in"] = tokens_in
            ocr_packet[ocr_opt]["tokens_out"] = tokens_out

            ocr_packet["OCR"] += f"\n{ocr_opt} OCR:\n{response}"

        return ocr_packet
    
    def process_voucher_vision(self, ocr_text):
        """Process the OCR text with VoucherVision"""
        # Update OCR text for processing
        self.Voucher_Vision.OCR = ocr_text
        prompt = self.Voucher_Vision.setup_prompt()
        
        # Call the LLM to process the OCR text (using pre-initialized model)
        response_candidate, nt_in, nt_out, _, _, _ = self.llm_model.call_llm_api_GoogleGemini(
            prompt, json_report=None, paths=None
        )

        return response_candidate, nt_in, nt_out
    
    def process_image_request(self, file, engine_options=None):
        """Process an image from a request file"""
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
            
            # Perform OCR
            ocr_results = self.perform_ocr(file_path, engine_options)
            
            # Process with VoucherVision
            vv_results, tokens_in, tokens_out = self.process_voucher_vision(ocr_results["OCR"])
            
            # Combine results
            results = {
                "ocr_results": ocr_results,
                "vouchervision_results": vv_results,
                "tokens": {
                    "input": tokens_in,
                    "output": tokens_out
                }
            }
            
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


# Initialize Flask app
app = Flask(__name__)

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
    
    # Process the image using the initialized processor
    results, status_code = app.config['processor'].process_image_request(file, engine_options)
    
    return jsonify(results), status_code

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)