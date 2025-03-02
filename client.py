import os
import sys
import json
import argparse
import requests
from pprint import pprint

def process_image(server_url, image_path, engines=None, prompt=None):
    """
    Process an image using the VoucherVision API server
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_path (str): Path to the image file or URL of the image
        engines (list): List of OCR engine options to use
        prompt (str): Custom prompt file to use
        
    Returns:
        dict: The processed results from the server
    """
    # Check if the image path is a URL or a local file
    if image_path.startswith(('http://', 'https://')):
        # For URL-based images, download them first or let the server handle it
        print(f"Processing image from URL: {image_path}")
        response = requests.get(image_path)
        if response.status_code != 200:
            raise Exception(f"Failed to download image from URL: {response.status_code}")
        
        # Save to a temp file
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(response.content)
        
        try:
            return process_image(server_url, temp_file_path, engines, prompt)
        finally:
            # Clean up the temporary file
            os.remove(temp_file_path)
    
    # Prepare the request data
    url = f"{server_url}/process"
    
    # Prepare the multipart form data
    files = {'file': open(image_path, 'rb')}
    
    # Add engine options and prompt if provided
    data = {}
    if engines:
        data['engines'] = engines
    if prompt:
        data['prompt'] = prompt
    
    try:
        # Send the request
        print(f"Sending request to {url}")
        response = requests.post(url, files=files, data=data)
        
        # Check if the request was successful
        if response.status_code == 200:
            return response.json()
        else:
            error_msg = f"Error: {response.status_code}"
            try:
                error_details = response.json()
                error_msg += f" - {error_details.get('error', 'Unknown error')}"
            except:
                error_msg += f" - {response.text}"
            raise Exception(error_msg)
    
    finally:
        # Close the file
        files['file'].close()

def print_results_summary(results):
    """
    Print a summary of the VoucherVision processing results
    
    Args:
        results (dict): The processing results from the server
    """
    print("\n----- RESULTS SUMMARY -----")
    
    # Print OCR summary
    print("\nOCR Info:")
    for engine in results['ocr_results']:
        if engine != "OCR":  # Skip the combined OCR text
            print(f"  {engine}:")
            print(f"    Tokens: {results['ocr_results'][engine].get('tokens_in', 0)} in, "
                  f"{results['ocr_results'][engine].get('tokens_out', 0)} out")
            print(f"    Cost: ${results['ocr_results'][engine].get('total_cost', 0):.6f}")
    
    print("\nOCR:")
    print(results['ocr_results']["OCR"])

    # Updated to use tokens_LLM instead of tokens
    llm_tokens = results.get('tokens_LLM', {'input': 0, 'output': 0})
    print(f"\nLLM Tokens: {llm_tokens['input']} in, {llm_tokens['output']} out")
    
    # Print VoucherVision summary
    vv_results = results.get('vvgo_json', {})
    print("\nVoucherVision JSON:")
    print(json.dumps(vv_results, indent=2, sort_keys=False))

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='VoucherVisionGO Client')
    parser.add_argument('--server', required=True, 
                        help='URL of the VoucherVision API server (e.g., http://localhost:8080)')
    parser.add_argument('--image', required=True, 
                        help='Path to the image file or URL of the image to process')
    parser.add_argument('--engines', nargs='+', default=["gemini-1.5-pro", "gemini-2.0-flash"],
                        help='OCR engine options to use (default: gemini-1.5-pro gemini-2.0-flash)')
    parser.add_argument('--prompt', default="SLTPvM_default.yaml",
                        help='Custom prompt file to use (default: SLTPvM_default.yaml)')
    parser.add_argument('--output', 
                        help='Path to save the output JSON results (optional)')
    parser.add_argument('--verbose', action='store_true',
                        help='Print all output to console')
    
    args = parser.parse_args()
    
    try:
        # Process the image
        results = process_image(args.server, args.image, args.engines, args.prompt)
        
        # Print summary of results if verbose is enabled
        if args.verbose:
            print_results_summary(results)
        
        # Save the full results to a file if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, sort_keys=False)
            print(f"\nFull results saved to: {args.output}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

    # python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --image "D:/Dropbox/VoucherVision/demo/demo_images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg" --output results.json --verbose
    # python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --image "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg" --output results.json --verbose