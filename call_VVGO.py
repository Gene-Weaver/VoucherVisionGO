import os, inspect, sys

# Get the absolute path to the project root
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

from call_OCR import call_OCR

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


def call_VVGO():
    config_file = os.path.join(os.path.dirname(__file__), 'VoucherVision.yaml')

    
    # Validate config file exists
    if not os.path.exists(config_file):
        print(f"Error: Configuration file not found at {config_file}")
        sys.exit(1)

    # Load configuration
    cfg = load_custom_cfg(config_file)
    
    Dirs = Dir_Structure(cfg)

    logger = start_logging(Dirs, cfg)

    dir_home = os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main"))

    Project = Project_Info(cfg, logger, dir_home, Dirs) # Where file names are modified



    Voucher_Vision = VoucherVision(cfg, logger, dir_home, None, Project, Dirs, is_hf=False, skip_API_keys=True)

    Voucher_Vision.initialize_token_counters()
    Voucher_Vision.path_custom_prompts = os.path.join(dir_home,'custom_prompts', cfg['leafmachine']['project']['prompt_version'])

    #### for each img

    ocr_packet = call_OCR(["gemini-1.5-pro","gemini-2.0-flash"], 
                        #   "D:/Dropbox/VoucherVision/demo/demo_images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg",
                        "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg",
                        double_OCR=False)
    # print(ocr_packet["OCR"])

    Voucher_Vision.OCR = ocr_packet["OCR"]
    prompt = Voucher_Vision.setup_prompt()
    Voucher_Vision.setup_JSON_dict_structure()
    model_name = ModelMaps.get_API_name(Voucher_Vision.model_name)

    llm_model = GoogleGeminiHandler(cfg, logger, model_name, Voucher_Vision.JSON_dict_structure, config_vals_for_permutation=None, exit_early_for_JSON=True)

    # output, nt_in, nt_out, None, None, None
    response_candidate, nt_in, nt_out, WFO_record, GEO_record, usage_report = llm_model.call_llm_api_GoogleGemini(prompt, json_report=None, paths=None)

    print(response_candidate)
    print(nt_in)
    print(nt_out)


if __name__ == "__main__":
    call_VVGO()