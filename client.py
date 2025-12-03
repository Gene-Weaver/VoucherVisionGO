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

from url_name_parser import extract_filename_from_url
"""


RUN IT FROM THE CLIENT PACKAGE NOT HERE


"""
N_SIZE=100
N_INDENT=2

"""
NOTE:
    You can use any of the Gemini models, not just those that I specify: https://ai.google.dev/gemini-api/docs/models
    Just pick the one you want (e.g. gemini-2.5-flash) as long as it supports: Audio, images, videos, and text
"""

class OrderedDictJSONEncoder(json.JSONEncoder):
    def encode(self, obj):
        if isinstance(obj, OrderedDict):
            # Convert OrderedDict to a list of tuples for ordered serialization
            return '{' + ','.join(f'"{k}":{self.encode(v)}' for k, v in obj.items()) + '}'
        return super().encode(obj)
    
def ordereddict_to_json(ordereddict_data, output_type="json"):
    """
    Convert an OrderedDict to JSON
    
    Args:
        ordereddict_data: The OrderedDict to convert
        output_type: "json" (string) or "dict" (Python dictionary)
        
    Returns:
        Either a JSON string or Python dictionary based on output_type
    """
    def convert_to_dict(obj):
        if isinstance(obj, OrderedDict):
            return {k: convert_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_dict(v) for v in obj]
        else:
            return obj
    
    regular_dict = convert_to_dict(ordereddict_data)
    
    if output_type.lower() == "dict":
        return regular_dict
    else:  # Default to JSON string
        return json.dumps(regular_dict, indent=4)
    
def process_image(fname, server_url, image_path, output_dir, verbose=False, 
                  engines=None, llm_model=None, prompt=None, auth_token=None, ocr_only=False, notebook_mode=False):
    """
    Process an image using the VoucherVision API server
    
    Args:
        fname (str): Name for the output file
        server_url (str): URL of the VoucherVision API server
        image_path (str): Path to the image file or URL of the image
        output_dir (str): Directory to save output files
        verbose (bool): Whether to print verbose output
        engines (list): List of OCR engine options to use
        llm_model (str): LLM model to use for creating JSON
        prompt (str): Custom prompt file to use
        auth_token (str): Authentication token for the API (Firebase token or API key)
        ocr_only (bool): Whether to only perform OCR and skip LLM processing
        notebook_mode (bool): Whether to only perform OCR, skip label collage, and skip LLM processing

    Returns:
        dict: The processed results from the server
    """
    # Always verify authentication using the cached verification
    if not verify_authentication(server_url, auth_token):
        print("Aborting. Authentication failed.")
        return
    
    # Check if the image path is a URL or a local file
    if image_path.startswith(('http://', 'https://')):
        # For URL-based images, download them first
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
            # Pass the auth token to the recursive call
            return process_image(fname, server_url, temp_file_path, output_dir, verbose, engines, llm_model, prompt, auth_token, ocr_only, notebook_mode)
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
    if llm_model:
        data['llm_model'] = llm_model
    if prompt:
        data['prompt'] = prompt
    if ocr_only:
        data['ocr_only'] = 'true'
    if notebook_mode:
        data['notebook_mode'] = 'true'

    # Determine auth header type based on auth_token format
    # API keys are typically alphanumeric strings without periods
    # Firebase tokens are JWT tokens with periods separating sections
    headers = {}
    if auth_token:
        if '.' in auth_token and len(auth_token) > 100:
            # Likely a Firebase token
            headers["Authorization"] = f"Bearer {auth_token}"
        else:
            # Likely an API key
            headers["X-API-Key"] = auth_token
    
    try:
        # Send the request
        if verbose:
            print(f"Sending request to {url}")
            if ocr_only:
                print("OCR-only mode: Skipping VoucherVision JSON parsing")
            if notebook_mode:
                print("Running in notebook mode")
        response = requests.post(url, files=files, data=data, headers=headers)
        
        # Check if the request was successful
        if response.status_code == 200:
            results = json.loads(response.text, object_pairs_hook=OrderedDict)
            # If formatted_json is a string that contains JSON, parse it with OrderedDict
            if 'formatted_json' in results and isinstance(results['formatted_json'], str):
                try:
                    # Try to parse it as JSON with order preserved
                    results['formatted_json'] = json.loads(results['formatted_json'], object_pairs_hook=OrderedDict)
                except json.JSONDecodeError:
                    # Not valid JSON, leave as string
                    pass
            results['filename'] = fname  # Add in the filename
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

