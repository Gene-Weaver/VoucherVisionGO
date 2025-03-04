#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import time
from datetime import datetime
import platform

class VoucherVisionTester:
    def __init__(self, server_url, base_dir="./", venv_path=None):
        self.server_url = server_url
        self.base_dir = base_dir
        self.venv_path = venv_path
        self.tests = []
        self.setup_test_cases()
        
    def setup_test_cases(self):
        """Setup all test cases with their descriptions and commands"""
        # Create base directories if they don't exist
        os.makedirs(f"{self.base_dir}/results/single_image", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/single_url", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/dir_images", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/dir_images_custom_prompt_save_to_csv", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/file_list_csv", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/file_list_txt", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/file_list_long_txt", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/single_image_custom_prompt", exist_ok=True)
        os.makedirs(f"{self.base_dir}/results/dir_images_save_to_csv", exist_ok=True)
        
        # Test cases
        self.tests = [
            {
                "name": "single_image",
                "description": "Process a single local image file",
                "cmd": [
                    sys.executable, "client.py",
                    "--server", self.server_url,
                    "--image", f"{self.base_dir}/images/MICH_16205594_Poaceae_Jouvea_pilosa.jpg",
                    "--output-dir", f"{self.base_dir}/results/single_image",
                ]
            },
            {
                "name": "url_image",
                "description": "Process an image from a URL",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--image", "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg",
                    "--output-dir", f"{self.base_dir}/results/single_url",
                ]
            },
            {
                "name": "custom_prompt",
                "description": "Process an image with a custom prompt",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--image", "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg",
                    "--output-dir", f"{self.base_dir}/results/single_image_custom_prompt",
                    "--verbose",
                    "--prompt", "SLTPvM_default_chromosome.yaml"
                ]
            },
            {
                "name": "directory_images",
                "description": "Process all images in a directory",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--directory", f"{self.base_dir}/images",
                    "--output-dir", f"{self.base_dir}/results/dir_images",
                ]
            },
            {
                "name": "directory_images_custom_prompt_csv",
                "description": "Process directory with custom prompt and save to CSV",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--directory", f"{self.base_dir}/images",
                    "--output-dir", f"{self.base_dir}/results/dir_images_custom_prompt_save_to_csv",
                    "--verbose",
                    "--prompt", "SLTPvM_default_chromosome.yaml",
                    "--save-to-csv"
                ]
            },
            {
                "name": "file_list_csv",
                "description": "Process a list of images from a CSV file",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--file-list", f"{self.base_dir}/csv/file_list.csv",
                    "--output-dir", f"{self.base_dir}/results/file_list_csv",
                ]
            },
            {
                "name": "file_list_txt",
                "description": "Process a list of images from a text file",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--file-list", f"{self.base_dir}/txt/file_list.txt",
                    "--output-dir", f"{self.base_dir}/results/file_list_txt",
                ]
            },
            {
                "name": "file_list_long_txt",
                "description": "Process a list of images from a text file",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--file-list", f"{self.base_dir}/txt/file_list_long_txt.txt",
                    "--output-dir", f"{self.base_dir}/results/file_list_long_txt",
                    "--save-to-csv",
                ]
            },
            {
                "name": "save_to_csv",
                "description": "Process images and save results to CSV",
                "cmd": [
                    "python", "client.py",
                    "--server", self.server_url,
                    "--directory", f"{self.base_dir}/images",
                    "--output-dir", f"{self.base_dir}/results/dir_images_save_to_csv",
                    "--save-to-csv"
                ]
            }
        ]
    
    def run_test(self, test):
        """Run a single test case"""
        print(f"\n{'=' * 80}")
        print(f"Running test: {test['name']}")
        print(f"Description: {test['description']}")
        print(f"Command: {' '.join(test['cmd'])}")
        print(f"{'-' * 80}")
        
        start_time = time.time()
        
        try:
            # Set up environment to include virtual environment if specified
            env = os.environ.copy()
            
            if self.venv_path:
                # Create the appropriate activate command based on OS
                if platform.system() == "Windows":
                    activate_script = os.path.join(self.venv_path, "Scripts", "activate.bat")
                    cmd_prefix = f"call {activate_script} && "
                else:
                    activate_script = os.path.join(self.venv_path, "bin", "activate")
                    cmd_prefix = f"source {activate_script} && "
                
                # Join the command with the activation prefix
                full_cmd = cmd_prefix + " ".join(test['cmd'])
                
                # Use shell=True to execute the combined command
                result = subprocess.run(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=True,
                    env=env
                )
            else:
                # Use the command as is
                result = subprocess.run(
                    test['cmd'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )
            
            # Print stdout
            if result.stdout:
                print("\nSTDOUT:")
                print(result.stdout)
            
            # Print stderr if there's an error
            if result.stderr:
                print("\nSTDERR:")
                print(result.stderr)
            
            success = result.returncode == 0
            
            # Special case for custom_prompt test - check for chromosomeCount in JSON
            if success and 'custom_prompt' in test['name']:
                try:
                    import json
                    from io import StringIO
                    
                    # Try to parse the stdout to find JSON data
                    output = result.stdout
                    json_data = None
                    
                    # Find the JSON output in the stdout
                    if "VoucherVision JSON:" in output:
                        json_start = output.find("VoucherVision JSON:") + len("VoucherVision JSON:")
                        json_text = output[json_start:].strip()
                        
                        # Try to parse the JSON
                        try:
                            json_data = json.loads(json_text)
                        except json.JSONDecodeError:
                            # If direct parsing fails, try to find JSON between specific delimiters
                            import re
                            json_pattern = re.compile(r'\{.*\}', re.DOTALL)
                            match = json_pattern.search(json_text)
                            if match:
                                try:
                                    json_data = json.loads(match.group(0))
                                except:
                                    pass
                    
                    # If we couldn't find JSON in stdout, try checking the output JSON file
                    if not json_data:
                        # Find the output directory from test command
                        output_dir = next((arg for i, arg in enumerate(test['cmd']) if arg == '--output-dir' and i + 1 < len(test['cmd'])), None)
                        if output_dir:
                            output_dir_index = test['cmd'].index('--output-dir') + 1
                            output_dir = test['cmd'][output_dir_index]
                            
                            # Extract the image filename or URL
                            image_path = next((arg for i, arg in enumerate(test['cmd']) if arg == '--image' and i + 1 < len(test['cmd'])), None)
                            if image_path:
                                image_index = test['cmd'].index('--image') + 1
                                image_path = test['cmd'][image_index]
                                
                                # Get the output filename
                                from os.path import basename, splitext, join
                                if image_path.startswith(('http://', 'https://')):
                                    # For URLs, use the last part of the URL as the filename
                                    base_name = basename(image_path.split('?')[0])  # Remove query params if any
                                else:
                                    base_name = basename(image_path)
                                
                                name_without_ext = splitext(base_name)[0]
                                json_file_path = join(output_dir, f"{name_without_ext}.json")
                                
                                # Try to read and parse the JSON file
                                if os.path.exists(json_file_path):
                                    try:
                                        with open(json_file_path, 'r') as f:
                                            file_data = json.load(f)
                                            if 'formatted_json' in file_data:
                                                json_data = file_data['formatted_json']
                                    except:
                                        pass
                    
                    # Check if the required key exists
                    if json_data:
                        if 'chromosomeCount' not in json_data:
                            success = False
                            print("❌ Test 'custom_prompt' failed validation: 'chromosomeCount' key not found in JSON output")
                        else:
                            print(f"✅ Validation passed: Found 'chromosomeCount' key with value: {json_data['chromosomeCount']}")
                    else:
                        success = False
                        print("❌ Test 'custom_prompt' failed validation: Could not parse JSON output")
                
                except Exception as e:
                    print(f"❌ Error validating custom_prompt test: {str(e)}")
                    success = False
            
            # Print test result
            end_time = time.time()
            duration = end_time - start_time
            
            if success:
                print(f"✅ Test '{test['name']}' PASSED in {duration:.2f} seconds")
            else:
                print(f"❌ Test '{test['name']}' FAILED in {duration:.2f} seconds")
                print(f"Return code: {result.returncode}")
            
            return {
                "name": test['name'],
                "success": success,
                "duration": duration,
                "return_code": result.returncode
            }
            
        except Exception as e:
            print(f"❌ Error running test '{test['name']}':")
            print(str(e))
            return {
                "name": test['name'],
                "success": False,
                "duration": time.time() - start_time,
                "error": str(e)
            }
    
    def run_all_tests(self):
        """Run all test cases and return the results"""
        print(f"Starting test run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Server URL: {self.server_url}")
        print(f"Base directory: {self.base_dir}")
        
        results = []
        
        for test in self.tests:
            result = self.run_test(test)
            results.append(result)
        
        return results
    
    def run_specific_test(self, test_name):
        """Run a specific test by name"""
        test = next((t for t in self.tests if t['name'] == test_name), None)
        
        if test:
            return self.run_test(test)
        else:
            print(f"No test found with name '{test_name}'")
            print(f"Available tests: {', '.join(t['name'] for t in self.tests)}")
            return None
    
    def print_summary(self, results):
        """Print a summary of test results"""
        print(f"\n{'=' * 80}")
        print("TEST SUMMARY")
        print(f"{'-' * 80}")
        
        total = len(results)
        passed = sum(1 for r in results if r['success'])
        failed = total - passed
        
        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        
        if failed > 0:
            print("\nFailed tests:")
            for result in results:
                if not result['success']:
                    print(f"  - {result['name']}")
        
        print(f"\nTest run completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def main():
    parser = argparse.ArgumentParser(description='VoucherVision Testing Tool')
    parser.add_argument('--server', default="https://vouchervision-go-738307415303.us-central1.run.app",
                        help='URL of the VoucherVision API server')
    parser.add_argument('--base-dir', default="./demo",
                        help='Base directory for test files and results')
    parser.add_argument('--test', 
                        help='Run a specific test by name (omit to run all tests)')
    parser.add_argument('--list-tests', action='store_true',
                        help='List all available tests')
    parser.add_argument('--venv', 
                        help='Path to virtual environment directory (e.g., .vvgo)')
    parser.add_argument('--install-deps', action='store_true',
                        help='Install required dependencies before running tests')
    
    args = parser.parse_args()
    
    # Install dependencies if requested
    if args.install_deps:
        print("Installing required dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "requests", "pandas"])
        print("Dependencies installed.")
    
    # Create tester instance
    tester = VoucherVisionTester(args.server, args.base_dir, args.venv)
    
    if args.list_tests:
        print("Available tests:")
        for test in tester.tests:
            print(f"  - {test['name']}: {test['description']}")
        return
    
    # Run tests
    if args.test:
        result = tester.run_specific_test(args.test)
        if result:
            tester.print_summary([result])
    else:
        results = tester.run_all_tests()
        tester.print_summary(results)

if __name__ == "__main__":
    main()

    '''
    python test.py --venv ".vvgo"

    options
    python test.py --install-deps
    '''