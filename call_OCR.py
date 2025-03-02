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

try:
    from vouchervision_main.vouchervision.OCR_Gemini import OCRGeminiProVision
except:
    from vouchervision.OCR_Gemini import OCRGeminiProVision # type: ignore
    

def call_OCR(engine_options, path_img, double_OCR=False):
    # engine_options = ["gemini-1.5-pro","gemini-2.0-flash"]

    api_key = os.environ.get("API_KEY")  # Fetch API key from environment variables

    ocr_packet = {}
    ocr_packet["OCR"] = ""
    
    for ocr_opt in engine_options:
        ocr_packet[ocr_opt] = {}

        OCR_Engine = OCRGeminiProVision(api_key, 
                                        model_name=ocr_opt, 
                                        max_output_tokens=1024, 
                                        temperature=0.5, 
                                        top_p=0.3, 
                                        top_k=3, 
                                        seed=123456, 
                                        do_resize_img=False)
        
        response, cost_in, cost_out, total_cost, rates_in, rates_out, tokens_in, tokens_out = OCR_Engine.ocr_gemini(path_img, temperature=1, top_k=1, top_p=0)
        
        # print(response)
        
        ocr_packet[ocr_opt]["ocr_text"] = response
        ocr_packet[ocr_opt]["cost_in"] = cost_in
        ocr_packet[ocr_opt]["cost_out"] = cost_out
        ocr_packet[ocr_opt]["total_cost"] = total_cost
        ocr_packet[ocr_opt]["rates_in"] = rates_in
        ocr_packet[ocr_opt]["rates_out"] = rates_out
        ocr_packet[ocr_opt]["tokens_in"] = tokens_in
        ocr_packet[ocr_opt]["tokens_out"] = tokens_out

        # Update the OCR string
        if double_OCR:
            ocr_packet["OCR"] += f"\n{ocr_opt} OCR:\n{response}" * 2
        else:
            ocr_packet["OCR"] += f"\n{ocr_opt} OCR:\n{response}"

    return ocr_packet

if __name__ == "__main__":
    ocr_packet = call_OCR(["gemini-1.5-pro","gemini-2.0-flash"], 
                          "D:/Dropbox/VoucherVision/demo/demo_images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg",
                          double_OCR=False)
    print(ocr_packet)

    ocr_packet = call_OCR(["gemini-1.5-pro","gemini-2.0-flash"], 
                          "D:/Dropbox/VoucherVision/demo/demo_images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg",
                          double_OCR=True)
    print(ocr_packet)