def process_image_file(server_url, image_path, engines, llm_model, prompt, output_dir, verbose, auth_token=None, ocr_only=False, notebook_mode=False):
    """
    Process a single image file and save the results
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_path (str): Path to the image file or URL
        engines (list): List of OCR engine options to use
        llm_model
        prompt (str): Custom prompt file to use
        output_dir (str): Directory to save output files
        verbose (bool): Whether to print verbose output
        auth_token (str): Authentication token for the API
        ocr_only (bool): Whether to only perform OCR and skip VoucherVision processing
        notebook_mode (bool): Whether to only perform OCR, skip label collage, and skip LLM processing
       
    Returns:
        dict: The processing results
    """
    output_file, output_file_md = get_output_filename(image_path, output_dir)
    fname = os.path.basename(output_file).split(".")[0]

    try:
        # Process the image
        results = process_image(fname, server_url, image_path, output_dir, verbose, engines, llm_model, prompt, auth_token, ocr_only, notebook_mode)

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

        # ------------------------------------------------------------------
        # Notebook mode: save formatted_md (markdown) to a .md file
        # ------------------------------------------------------------------
        if notebook_mode:
            formatted_md = ""

            if isinstance(results, dict):
                # Top-level formatted_md as in your example JSON
                formatted_md = results.get("formatted_md", "") or ""

            if formatted_md:
                md_text = formatted_md.strip()

                # If wrapped in ```markdown ... ``` or ``` ... ```
                if md_text.startswith("```"):
                    lines = md_text.splitlines()

                    # Drop opening fence line
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]

                    # Drop closing fence line if present
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]

                    md_text = "\n".join(lines).rstrip() + "\n"

                # Write final markdown to the .md file
                with open(output_file_md, "w", encoding="utf-8") as f_md:
                    f_md.write(md_text)

                if verbose:
                    print(f"Notebook-mode markdown saved to: {output_file_md}")
            else:
                if verbose:
                    print("Notebook mode enabled, but no 'formatted_md' found in results; skipping .md save.")

        return results
    
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None

