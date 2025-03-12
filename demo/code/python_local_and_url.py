import requests
import os
import json
from pprint import pprint

def process_local_image(server_url, image_path, auth_token, engines=None, prompt=None, verbose=False):
    """
    Process a local image file using the VoucherVision API
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_path (str): Path to the local image file
        auth_token (str): Authentication token or API key
        engines (list): OCR engine options to use
        prompt (str): Custom prompt file to use
        verbose (bool): Whether to print detailed information
        
    Returns:
        dict: The processed results from the server
    """
    # API endpoint
    url = f"{server_url}/process"
    
    if verbose:
        print(f"Processing local image: {image_path}")
        print(f"Server URL: {url}")
    
    # Prepare the multipart form data
    files = {'file': open(image_path, 'rb')}
    
    # Optional parameters
    data = {}
    if engines:
        data['engines'] = engines
        if verbose:
            print(f"Using engines: {engines}")
    if prompt:
        data['prompt'] = prompt
        if verbose:
            print(f"Using prompt: {prompt}")
    
    # Determine auth header type based on auth_token format
    headers = {}
    if '.' in auth_token and len(auth_token) > 100:
        # Likely a Firebase token
        headers["Authorization"] = f"Bearer {auth_token}"
        if verbose:
            print("Using Firebase token authentication")
    else:
        # Likely an API key
        headers["X-API-Key"] = auth_token
        if verbose:
            print("Using API key authentication")
    
    try:
        if verbose:
            print("Sending request...")
            print(f"Headers: {headers}")
            print(f"Data params: {data}")
            print(f"Sending file: {os.path.basename(image_path)}")
        
        # Send the request
        response = requests.post(url, files=files, data=data, headers=headers)
        
        if verbose:
            print(f"Response status code: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            if verbose:
                print("Request successful!")
            return result
        else:
            error_msg = f"Error: {response.status_code}"
            try:
                error_details = response.json()
                error_msg += f" - {error_details.get('error', 'Unknown error')}"
            except:
                error_msg += f" - {response.text}"
            
            if verbose:
                print(f"Request failed: {error_msg}")
            
            raise Exception(error_msg)
    
    finally:
        # Close the file
        files['file'].close()
        if verbose:
            print("Closed file handle")

def process_image_url(server_url, image_url, auth_token, engines=None, prompt=None, verbose=False):
    """
    Process an image by URL using the VoucherVision API
    
    Args:
        server_url (str): URL of the VoucherVision API server
        image_url (str): URL of the image to process
        auth_token (str): Authentication token or API key
        engines (list): OCR engine options to use
        prompt (str): Custom prompt file to use
        verbose (bool): Whether to print detailed information
        
    Returns:
        dict: The processed results from the server
    """
    # API endpoint
    url = f"{server_url}/process-url"
    
    if verbose:
        print(f"Processing image URL: {image_url}")
        print(f"Server URL: {url}")
    
    # Prepare request data
    data = {'image_url': image_url}
    
    # Add optional parameters
    if engines:
        data['engines'] = engines
        if verbose:
            print(f"Using engines: {engines}")
    if prompt:
        data['prompt'] = prompt
        if verbose:
            print(f"Using prompt: {prompt}")
    
    # Determine auth header type based on auth_token format
    headers = {
        'Content-Type': 'application/json'
    }
    
    if '.' in auth_token and len(auth_token) > 100:
        # Likely a Firebase token
        headers["Authorization"] = f"Bearer {auth_token}"
        if verbose:
            print("Using Firebase token authentication")
    else:
        # Likely an API key
        headers["X-API-Key"] = auth_token
        if verbose:
            print("Using API key authentication")
    
    if verbose:
        print("Sending request...")
        print(f"Headers: {headers}")
        print(f"Request data: {data}")
    
    # Send the request
    response = requests.post(url, json=data, headers=headers)
    
    if verbose:
        print(f"Response status code: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
    
    # Check if the request was successful
    if response.status_code == 200:
        result = response.json()
        if verbose:
            print("Request successful!")
        return result
    else:
        error_msg = f"Error: {response.status_code}"
        try:
            error_details = response.json()
            error_msg += f" - {error_details.get('error', 'Unknown error')}"
        except:
            error_msg += f" - {response.text}"
        
        if verbose:
            print(f"Request failed: {error_msg}")
        
        raise Exception(error_msg)

if __name__ == "__main__":
    # Server URL
    server_url = "https://vouchervision-go-738307415303.us-central1.run.app"
    
    # Authentication token (required)
    # This could be either a Firebase token or an API key
    auth_token = "YOUR_AUTH_TOKEN_OR_API_KEY_HERE"
    
    # Always enable verbose mode for detailed output
    verbose = True
    
    # Example 1: Process a local image file
    local_image_path = "path/to/your/local/image.jpg"
    if os.path.exists(local_image_path):
        print("\n--- Processing local image ---")
        try:
            result = process_local_image(
                server_url=server_url,
                image_path=local_image_path,
                auth_token=auth_token,
                engines=['gemini-1.5-pro', 'gemini-2.0-flash'],
                prompt='SLTPvM_default.yaml',
                verbose=verbose
            )
            print("Success! Results:")
            pprint(result)
        except Exception as e:
            print(f"Error processing local image: {e}")
    
    # Example 2: Process an image by URL
    image_url = "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg"
    print("\n--- Processing image by URL ---")
    try:
        result = process_image_url(
            server_url=server_url,
            image_url=image_url,
            auth_token=auth_token,
            engines=['gemini-1.5-pro', 'gemini-2.0-flash'],
            prompt='SLTPvM_default.yaml',
            verbose=verbose
        )
        print("Success! Results:")
        pprint(result)
    except Exception as e:
        print(f"Error processing image URL: {e}")
        print("Note: The '/process-url' endpoint needs to be implemented on the server first.")

# Example command to run:
# python python_local_and_url.py