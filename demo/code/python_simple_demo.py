import os 
from client_dep2 import process_vouchers

# USE AN ENV VARIABLE
YOUR_API_KEY_OR_AUTH_TOKEN = os.getenv('VV_API_KEY')
IMAGE_URL = "https://swbiodiversity.org/imglib/seinet/sernec/EKY/31234100396/31234100396116.jpg"
DIR_TO_PROCESS = "D:/Dropbox/VoucherVisionGO/demo/images"

if __name__ == '__main__':
	process_vouchers(server="https://vouchervision-go-738307415303.us-central1.run.app", 
		output_dir="./output_single_url", 
		prompt="SLTPvM_geolocate_flag_multispecimen.yaml",#"SLTPvM_default_v2.yaml", 
		image=IMAGE_URL, 
		directory=None, 
		file_list=None, 
		verbose=True, 
		save_to_csv=True, 
		max_workers=4,
		ocr_only=False,
		engines=["gemini-2.0-flash-lite", "gemini-2.0-flash"], # "gemini-1.5-pro", "gemini-2.0-flash", "gemini-2.5", "gemini-2.5-pro"
		llm_model="gemini-2.5-pro", # "gemini-2.0-flash"
		auth_token=YOUR_API_KEY_OR_AUTH_TOKEN
	)

	process_vouchers(server="https://vouchervision-go-738307415303.us-central1.run.app", 
		output_dir="./output_multiple_local", 
		prompt="SLTPvM_geolocate_flag_multispecimen.yaml",#"SLTPvM_default_v2.yaml", 
		image=None, 
		directory=DIR_TO_PROCESS, 
		file_list=None, 
		verbose=True, 
		save_to_csv=True, 
		ocr_only=False,
		llm_model="gemini-2.5-pro",
		max_workers=8,
		# engines=["gemini-1.5-pro", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
		engines=["gemini-2.0-flash", "gemini-2.5-pro"],
		auth_token=YOUR_API_KEY_OR_AUTH_TOKEN
	)

