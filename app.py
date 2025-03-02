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
# Ensure project root is in sys.path (for package resolution)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# Add the `vouchervision_main` directory
submodule_path = os.path.join(project_root, "vouchervision_main")
if submodule_path not in sys.path:
    sys.path.insert(0, submodule_path)
# Add `vouchervision` directory so internal module imports work
vouchervision_path = os.path.join(submodule_path, "vouchervision")
if vouchervision_path not in sys.path:
    sys.path.insert(0, vouchervision_path)
# Ensure `OCR_Gemini.py` can find `OCR_resize_for_VLMs.py`
component_detector_path = os.path.join(vouchervision_path, "component_detector")
if component_detector_path not in sys.path:
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

app = Flask(__name__)

# Configuration
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'tif', 'tiff'}
MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB max upload size

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_api_key():
    """Get API key from environment variable"""
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise ValueError("API_KEY environment variable not set")
    return api_key

def perform_ocr(file_path, engine_options):
    """Perform OCR on the provided image"""
    api_key = get_api_key()
    
    ocr_packet = {}
    ocr_packet["OCR"] = ""
    
    for ocr_opt in engine_options:
        ocr_packet[ocr_opt] = {}

        OCR_Engine = OCRGeminiProVision(
            api_key, 
            model_name=ocr_opt, 
            max_output_tokens=1024, 
            temperature=0.5, 
            top_p=0.3, 
            top_k=3, 
            seed=123456, 
            do_resize_img=False
        )
        
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

def process_voucher_vision(ocr_text):
    """Process the OCR text with VoucherVision"""
    config_file = os.path.join(os.path.dirname(__file__), 'VoucherVision.yaml')
    
    # Validate config file exists
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file not found at {config_file}")

    # Load configuration
    cfg = load_custom_cfg(config_file)
    
    Dirs = Dir_Structure(cfg)
    logger = start_logging(Dirs, cfg)
    dir_home = os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main"))
    Project = Project_Info(cfg, logger, dir_home, Dirs)

    Voucher_Vision = VoucherVision(
        cfg, logger, dir_home, None, Project, Dirs, 
        is_hf=False, skip_API_keys=True
    )

    Voucher_Vision.initialize_token_counters()
    Voucher_Vision.path_custom_prompts = os.path.join(
        dir_home, 'custom_prompts', 
        cfg['leafmachine']['project']['prompt_version']
    )

    # Set OCR text and prepare for processing
    Voucher_Vision.OCR = ocr_text
    prompt = Voucher_Vision.setup_prompt()
    Voucher_Vision.setup_JSON_dict_structure()
    model_name = ModelMaps.get_API_name(Voucher_Vision.model_name)

    llm_model = GoogleGeminiHandler(
        cfg, logger, model_name, Voucher_Vision.JSON_dict_structure, 
        config_vals_for_permutation=None, exit_early_for_JSON=True
    )

    # Call the LLM to process the OCR text
    response_candidate, nt_in, nt_out, _, _, _ = llm_model.call_llm_api_GoogleGemini(
        prompt, json_report=None, paths=None
    )

    return response_candidate, nt_in, nt_out

@app.route('/process', methods=['POST'])
def process_image():
    """API endpoint to process an image"""
    # Check if file is present in the request
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    # Check if the file is valid
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': f'File type not allowed. Supported types: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
    
    # Save uploaded file to a temporary location
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, secure_filename(file.filename))
    file.save(file_path)
    
    try:
        # Get engine options (default to gemini models if not specified)
        engine_options = request.form.getlist('engines') or ["gemini-1.5-pro", "gemini-2.0-flash"]
        
        # Perform OCR
        ocr_results = perform_ocr(file_path, engine_options)
        
        # Process with VoucherVision
        vv_results, tokens_in, tokens_out = process_voucher_vision(ocr_results["OCR"])
        
        # Combine results
        results = {
            "ocr_results": ocr_results,
            "vouchervision_results": vv_results,
            "tokens": {
                "input": tokens_in,
                "output": tokens_out
            }
        }
        
        return jsonify(results), 200
    
    except Exception as e:
        logger.exception("Error processing request")
        return jsonify({'error': str(e)}), 500
    
    finally:
        # Clean up the temporary file
        try:
            os.remove(file_path)
            os.rmdir(temp_dir)
        except:
            pass

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)