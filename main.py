import os
import sys
from vouchervision_main.


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