def process_images_parallel(server_url, image_paths, engines, llm_model, prompt, output_dir, verbose, max_workers=4, auth_token=None, ocr_only=False, notebook_mode=False):
    """
    Process multiple images in parallel
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_paths (list): List of paths to image files or URLs
        engines (list): List of OCR engine options to use
        llm_model
        prompt (str): Custom prompt file to use
        output_dir (str): Directory to save output files
        verbose (bool): Whether to print verbose output
        max_workers (int): Maximum number of parallel workers
        auth_token (str): Authentication token for the API
        ocr_only (bool): Whether to only perform OCR and skip VoucherVision processing
       
    Returns:
        list: List of processing results
    """
    results = []
    
    print(f"Processing {len(image_paths)} images with up to {max_workers} parallel workers")
    if ocr_only:
        print("OCR-only mode: Skipping VoucherVision processing")
    if notebook_mode:
        print("Running in notebook mode")

    # Create a progress bar
    progress_bar = tqdm(total=len(image_paths), desc="Processing", unit="image")
    
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a dictionary mapping futures to their corresponding file paths
        # Verbose is forced off when using parallel, it's too messy in console printout
        future_to_path = {
            executor.submit(
                process_image_file, 
                server_url, 
                path, 
                engines, 
                llm_model,
                prompt, 
                output_dir, 
                False, 
                auth_token,
                ocr_only,
                notebook_mode,
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
        base_name = extract_filename_from_url(input_path)
        # base_name = os.path.basename(input_path).split('?')[0]  # Remove query params if any
    else:
        base_name = os.path.basename(input_path)
    
    # Replace the extension with .json
    name_without_ext = os.path.splitext(base_name)[0]
    output_filename = f"{name_without_ext}.json"
    output_filename_md = f"{name_without_ext}.md"
    
    # If output directory is specified, join it with the filename
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, output_filename), os.path.join(output_dir, output_filename_md)
    
    return output_filename, output_filename_md

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
    
    if ext == ".xlsx":
        try:
            df = pd.read_excel(list_file, dtype=str)  # ensure all strings
            # Use first column only
            first_col = df.columns[0]
            for val in df[first_col].fillna("").astype(str).tolist():
                val = val.strip()
                if val:
                    file_paths.append(val)
        except Exception as e:
            raise RuntimeError(f"Failed to read XLSX file '{list_file}': {e}")

    elif ext == ".csv":
        try:
            with open(list_file, "r", newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if row and row[0].strip():
                        file_paths.append(row[0].strip())
        except Exception as e:
            raise RuntimeError(f"Failed to read CSV file '{list_file}': {e}")
        
    else:
        try:
            with open(list_file, "r", encoding="utf-8") as f:
                for line in f:
                    cleaned = line.strip()
                    if cleaned:
                        file_paths.append(cleaned)
        except Exception as e:
            raise RuntimeError(f"Failed to read text file '{list_file}': {e}")

    return file_paths


def save_results_to_xlsx(results_list, output_dir):
    """
    Save a list of VoucherVision results to an XLSX file using the filename 
    that's already included in the results. All columns are stored as strings
    so that Excel does not auto-convert cells.
    
    Args:
        results_list (list): List of dictionaries containing the results
        output_dir (str): Directory to save the XLSX file
    """
    if not results_list:
        print("No results to save to XLSX")
        return
    
    # Extract formatted_json from each result and add filename
    vvgo_data = []
    
    for i, result in enumerate(results_list):
        # Debug info for the first few results
        # if i < 2:
        #     print(f"\nDebug - Result keys: {list(result.keys() if result else [])}")
        
        # Skip if result is empty
        if not result:
            continue
            
        # Get the filename directly from the result
        if 'filename' in result:
            filename = os.path.splitext(os.path.basename(result['filename']))[0]
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
    
    # --- Force all columns to string to avoid Excel auto-conversion ---
    # Replace NaN with empty string, then cast everything to str
    df = df.fillna("").astype(str)
    
    # Save to XLSX
    xlsx_path = os.path.join(output_dir, 'results.xlsx')
    df.to_excel(xlsx_path, index=False, sheet_name='results')
    print(f"Combined results saved to XLSX: {xlsx_path}")
    print(f"Total records processed: {len(df)}")
    
    # Print column names for verification
    if not df.empty:
        print(f"XLSX columns: {', '.join(df.columns.tolist())}")


### USE AT YOUR OWN RISK
### csv when opened in excel may autoconvert column like date. Use the xlsx version. 
def save_results_to_csv(results_list, output_dir):
    """
    Save a list of VoucherVision results to a XLSX file using the filename 
    that's already included in the results
    
    Args:
        results_list (list): List of dictionaries containing the results
        output_dir (str): Directory to save the XLSX file
    """
    if not results_list:
        print("No results to save to XLSX")
        return
    
    # Extract formatted_json from each result and add filename
    vvgo_data = []
    
    for i, result in enumerate(results_list):
        # Debug info for the first few results
        # if i < 2:
            # print(f"\nDebug - Result keys: {list(result.keys() if result else [])}")
        
        # Skip if result is empty
        if not result:
            continue
            
        # Get the filename directly from the result
        # filename = "" #result.get('filename', '')
        # if not filename:
        # Fallback methods if filename is not directly available
        # print(result)
        if 'filename' in result:
            filename = os.path.splitext(os.path.basename(result['filename']))[0]
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
    print(f"Combined results saved to CSV: {csv_path}")
    print(f"Total records processed: {len(df)}")
    
    # Print column names for verification
    if not df.empty:
        print(f"CSV columns: {', '.join(df.columns.tolist())}")

def verify_authentication(server_url, auth_token=None):
    """Verify the authentication token before starting any processing"""
    if not auth_token:
        print("ERROR: No authentication token provided.")
        print("Visit the login page to get your token: " + server_url + "/login")
        print("Or visit the API key management page: " + server_url + "/api-key-management")
        return False
    try:
        # We'll check both authentication methods - API key or Firebase token
        
        # First, try as API key
        headers = {"X-API-Key": auth_token}
        response = requests.get(f"{server_url}/auth-check", headers=headers)
        
        if response.status_code == 200:
            print("Authentication successful using API key.")
            return True
        
        # If that fails, try as Firebase token
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{server_url}/auth-check", headers=headers)
        
        if response.status_code == 200:
            print("Authentication successful using Firebase token.")
            return True
        elif response.status_code == 401:
            print("ERROR: Authentication failed. Please provide a valid authentication token or API key.")
            print("Visit the login page to get your token: " + server_url + "/login")
            print("Or visit the API key management page: " + server_url + "/api-key-management")
            return False
        else:
            print(f"ERROR: Server returned unexpected status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"ERROR: Could not connect to server: {str(e)}")
        return False
    
def process_vouchers(server, output_dir, engines=["gemini-1.5-pro", "gemini-2.0-flash"], llm_model="gemini-2.0-flash",
                    prompt="SLTPvM_default.yaml", image=None, directory=None, 
                    file_list=None, verbose=False, save_to_xlsx=False, max_workers=4, auth_token=None, ocr_only=False, notebook_mode=False):
    """
    Process voucher images through the VoucherVision API.
    
    Args:
        server (str): URL of the VoucherVision API server
        output_dir (str): Directory to save the output JSON results
        engines (list): OCR engine options to use
        llm_model
        prompt (str): Custom prompt file to use
        image (str): Path to a single image file or URL to process
        directory (str): Path to a directory containing images to process
        file_list (str): Path to a file containing a list of image paths or URLs
        verbose (bool): Print all output to console
        save_to_xlsx (bool): Save all formatted_json results to a XLSX file
        max_workers (int): Maximum number of parallel workers
        auth_token (str): Authentication token for the API
        ocr_only (bool): Whether to only perform OCR and skip VoucherVision processing
        
    Returns:
        list: List of processed results if save_to_xlsx is True, otherwise None
    """
    # First verify authentication before doing anything
    if not verify_authentication(server, auth_token):
        print("Aborting. Authentication failed.")
        return
    
    import os
    import time
    import sys
    import glob

    # Ensure max_workers is no more than 32
    max_workers = min(max_workers, 32)
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Start timing
    start_time = time.time()
    
    # If in OCR-only mode, inform user
    if ocr_only:
        print("Running in OCR-only mode: Skipping VoucherVision JSON parsing")
    if notebook_mode:
        print("Running in notebook mode: Skipping VoucherVision JSON parsing: Skipping label collage")
    
    try:
        # To store all results if save-to-xlsx is enabled
        all_results = []
        
        # Process based on the input type
        if image:
            # Single image (no need for parallelization)
            result = process_image_file(server, image, engines, llm_model, prompt, output_dir, verbose, auth_token, ocr_only, notebook_mode)
            if result and save_to_xlsx:
                all_results.append(result)
        
        elif directory:
            # Directory of images - use parallel processing
            if not os.path.isdir(directory):
                raise ValueError(f"Directory not found: {directory}")
            
            # Get all image files in the directory
            image_extensions = ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.gif', '.JPG', '.JPEG', '.PNG']
            image_files = []

            for ext in image_extensions:
                # Just use the lowercase extension - Windows is case-insensitive anyway
                image_files.extend(glob.glob(os.path.join(directory, f"*{ext}")))

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
                print(f"No image files found in {directory}")
                return None
            
            # Process images in parallel
            results = process_images_parallel(
                server, 
                image_files, 
                engines, 
                llm_model,
                prompt, 
                output_dir, 
                verbose,
                max_workers,
                auth_token,
                ocr_only,
                notebook_mode,
            )
            
            if save_to_xlsx:
                all_results.extend(results)
        
        elif file_list:
            # List of image paths or URLs from a file - use parallel processing
            file_paths = read_file_list(file_list)
            
            if not file_paths:
                print(f"No file paths found in {file_list}")
                return None
            
            print(f"Found {len(file_paths)} paths to process")
            
            # Process files in parallel
            results = process_images_parallel(
                server, 
                file_paths, 
                engines, 
                llm_model,
                prompt, 
                output_dir, 
                verbose,
                max_workers,
                auth_token,
                ocr_only,
                notebook_mode,
            )
            
            if save_to_xlsx:
                all_results.extend(results)
        
        # Save to XLSX if requested
        if save_to_xlsx and all_results:
            save_results_to_xlsx(all_results, output_dir)
            
        if save_to_xlsx:
            return all_results
        return None

    except Exception as e:
        print(f"Error: {e}")
        if __name__ == "__main__":
            sys.exit(1)
        else:
            raise

    finally:
        # End timing and report
        end_time = time.time()
        elapsed_seconds = end_time - start_time
        minutes, seconds = divmod(elapsed_seconds, 60)
        print(f"\n{'-' * N_SIZE}")
        print(f"Total operation time: {int(minutes)} minutes and {int(seconds)} seconds")
        print(f"{'-' * N_SIZE}")

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='VoucherVisionGO Client')
    parser.add_argument('--server', required=True, 
                        help='URL of the VoucherVision API server (e.g., http://localhost:8080)')
    
    parser.add_argument('--auth-token', required=True, 
                        help='Authentication token (https://vouchervision-go-738307415303.us-central1.run.app/login)')
    
    # Create a mutually exclusive group for input sources
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--image', 
                             help='Path to a single image file or URL to process')
    input_group.add_argument('--directory',
                             help='Path to a directory containing images to process')
    input_group.add_argument('--file-list',
                             help='Path to a file containing a list of image paths or URLs (one per line or XLSX)')
    
    parser.add_argument('--engines', nargs='+', default=["gemini-1.5-pro", "gemini-2.0-flash"],
                        help='OCR engine options to use (default: gemini-1.5-pro gemini-2.0-flash)')
    parser.add_argument('--llm-model', default="gemini-2.0-flash",
                        help='OCR engine options to use (default: gemini-2.0-flash)')
    parser.add_argument('--prompt', default="SLTPvM_default.yaml",
                        help='Custom prompt file to use (default: SLTPvM_default.yaml)')
    parser.add_argument('--output-dir', required=True,
                        help='Directory to save the output JSON results')
    parser.add_argument('--verbose', action='store_true',
                        help='Print all output to console')
    parser.add_argument('--save-to-xlsx', action='store_true',
                        help='Save all formatted_json results to a XLSX file in the output directory')
    parser.add_argument('--max-workers', type=int, default=4,
                        help='Maximum number of parallel workers (default: 4)')
    parser.add_argument('--ocr-only', action='store_true',
                        help='Only perform OCR and skip VoucherVision processing')
    parser.add_argument('--notebook-mode', action='store_true',
                        help='Only perform OCR and skip VoucherVision processing. Also skips label collage, uses full image. Returns OCR as text and a .md')
    
    args = parser.parse_args()
    
    # Call the processing function with CLI arguments
    process_vouchers(
        server=args.server,
        output_dir=args.output_dir,
        engines=args.engines,
        llm_model=args.llm_model,
        prompt=args.prompt,
        image=args.image,
        directory=args.directory,
        file_list=args.file_list,
        verbose=args.verbose,
        save_to_xlsx=args.save_to_xlsx,
        max_workers=args.max_workers,
        auth_token=args.auth_token,
        ocr_only=args.ocr_only,
        notebook_mode=args.notebook_mode,
    )


if __name__ == "__main__":
    main()

### Usage examples:
# Single image:
# python client.py --server https://vouchervision-go-XXXXXX.app --image "./demo/images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg" --output-dir "./demo/results_single_image" --verbose

# URL image:
# python client.py --server https://vouchervision-go-XXXXXX.app --image "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg" --output-dir "./demo/results_single_url" --verbose

# Directory of images:
# python client.py --server https://vouchervision-go-XXXXXX.app --directory "./demo/images" --output-dir "./demo/results_dir_images" --verbose --max-workers 4
# python client.py --server https://vouchervision-go-XXXXXX.app --directory "./demo/images" --output-dir "./demo/results_dir_images_custom_prompt_save_to_xlsx" --verbose --prompt "SLTPvM_default_chromosome.yaml" --max-workers 4

# List of files:
# python client.py --server https://vouchervision-go-XXXXXX.app --file-list "./demo/xlsx/file_list.xlsx" --output-dir "./demo/results_file_list_xlsx" --verbose --max-workers 2
# python client.py --server https://vouchervision-go-XXXXXX.app --file-list "./demo/txt/file_list.txt" --output-dir "./demo/results_file_list_txt" --verbose --max-workers 4

# Custom prompt:
# python client.py --server https://vouchervision-go-XXXXXX.app --image "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg" --output-dir "./demo/results_single_image_custom_prompt" --verbose --prompt "SLTPvM_default_chromosome.yaml"

# Save results to XLSX:
# python client.py --server https://vouchervision-go-XXXXXX.app --directory ./demo/images --output-dir "./demo/results_dir_images_save_to_xlsx" --save-to-xlsx

### Programmatic Example
'''
from client import process_vouchers

if __name__ == '__main__':
	process_vouchers(server="https://vouchervision-go-XXXXXX.app", 
output_dir="./output", 
prompt="SLTPvM_default_chromosome.yaml", 
image="https://swbiodiversity.org/imglib/seinet/sernec/EKY/31234100396/31234100396116.jpg", 
directory=None, 
file_list=None, 
verbose=True, 
save_to_xlsx=True, 
max_workers=4)
	process_vouchers(server="https://vouchervision-go-XXXXXX.app", 
output_dir="./output2", 
prompt="SLTPvM_default_chromosome.yaml", 
image=None, 
directory="D:/Dropbox/VoucherVisionGO/demo/images", 
file_list=None, 
verbose=True, 
save_to_xlsx=True, 
max_workers=4)
'''