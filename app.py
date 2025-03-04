import os
import sys
import json
import tempfile
import threading
from flask import Flask, request, jsonify, render_template_string
import logging
from werkzeug.utils import secure_filename
from collections import OrderedDict
from pathlib import Path
import yaml
import re

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

@app.route('/prompts', methods=['GET'])
def list_prompts_api():
    """API endpoint to list all available prompt templates"""
    # Get prompt directory
    prompt_dir = os.path.join(project_root, "vouchervision_main", "custom_prompts")
    
    # Default to only listing prompts
    view_details = request.args.get('view', 'false').lower() == 'true'
    specific_prompt = request.args.get('prompt')
    
    # Get all YAML files
    prompt_files = []
    for ext in ['.yaml', '.yml']:
        prompt_files.extend(list(Path(prompt_dir).glob(f'*{ext}')))
    
    if not prompt_files:
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
            return jsonify({
                'status': 'success',
                'prompt': extract_prompt_details(target_file)
            })
        else:
            # Return error with list of available prompts
            return jsonify({
                'status': 'error',
                'message': f"Prompt file '{specific_prompt}' not found.",
                'available_prompts': [file.name for file in prompt_files]
            }), 404
    
    # Otherwise list all prompts
    prompt_info_list = []
    for file in prompt_files:
        info = extract_prompt_info(file)
        
        # If view_details is True, include the full prompt content
        if view_details:
            info['details'] = extract_prompt_details(file)
        
        prompt_info_list.append(info)
    
    return jsonify({
        'status': 'success',
        'count': len(prompt_files),
        'prompts': prompt_info_list
    })

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
        
        # Look for fields with specific names
        field_mapping = {
            'prompt_author': 'author',
            'prompt_author_institution': 'institution',
            'prompt_name': 'name',
            'prompt_version': 'version',
            'prompt_description': 'description'
        }
        
        # Extract values using regex
        for json_field, info_field in field_mapping.items():
            pattern = rf'{json_field}:\s*(.*?)(?=\n\w+:|$)'
            matches = re.findall(pattern, content, re.DOTALL)
            if matches:
                # Clean up the value (remove extra whitespace, join multi-line values)
                value = ' '.join([line.strip() for line in matches[0].strip().split('\n')])
                info[info_field] = value
        
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
    Extract detailed content from a prompt file
    
    Args:
        prompt_file (Path): Path to the prompt file
        
    Returns:
        dict: Dictionary with sections of the prompt
    """
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Initialize details dictionary
        details = {
            'raw_content': content,
            'sections': {}
        }
        
        # Try YAML parsing first
        try:
            data = yaml.safe_load(content)
            
            if isinstance(data, dict):
                # Store all sections from the YAML
                details['sections'] = data
            else:
                # Fallback to manual parsing
                raise ValueError("YAML parsing didn't produce a dictionary")
                
        except Exception:
            # Manual parsing for non-YAML format
            prompt_sections = {
                'SYSTEM_PROMPT': 'system_prompt',
                'USER_PROMPT': 'user_prompt',
                'EXAMPLES': 'examples',
                'FIELDS': 'fields'
            }
            
            # Try to find prompt sections
            lines = content.split('\n')
            current_section = None
            section_content = []
            
            for line in lines:
                # Check if this line starts a new section
                for section_key, section_name in prompt_sections.items():
                    if line.strip().startswith(section_key):
                        # Save the previous section if there was one
                        if current_section and section_content:
                            details['sections'][current_section] = '\n'.join(section_content)
                        
                        # Start new section
                        current_section = section_name
                        section_content = []
                        break
                else:
                    # Skip metadata lines
                    if line.strip().startswith(('PROMPT_AUTHOR:', 'PROMPT_AUTHOR_INSTITUTION:', 
                                            'PROMPT_NAME:', 'PROMPT_VERSION:', 'PROMPT_DESCRIPTION:')):
                        continue
                    
                    # If we're in a section, add this line to its content
                    if current_section:
                        section_content.append(line)
            
            # Save the last section
            if current_section and section_content:
                details['sections'][current_section] = '\n'.join(section_content)
        
        return details
    
    except Exception as e:
        logger.error(f"Error extracting details from {prompt_file}: {e}")
        return {'error': str(e)}

# HTML UI route for browsing prompts
@app.route('/prompts-ui', methods=['GET'])
def prompts_ui():
    """Web UI for browsing prompts"""
    html_template = """
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
        .modal { display: none; position: fixed; z-index: 1; left: 0; top: 0; width: 100%; height: 100%; 
               overflow: auto; background-color: rgba(0,0,0,0.4); }
        .modal-content { background-color: #fefefe; margin: 5% auto; padding: 20px; border: 1px solid #888; 
                        width: 80%; max-height: 80%; overflow: auto; }
        .close { color: #aaa; float: right; font-size: 28px; font-weight: bold; cursor: pointer; }
        .close:hover { color: black; }
        pre { background-color: #f8f8f8; padding: 10px; border-radius: 4px; overflow-x: auto; 
            white-space: pre-wrap; word-wrap: break-word; }
        .section-title { color: #2c3e50; margin-top: 15px; }
    </style>
</head>
<body>
    <h1>VoucherVision Prompt Templates</h1>
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
                <th>Institution</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="promptList">
            <!-- Prompts will be loaded here -->
        </tbody>
    </table>
    
    <div id="promptModal" class="modal">
        <div class="modal-content">
            <span class="close">&times;</span>
            <h2 id="modalTitle">Prompt Details</h2>
            <div id="promptDetails">
                <!-- Prompt details will be loaded here -->
            </div>
        </div>
    </div>
    
    <script>
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
                        
                        row.innerHTML = `
                            <td>${index + 1}</td>
                            <td>${prompt.filename}</td>
                            <td>${prompt.name}</td>
                            <td class="description">${prompt.description}</td>
                            <td>${prompt.version}</td>
                            <td>${prompt.author}</td>
                            <td>${prompt.institution}</td>
                            <td><button class="details-btn" data-filename="${prompt.filename}">View Details</button></td>
                        `;
                        
                        promptList.appendChild(row);
                    });
                    
                    // Add event listeners to the buttons
                    document.querySelectorAll('.details-btn').forEach(button => {
                        button.addEventListener('click', () => {
                            const filename = button.getAttribute('data-filename');
                            loadPromptDetails(filename);
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
        
        // Load prompt details
        function loadPromptDetails(filename) {
            fetch(`/prompts?prompt=${filename}`)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        const prompt = data.prompt;
                        document.getElementById('modalTitle').textContent = `Prompt: ${filename}`;
                        
                        let detailsHTML = `
                            <h3>Metadata</h3>
                            <table>
                                <tr><td><strong>Name:</strong></td><td>${data.prompt.name || filename}</td></tr>
                                <tr><td><strong>Description:</strong></td><td>${data.prompt.description || 'No description'}</td></tr>
                                <tr><td><strong>Version:</strong></td><td>${data.prompt.version || 'Unknown'}</td></tr>
                                <tr><td><strong>Author:</strong></td><td>${data.prompt.author || 'Unknown'}</td></tr>
                                <tr><td><strong>Institution:</strong></td><td>${data.prompt.institution || 'Unknown'}</td></tr>
                            </table>
                        `;
                        
                        // Add sections
                        if (prompt.details && prompt.details.sections) {
                            const sections = prompt.details.sections;
                            
                            // Common section names to display first and with specific formatting
                            const prioritySections = ['system_prompt', 'user_prompt', 'examples', 'fields'];
                            
                            // Add priority sections first
                            prioritySections.forEach(sectionKey => {
                                if (sections[sectionKey]) {
                                    const sectionTitle = sectionKey.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                                    detailsHTML += `<h3 class="section-title">${sectionTitle}</h3>`;
                                    detailsHTML += `<pre>${sections[sectionKey]}</pre>`;
                                    delete sections[sectionKey]; // Remove from object so we don't display twice
                                }
                            });
                            
                            // Add remaining sections
                            for (const [key, value] of Object.entries(sections)) {
                                if (key !== 'raw_content') {  // Skip raw content
                                    const sectionTitle = key.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                                    detailsHTML += `<h3 class="section-title">${sectionTitle}</h3>`;
                                    
                                    if (typeof value === 'object') {
                                        detailsHTML += `<pre>${JSON.stringify(value, null, 2)}</pre>`;
                                    } else {
                                        detailsHTML += `<pre>${value}</pre>`;
                                    }
                                }
                            }
                        } else if (prompt.details && prompt.details.raw_content) {
                            // Fallback to raw content
                            detailsHTML += `<h3 class="section-title">Raw Content</h3>`;
                            detailsHTML += `<pre>${prompt.details.raw_content}</pre>`;
                        }
                        
                        document.getElementById('promptDetails').innerHTML = detailsHTML;
                        document.getElementById('promptModal').style.display = 'block';
                    } else {
                        alert('Error: ' + data.message);
                    }
                })
                .catch(error => {
                    console.error('Error fetching prompt details:', error);
                    alert('Error loading prompt details: ' + error.message);
                });
        }
        
        // Close the modal when clicking the close button
        document.querySelector('.close').addEventListener('click', () => {
            document.getElementById('promptModal').style.display = 'none';
        });
        
        // Close the modal when clicking outside the content
        window.addEventListener('click', (event) => {
            if (event.target === document.getElementById('promptModal')) {
                document.getElementById('promptModal').style.display = 'none';
            }
        });
    </script>
</body>
</html>
    """
    return render_template_string(html_template)

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)