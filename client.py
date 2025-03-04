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
from termcolor import colored
from tabulate import tabulate
from tqdm import tqdm

N_SIZE=80
N_INDENT=2

class OrderedDictJSONEncoder(json.JSONEncoder):
    def encode(self, obj):
        if isinstance(obj, OrderedDict):
            # Convert OrderedDict to a list of tuples for ordered serialization
            return '{' + ','.join(f'"{k}":{self.encode(v)}' for k, v in obj.items()) + '}'
        return super().encode(obj)
    
def process_image(server_url, image_path, output_dir, verbose=False, engines=None, prompt=None):
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
        if verbose:
            print(f"Processing image from URL: {image_path}")
        response = requests.get(image_path)
        if response.status_code != 200:
            raise Exception(f"Failed to download image from URL: {response.status_code}")
        
        # Save to a temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(response.content)
        
        try:
            return process_image(server_url, temp_file_path, verbose, engines, prompt)
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
        if verbose:
            print(f"Sending request to {url}")
        response = requests.post(url, files=files, data=data)
        
        # Check if the request was successful
        if response.status_code == 200:
            results = json.loads(response.text, object_pairs_hook=OrderedDict)
            # If formatted_json is a string that contains JSON, parse it with OrderedDict
            if 'formatted_json' in results and isinstance(results['formatted_json'], str):
                output_file = get_output_filename(image_path, output_dir)
                fname = os.path.basename(output_file).split(".")[0]
                results['filename'] = fname
                try:
                    # Try to parse it as JSON with order preserved
                    results['formatted_json'] = json.loads(results['formatted_json'], object_pairs_hook=OrderedDict)
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
        results = process_image(server_url, image_path, output_dir, verbose, engines, prompt)
        
        # Generate output filename
        output_file = get_output_filename(image_path, output_dir)
        fname = os.path.basename(output_file).split(".")[0]

        # Print summary of results if verbose is enabled
        if verbose:
            print_results_summary(results, fname)
            print(f"Processed: {image_path}")
        
        # Save the results - ensure we preserve order
        with open(output_file, 'w') as f:
            # Use json.dump with an OrderedDict to preserve key order 
            json.dump(results, f, indent=2, sort_keys=False, 
                     cls=OrderedDictJSONEncoder)  # Use custom encoder
        
        if verbose:
            print(f"Individual results saved to: {output_file}")
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

    # Create a progress bar
    progress_bar = tqdm(total=len(image_paths), desc="Processing", unit="image")
    
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a dictionary mapping futures to their corresponding file paths
        # Verbose is forced off when using parallel, it's too messy in console print
        future_to_path = {
            executor.submit(
                process_image_file, 
                server_url, 
                path, 
                engines, 
                prompt, 
                output_dir, 
                False
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
                print(f"\nError processing {path}: {e}")
            finally:
                # Update the progress bar
                progress_bar.update(1)
    
    # Close the progress bar
    progress_bar.close()

    return results

def print_results_summary(results, fname):
    """
    Print a summary of the VoucherVision processing results with enhanced formatting.
    Dynamically determines fields from the JSON structure.
    
    Args:
        results (dict): The processing results from the server
    """
    from termcolor import colored
    from tabulate import tabulate
    import json
    
    print("\n" + "="*N_SIZE)
    print("VOUCHERVISION RESULTS SUMMARY", colored(f"{fname}", 'green', attrs=['bold']))
    print("="*N_SIZE)
    
    # Print top-level sections one by one
    for section_name, section_data in results.items():
        if section_name != "ocr":
            print(colored(f"{section_name.upper()}:", 'cyan', attrs=['bold']))

        if section_name == 'ocr_info':
            # Handle OCR results specially
            # Print engine summary table
            ocr_table = []
            total_cost = 0
            
            for engine, engine_data in section_data.items():
                tokens_in = engine_data.get('tokens_in', 0)
                tokens_out = engine_data.get('tokens_out', 0)
                cost = engine_data.get('total_cost', 0)
                total_cost += cost
                
                ocr_table.append([
                    engine,
                    f"{tokens_in:,}",
                    f"{tokens_out:,}",
                    f"${cost:.6f}"
                ])
            
            # Add total row if we have engine data
            if ocr_table:
                ocr_table.append([
                    colored("TOTAL", attrs=['bold']),
                    "",
                    "",
                    colored(f"${total_cost:.6f}", 'yellow', attrs=['bold'])
                ])
                
                print(tabulate(ocr_table, 
                              headers=['Engine', 'Tokens In', 'Tokens Out', 'Cost'],
                              tablefmt='grid'))
            
            # Print the OCR text
        elif section_name == 'ocr':
            print(colored("OCR Text:", 'magenta', attrs=['bold']))
            print(str(section_data))

        
        elif section_name == 'parsing_info':
            # Enhanced handling for tokens_LLM that now includes model, cost_in, and cost_out
            llm_table = []
            
            # Check if we have the enhanced structure or the basic one
            if isinstance(section_data, dict) and 'model' in section_data:
                # Enhanced structure with all fields
                model = section_data.get('model', '')
                tokens_in = section_data.get('input', 0)
                tokens_out = section_data.get('output', 0)
                cost_in = section_data.get('cost_in', 0)
                cost_out = section_data.get('cost_out', 0)
                total_cost = cost_in + cost_out
                
                # Add a row with all the data
                llm_table.append([
                    model,
                    f"{tokens_in:,}",
                    f"{tokens_out:,}",
                    f"${cost_in:.6f}",
                    f"${cost_out:.6f}",
                    colored(f"${total_cost:.6f}", 'yellow', attrs=['bold'])
                ])
                
                # Print the enhanced table with all fields
                print(tabulate(llm_table, 
                      headers=['Model', 'Tokens In', 'Tokens Out', 'Cost In', 'Cost Out', 'Total Cost'],
                      tablefmt='grid'))
            else:
                # Basic structure with just input and output tokens
                llm_table.append([
                    f"{section_data.get('input', 0):,}", 
                    f"{section_data.get('output', 0):,}"
                ])
                
                # Print the basic table
                print(tabulate(llm_table, 
                      headers=['Tokens In', 'Tokens Out'],
                      tablefmt='simple'))
        
        elif section_name == 'formatted_json':
            # Format the extracted JSON data
            if isinstance(section_data, dict):
                # Create a table for all top-level fields
                json_table = []
                
                for field, value in section_data.items():
                    # Format the value
                    if value == "":
                        formatted_value = colored("(empty)", 'dark_grey')
                    elif isinstance(value, (dict, list)):
                        # For nested structures, show a placeholder
                        formatted_value = colored(f"({type(value).__name__})", 'blue')
                    else:
                        formatted_value = str(value)
                    
                    json_table.append([field, formatted_value])
                
                # Print the table
                if json_table:
                    print(tabulate(json_table, tablefmt='simple'))
            else:
                # If not a dict, just print the data
                print(json.dumps(section_data, indent=N_INDENT, sort_keys=False, cls=OrderedDictJSONEncoder))
        
        else:
            # Generic handler for any other sections
            try:
                print(json.dumps(section_data, indent=N_INDENT, sort_keys=False, cls=OrderedDictJSONEncoder))
            except:
                print(str(section_data))
    

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
    Save a list of VoucherVision results to a CSV file using the filename 
    that's already included in the results
    
    Args:
        results_list (list): List of dictionaries containing the results
        output_dir (str): Directory to save the CSV file
    """
    if not results_list:
        print("No results to save to CSV")
        return
    
    # Extract formatted_json from each result and add filename
    vvgo_data = []
    
    for i, result in enumerate(results_list):
        # Debug info for the first few results
        if i < 2:
            print(f"\nDebug - Result keys: {list(result.keys() if result else [])}")
        
        # Skip if result is empty
        if not result:
            continue
            
        # Get the filename directly from the result
        filename = result.get('filename', '')
        if not filename:
            # Fallback methods if filename is not directly available
            if 'source_file' in result:
                filename = os.path.splitext(os.path.basename(result['source_file']))[0]
            else:
                # Use index as last resort
                filename = f"file_{i+1}"
                
        # Get the JSON data (try formatted_json first, then vvgo_json)
        json_data = None
        json_key = None
        
        if 'formatted_json' in result:
            json_key = 'formatted_json'
        elif 'vvgo_json' in result:
            json_key = 'vvgo_json'
            
        if json_key:
            # Get the JSON data in the appropriate format
            if isinstance(result[json_key], OrderedDict):
                json_data = result[json_key]
            elif isinstance(result[json_key], str):
                # Parse string JSON with OrderedDict
                try:
                    json_data = json.loads(result[json_key], object_pairs_hook=OrderedDict)
                except json.JSONDecodeError:
                    continue
            elif isinstance(result[json_key], dict):
                # Convert regular dict to OrderedDict
                json_data = OrderedDict(result[json_key])
            else:
                json_data = result[json_key]
            
            if json_data:
                # Create a new OrderedDict with filename as the first key
                data_with_filename = OrderedDict([('filename', filename)])
                
                # Add all other keys in their original order
                for key, value in json_data.items():
                    data_with_filename[key] = value
                
                vvgo_data.append(data_with_filename)
    
    if not vvgo_data:
        print("No VoucherVision JSON data found in results")
        print("Available keys in results:", [list(r.keys()) for r in results_list[:3] if r])
        return
    
    # Get the order of columns from the first result
    if vvgo_data and isinstance(vvgo_data[0], OrderedDict):
        column_order = list(vvgo_data[0].keys())
    else:
        column_order = None  # Let pandas decide
    
    # Convert to DataFrame
    df = pd.DataFrame(vvgo_data)
    
    # Ensure column order with filename first if we have a specific order
    if column_order:
        # Make sure all columns exist in the DataFrame
        available_columns = [col for col in column_order if col in df.columns]
        df = df[available_columns]
    
    # Save to CSV
    csv_path = os.path.join(output_dir, 'results.csv')
    df.to_csv(csv_path, index=False)
    print(f"\nCombined results saved to CSV: {csv_path}")
    print(f"Total records processed: {len(df)}")
    
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
                        help='Save all formatted_json results to a CSV file in the output directory')
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
    print(f"\n{'-' * N_SIZE}")
    print(f"Total operation time: {int(minutes)} minutes and {int(seconds)} seconds")
    print(f"{'-' * N_SIZE}")

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