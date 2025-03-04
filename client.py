import os
import sys
import json
import time
import argparse
import requests
import glob
import csv
import tempfile
import pandas as pd
import concurrent.futures
from collections import OrderedDict

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
            results = json.loads(response.text, object_pairs_hook=OrderedDict)
            # If vvgo_json is a string that contains JSON, parse it with OrderedDict
            if 'vvgo_json' in results and isinstance(results['vvgo_json'], str):
                try:
                    # Try to parse it as JSON with order preserved
                    results['vvgo_json'] = json.loads(results['vvgo_json'], object_pairs_hook=OrderedDict)
                except json.JSONDecodeError:
                    # Not valid JSON, leave as string
                    pass
            return results
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

def process_image_file(server_url, image_path, engines, prompt, output_dir, verbose):
    """
    Process a single image file and save the results
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_path (str): Path to the image file or URL
        engines (list): List of OCR engine options to use
        prompt (str): Custom prompt file to use
        output_dir (str): Directory to save output files
        verbose (bool): Whether to print verbose output
        
    Returns:
        dict: The processing results
    """
    try:
        # Process the image
        results = process_image(server_url, image_path, engines, prompt)
        
        # Generate output filename
        output_file = get_output_filename(image_path, output_dir)
        
        # Print summary of results if verbose is enabled
        if verbose:
            print_results_summary(results)
        else:
            print(f"Processed: {image_path}")
        
        # Save the results
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, sort_keys=False)
        
        print(f"Results saved to: {output_file}")
        return results
    
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None

def process_images_parallel(server_url, image_paths, engines, prompt, output_dir, verbose, max_workers=4):
    """
    Process multiple images in parallel
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_paths (list): List of paths to image files or URLs
        engines (list): List of OCR engine options to use
        prompt (str): Custom prompt file to use
        output_dir (str): Directory to save output files
        verbose (bool): Whether to print verbose output
        max_workers (int): Maximum number of parallel workers
        
    Returns:
        list: List of processing results
    """
    results = []
    
    print(f"Processing {len(image_paths)} images with up to {max_workers} parallel workers")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a dictionary mapping futures to their corresponding file paths
        future_to_path = {
            executor.submit(
                process_image_file, 
                server_url, 
                path, 
                engines, 
                prompt, 
                output_dir, 
                verbose
            ): path for path in image_paths
        }
        
        # Process as they complete
        for future in concurrent.futures.as_completed(future_to_path):
            path = future_to_path[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                print(f"Error processing {path}: {e}")
    
    return results

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

def get_output_filename(input_path, output_dir=None):
    """
    Generate an output filename based on the input file path
    
    Args:
        input_path (str): Path to the input file
        output_dir (str): Directory to save the output file (optional)
        
    Returns:
        str: Path to the output file
    """
    # Extract the base filename without extension
    if input_path.startswith(('http://', 'https://')):
        # For URLs, use the last part of the URL as the filename
        base_name = os.path.basename(input_path).split('?')[0]  # Remove query params if any
    else:
        base_name = os.path.basename(input_path)
    
    # Replace the extension with .json
    name_without_ext = os.path.splitext(base_name)[0]
    output_filename = f"{name_without_ext}.json"
    
    # If output directory is specified, join it with the filename
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, output_filename)
    
    return output_filename

