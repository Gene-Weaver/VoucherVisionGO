import os, inspect, sys

# Get the absolute path of the submodule
submodule_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "vouchervision_main"))

# Ensure it's in sys.path
if submodule_path not in sys.path:
    sys.path.insert(0, submodule_path)
    
from vouchervision_main.vouchervision.vouchervision_main import voucher_vision, load_custom_cfg

def vvgo():
    config_file = os.path.join(os.path.dirname(__file__), 'VoucherVision.yaml')
        
    # Validate config file exists
    if not os.path.exists(config_file):
        print(f"Error: Configuration file not found at {config_file}")
        sys.exit(1)

    # Load configuration
    cfg = load_custom_cfg(config_file)
    dir_home = submodule_path #os.path.dirname(os.path.dirname(os.path.dirname(inspect.getfile(load_custom_cfg))))
    path_custom_prompts = os.path.join(dir_home, 'custom_prompts', cfg['leafmachine']['project']['prompt_version'])

    result = voucher_vision(
        cfg_file_path=cfg,
        dir_home=dir_home,
        path_custom_prompts=path_custom_prompts,
        cfg_test=None,
        progress_report=None,
        json_report=False,
        path_api_cost=os.path.join(dir_home, 'api_cost', 'api_cost.yaml'),
        test_ind=None,
        is_hf=False,
        is_real_run=False # True is for streamlit GUI
    )

if __name__ == "__main__":
    vvgo()