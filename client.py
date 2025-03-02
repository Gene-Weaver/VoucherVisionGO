import os
import sys
import json
import argparse
import requests
from pprint import pprint

def process_image(server_url, image_path, engines=None):
    """
    Process an image using the VoucherVision API server
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_path (str): Path to the image file or URL of the image
        engines (list): List of OCR engine options to use
        
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
            return process_image(server_url, temp_file_path, engines)
        finally:
            # Clean up the temporary file
            os.remove(temp_file_path)
    
    # Prepare the request data
    url = f"{server_url}/process"
    
    # Prepare the multipart form data
    files = {'file': open(image_path, 'rb')}
    
    # Add engine options if provided
    data = {}
    if engines:
        data = {'engines': engines}
    
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

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='VoucherVision Client')
    parser.add_argument('--server', required=True, 
                        help='URL of the VoucherVision API server (e.g., http://localhost:8080)')
    parser.add_argument('--image', required=True, 
                        help='Path to the image file or URL of the image to process')
    parser.add_argument('--engines', nargs='+', default=["gemini-1.5-pro", "gemini-2.0-flash"],
                        help='OCR engine options to use (default: gemini-1.5-pro gemini-2.0-flash)')
    parser.add_argument('--output', 
                        help='Path to save the output JSON results (optional)')
    
    args = parser.parse_args()
    
    try:
        # Process the image
        results = process_image(args.server, args.image, args.engines)
        
        # Print a summary of the results
        print("\n----- RESULTS SUMMARY -----")
        
        # Print OCR summary
        print("\nOCR Results:")
        for engine in results['ocr_results']:
            if engine != "OCR":  # Skip the combined OCR text
                print(f"  {engine}:")
                print(f"    Tokens: {results['ocr_results'][engine].get('tokens_in', 0)} in, "
                      f"{results['ocr_results'][engine].get('tokens_out', 0)} out")
                print(f"    Cost: ${results['ocr_results'][engine].get('total_cost', 0):.6f}")
        
        # Print VoucherVision summary (just a few key fields)
        vv_results = results.get('vouchervision_results', {})
        print("\nVoucherVision Results:")
        
        # Try to extract some key information if available
        scientific_name = vv_results.get('scientificName', 'Not identified')
        print(f"  Scientific Name: {scientific_name}")
        
        family = vv_results.get('family', 'Not identified')
        print(f"  Family: {family}")
        
        collection = vv_results.get('collectionCode', 'Not identified')
        print(f"  Collection: {collection}")
        
        catalog_number = vv_results.get('catalogNumber', 'Not identified')
        print(f"  Catalog Number: {catalog_number}")
        
        print(f"\nTotal Tokens: {results['tokens']['input']} in, {results['tokens']['output']} out")
        
        # Save the full results to a file if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nFull results saved to: {args.output}")
        else:
            # Ask if the user wants to see the full details
            choice = input("\nShow full details? (y/n): ")
            if choice.lower() == 'y':
                print("\n----- FULL RESULTS -----")
                pprint(results)
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()