def read_file_list(list_file):
    """
    Read a list of file paths or URLs from a file
    
    Args:
        list_file (str): Path to the file containing the list
        
    Returns:
        list: List of file paths or URLs
    """
    file_paths = []
    
    # Check file extension
    ext = os.path.splitext(list_file)[1].lower()
    
    if ext == '.csv':
        # Handle CSV file
        with open(list_file, 'r', newline='') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if row and row[0].strip():  # Skip empty rows
                    file_paths.append(row[0].strip())
    else:
        # Handle text file (one path per line)
        with open(list_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    file_paths.append(line)
    
    return file_paths

def save_results_to_csv(results_list, output_dir):
    """
    Save a list of VoucherVision results to a CSV file
    
    Args:
        results_list (list): List of dictionaries containing the results
        output_dir (str): Directory to save the CSV file
    """
    if not results_list:
        print("No results to save to CSV")
        return
    
    # Extract vvgo_json from each result
    vvgo_data = [result.get('vvgo_json', {}) for result in results_list if result and 'vvgo_json' in result]
    
    if not vvgo_data:
        print("No VoucherVision JSON data found in results")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(vvgo_data)
    
    # Save to CSV
    csv_path = os.path.join(output_dir, 'results.csv')
    df.to_csv(csv_path, index=False)
    print(f"\nCombined results saved to CSV: {csv_path}")
    print(f"Total records: {len(df)}")
    
    # Print column names for verification
    if not df.empty:
        print(f"CSV columns: {', '.join(df.columns.tolist())}")
    
def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='VoucherVisionGO Client')
    parser.add_argument('--server', required=True, 
                        help='URL of the VoucherVision API server (e.g., http://localhost:8080)')
    
    # Create a mutually exclusive group for input sources
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--image', 
                             help='Path to a single image file or URL to process')
    input_group.add_argument('--directory',
                             help='Path to a directory containing images to process')
    input_group.add_argument('--file-list',
                             help='Path to a file containing a list of image paths or URLs (one per line or CSV)')
    
    parser.add_argument('--engines', nargs='+', default=["gemini-1.5-pro", "gemini-2.0-flash"],
                        help='OCR engine options to use (default: gemini-1.5-pro gemini-2.0-flash)')
    parser.add_argument('--prompt', default="SLTPvM_default.yaml",
                        help='Custom prompt file to use (default: SLTPvM_default.yaml)')
    parser.add_argument('--output-dir', required=True,
                        help='Directory to save the output JSON results')
    parser.add_argument('--verbose', action='store_true',
                        help='Print all output to console')
    parser.add_argument('--save-to-csv', action='store_true',
                        help='Save all vvgo_json results to a CSV file in the output directory')
    parser.add_argument('--max-workers', type=int, default=4,
                        help='Maximum number of parallel workers (default: 4)')
    
    args = parser.parse_args()
    
    # Ensure max_workers is no more than 4
    max_workers = min(args.max_workers, 32)
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # Start timing
    start_time = time.time()
    
    try:
        # To store all results if save-to-csv is enabled
        all_results = []
        
        # Process based on the input type
        if args.image:
            # Single image (no need for parallelization)
            result = process_image_file(args.server, args.image, args.engines, args.prompt, args.output_dir, args.verbose)
            if result and args.save_to_csv:
                all_results.append(result)
        
        elif args.directory:
            # Directory of images - use parallel processing
            if not os.path.isdir(args.directory):
                raise ValueError(f"Directory not found: {args.directory}")
            
            # Get all image files in the directory
            image_extensions = ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.gif']
            image_files = []

            for ext in image_extensions:
                # Just use the lowercase extension - Windows is case-insensitive anyway
                image_files.extend(glob.glob(os.path.join(args.directory, f"*{ext}")))

            # Remove duplicates using lowercase comparison
            seen = set()
            unique_files = []
            for file in image_files:
                lowercase_path = file.lower()
                if lowercase_path not in seen:
                    seen.add(lowercase_path)
                    unique_files.append(file)

            image_files = unique_files
            print(f"Found {len(image_files)} unique image files to process")

            if not image_files:
                print(f"No image files found in {args.directory}")
                return
            
            print(f"Found {len(image_files)} image files to process")
            
            # Process images in parallel
            results = process_images_parallel(
                args.server, 
                image_files, 
                args.engines, 
                args.prompt, 
                args.output_dir, 
                args.verbose,
                max_workers
            )
            
            if args.save_to_csv:
                all_results.extend(results)
        
        elif args.file_list:
            # List of image paths or URLs from a file - use parallel processing
            file_paths = read_file_list(args.file_list)
            
            if not file_paths:
                print(f"No file paths found in {args.file_list}")
                return
            
            print(f"Found {len(file_paths)} paths to process")
            
            # Process files in parallel
            results = process_images_parallel(
                args.server, 
                file_paths, 
                args.engines, 
                args.prompt, 
                args.output_dir, 
                args.verbose,
                max_workers
            )
            
            if args.save_to_csv:
                all_results.extend(results)
        
        # Save to CSV if requested
        if args.save_to_csv:
            save_results_to_csv(all_results, args.output_dir)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    # End timing and report
    end_time = time.time()
    elapsed_seconds = end_time - start_time
    minutes, seconds = divmod(elapsed_seconds, 60)
    print(f"\n{'-' * 40}")
    print(f"Total operation time: {int(minutes)} minutes and {int(seconds)} seconds")
    print(f"{'-' * 40}")

if __name__ == "__main__":
    main()

# Usage examples:
# Single image:
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --image "./demo/images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg" --output-dir "./demo/results_single_image" --verbose

# URL image:
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --image "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg" --output-dir "./demo/results_single_url" --verbose

# Directory of images:
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --directory "./demo/images" --output-dir "./demo/results_dir_images" --verbose --max-workers 4
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --directory "./demo/images" --output-dir "./demo/results_dir_images_custom_prompt_save_to_csv" --verbose --prompt "SLTPvM_default_chromosome.yaml" --max-workers 4

# List of files:
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --file-list "./demo/csv/file_list.csv" --output-dir "./demo/results_file_list_csv" --verbose --max-workers 2
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --file-list "./demo/txt/file_list.txt" --output-dir "./demo/results_file_list_txt" --verbose --max-workers 4

# Custom prompt:
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --image "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg" --output-dir "./demo/results_single_image_custom_prompt" --verbose --prompt "SLTPvM_default_chromosome.yaml"

# Save results to CSV:
# python client.py --server https://vouchervision-go-738307415303.us-central1.run.app --directory ./demo/images --output-dir "./demo/results_dir_images_save_to_csv" --save-to-csv