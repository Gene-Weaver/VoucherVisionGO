#!/usr/bin/env python
"""
List and display custom prompts for VoucherVision

This utility lists available prompt templates in the specified directory
and allows viewing the contents of selected prompts.

It can also fetch prompt information from a VoucherVisionGO server when
prompt files are not stored locally.
"""

import os
import sys
import argparse
import yaml
import textwrap
import json
import requests
from pathlib import Path
from termcolor import colored
from tabulate import tabulate

def list_prompts(prompt_dir):
    """
    List all prompt files (YAML) in the given directory
    
    Args:
        prompt_dir (str): Path to the directory containing prompt files
        
    Returns:
        list: List of prompt file paths
    """
    if not os.path.isdir(prompt_dir):
        print(f"Error: Directory '{prompt_dir}' not found.")
        return []
    
    # Get all YAML files
    prompt_files = []
    for ext in ['.yaml', '.yml']:
        prompt_files.extend(list(Path(prompt_dir).glob(f'*{ext}')))
    
    return sorted(prompt_files)

def extract_prompt_info(prompt_file):
    """
    Extract basic information from a prompt file
    
    Args:
        prompt_file (Path): Path to the prompt file
        
    Returns:
        dict: Dictionary with name, description, and other info
    """
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Initialize info dictionary with defaults
        info = {
            'filename': prompt_file.name,
            'description': 'No description provided',
            'version': 'Unknown',
            'author': 'Unknown',
            'institution': 'Unknown',
            'name': os.path.splitext(prompt_file.name)[0],  # Default to filename without extension
            'full_path': str(prompt_file.absolute())
        }
        
        # Look for JSON fields with lowercase names
        field_mapping = {
            'prompt_author': 'author',
            'prompt_author_institution': 'institution',
            'prompt_name': 'name',
            'prompt_version': 'version',
            'prompt_description': 'description'
        }
        
        # Extract values using regex or string operations
        import re
        for json_field, info_field in field_mapping.items():
            # Look for "json_field: value" pattern
            pattern = rf'{json_field}:\s*(.*?)(?=\n\w+:|$)'
            matches = re.findall(pattern, content, re.DOTALL)
            if matches:
                # Clean up the value (remove extra whitespace, join multi-line values)
                value = ' '.join([line.strip() for line in matches[0].strip().split('\n')])
                info[info_field] = value
        
        return info
    
    except Exception as e:
        print(f"Error extracting info from {prompt_file}: {e}")
        return {
            'filename': prompt_file.name,
            'description': f'Error reading file: {str(e)}',
            'version': 'Unknown',
            'author': 'Unknown',
            'institution': 'Unknown',
            'name': os.path.splitext(prompt_file.name)[0],
            'full_path': str(prompt_file.absolute())
        }

def display_prompt_contents(prompt_file):
    """
    Display the contents of a prompt file
    
    Args:
        prompt_file (str): Path to the prompt file
    """
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print("\n" + "="*80)
        print(colored(f"PROMPT FILE: {os.path.basename(prompt_file)}", 'green', attrs=['bold']))
        print("="*80 + "\n")
        
        # Extract and display prompt metadata using the specific format
        prompt_info = extract_prompt_info(prompt_file)
        
        # Print metadata section
        print(colored("METADATA:", 'yellow', attrs=['bold']))
        print(f"Name: {prompt_info['name']}")
        print(f"Description: {prompt_info['description']}")
        print(f"Version: {prompt_info['version']}")
        print(f"Author: {prompt_info['author']}")
        print(f"Institution: {prompt_info['institution']}")
        print()
        
        # Look for specific prompt sections
        prompt_sections = {
            'SYSTEM_PROMPT': ('SYSTEM PROMPT:', 'cyan'),
            'USER_PROMPT': ('USER PROMPT:', 'magenta'),
            'EXAMPLES': ('EXAMPLES:', 'blue'),
            'FIELDS': ('FIELDS:', 'blue')
        }
        
        # Try to find and display prompt sections
        lines = content.split('\n')
        current_section = None
        section_content = []
        
        for line in lines:
            # Check if this line starts a new section
            for section_key, (section_name, color) in prompt_sections.items():
                if line.strip().startswith(section_key):
                    # Print the previous section if there was one
                    if current_section and section_content:
                        print(colored(prompt_sections[current_section][0], prompt_sections[current_section][1], attrs=['bold']))
                        print('\n'.join(section_content))
                        print()
                    
                    # Start new section
                    current_section = section_key
                    section_content = []
                    break
            else:
                # Skip metadata lines that we already displayed
                if line.strip().startswith(('PROMPT_AUTHOR:', 'PROMPT_AUTHOR_INSTITUTION:', 
                                          'PROMPT_NAME:', 'PROMPT_VERSION:', 'PROMPT_DESCRIPTION:')):
                    continue
                
                # If we're in a section, add this line to its content
                if current_section:
                    section_content.append(line)
        
        # Print the last section
        if current_section and section_content:
            print(colored(prompt_sections[current_section][0], prompt_sections[current_section][1], attrs=['bold']))
            print('\n'.join(section_content))
            print()
        
        # If we didn't find any sections, just print the raw content
        if not any(section in content for section in prompt_sections):
            # Try YAML parsing first
            try:
                data = yaml.safe_load(content)
                
                # Print prompt sections from YAML
                if 'system_prompt' in data:
                    print(colored("SYSTEM PROMPT:", 'cyan', attrs=['bold']))
                    print(textwrap.fill(data['system_prompt'], width=80))
                    print()
                
                if 'user_prompt' in data:
                    print(colored("USER PROMPT:", 'magenta', attrs=['bold']))
                    print(textwrap.fill(data['user_prompt'], width=80))
                    print()
                
                # Print other sections
                for key, value in data.items():
                    if key not in ['description', 'version', 'author', 'date', 'system_prompt', 'user_prompt']:
                        print(colored(f"{key.upper()}:", 'blue', attrs=['bold']))
                        if isinstance(value, str):
                            print(textwrap.fill(value, width=80))
                        else:
                            print(yaml.dump(value, default_flow_style=False))
                        print()
            except:
                # If YAML parsing fails, print the raw content
                # But exclude the metadata sections we already displayed
                print(colored("CONTENT:", 'blue', attrs=['bold']))
                print("\n".join(line for line in content.split('\n') 
                              if not line.strip().startswith(('PROMPT_AUTHOR:', 'PROMPT_AUTHOR_INSTITUTION:', 
                                                           'PROMPT_NAME:', 'PROMPT_VERSION:', 'PROMPT_DESCRIPTION:'))))
        
        print("="*80 + "\n")
    
    except Exception as e:
        print(f"Error reading prompt file: {e}")

def fetch_prompts_from_server(server_url, api_token=None, specific_prompt=None, full_details=False):
    """
    Fetch prompt information from a VoucherVisionGO server
    
    Args:
        server_url (str): URL of the VoucherVisionGO server (e.g., https://example.com)
        api_token (str, optional): API token for authentication
        specific_prompt (str, optional): Name of a specific prompt to fetch
        full_details (bool, optional): Whether to fetch full prompt details
        
    Returns:
        dict: Server response containing prompt information
    """
    # Construct the URL
    endpoint = f"{server_url.rstrip('/')}/prompts"
    
    # Add query parameters
    params = {}
    if specific_prompt:
        params['prompt'] = specific_prompt
    if full_details:
        params['view'] = 'true'
    
    # Set up headers
    headers = {
        'Accept': 'application/json',
    }
    
    # Add API token if provided
    if api_token:
        headers['X-API-Token'] = api_token
        # Also add as query param for ease of testing
        params['api_token'] = api_token
    
    try:
        # Make the request
        response = requests.get(endpoint, params=params, headers=headers)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        
        # Parse JSON response
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching prompts from server: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"Server error: {error_detail.get('message', 'Unknown error')}")
            except:
                print(f"Server returned: {e.response.status_code} {e.response.text}")
        return None

def display_prompts_from_server(server_response, format_output=True):
    """
    Display prompt information fetched from the server
    
    Args:
        server_response (dict): Response from the server
        format_output (bool): Whether to format the output with colors and tables
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not server_response or server_response.get('status') != 'success':
        error_msg = "Unknown error"
        if server_response and 'message' in server_response:
            error_msg = server_response['message']
        print(f"Failed to retrieve prompts: {error_msg}")
        return False
    
    # Check if this is a list of prompts or details of a specific prompt
    if 'prompts' in server_response:
        # List of prompts
        prompts = server_response['prompts']
        count = server_response['count']
        
        if format_output:
            # Format as a table
            table_data = []
            for i, prompt in enumerate(prompts, 1):
                # Format the description with proper text wrapping
                wrapped_description = textwrap.fill(prompt.get('description', ''), width=50)
                
                table_data.append([
                    i,
                    prompt.get('filename', ''),
                    wrapped_description,
                    prompt.get('version', 'Unknown'),
                    prompt.get('author', 'Unknown'),
                    prompt.get('institution', 'Unknown')
                ])
            
            print("\nAvailable Prompt Templates:")
            print(tabulate(table_data, headers=['#', 'Filename', 'Description', 'Version', 'Author', 'Institution'], 
                        tablefmt='grid', maxcolwidths=[None, 30, 50, 15, 20, 25]))
            print(f"\nTotal: {count} prompt file(s) found on server")
        else:
            # Return raw data
            print(json.dumps(server_response, indent=2))
        
        return True
    
    elif 'prompt' in server_response:
        # Specific prompt details
        prompt = server_response['prompt']
        
        if format_output:
            print("\n" + "="*80)
            print(colored(f"PROMPT FILE: {prompt.get('filename', 'Unknown')}", 'green', attrs=['bold']))
            print("="*80 + "\n")
            
            # Print metadata section
            print(colored("METADATA:", 'yellow', attrs=['bold']))
            print(f"Name: {prompt.get('name', 'Unknown')}")
            print(f"Description: {prompt.get('description', 'No description provided')}")
            print(f"Version: {prompt.get('version', 'Unknown')}")
            print(f"Author: {prompt.get('author', 'Unknown')}")
            print(f"Institution: {prompt.get('institution', 'Unknown')}")
            print()
            
            # Print details sections if available
            if 'details' in prompt and 'sections' in prompt['details']:
                sections = prompt['details']['sections']
                
                # Print priority sections first
                priority_sections = ['system_prompt', 'user_prompt', 'examples', 'fields']
                for section_key in priority_sections:
                    if section_key in sections:
                        section_title = section_key.replace('_', ' ').title()
                        print(colored(f"{section_title}:", 'cyan', attrs=['bold']))
                        print(sections[section_key])
                        print()
                
                # Print remaining sections
                for key, value in sections.items():
                    if key not in priority_sections and key != 'raw_content':
                        section_title = key.replace('_', ' ').title()
                        print(colored(f"{section_title}:", 'blue', attrs=['bold']))
                        if isinstance(value, str):
                            print(value)
                        else:
                            print(yaml.dump(value, default_flow_style=False))
                        print()
            
            # If no sections available but we have raw content
            elif 'details' in prompt and 'raw_content' in prompt['details']:
                print(colored("Raw Content:", 'blue', attrs=['bold']))
                print(prompt['details']['raw_content'])
            
            print("="*80 + "\n")
        else:
            # Return raw data
            print(json.dumps(server_response, indent=2))
        
        return True
    
    else:
        print("Unexpected server response format")
        return False

def main():
    parser = argparse.ArgumentParser(description='List and view VoucherVision prompt templates')
    
    # File-based options
    file_group = parser.add_argument_group('Local File Options')
    file_group.add_argument('--dir', default='./prompts', 
                       help='Directory containing prompt templates (default: ./prompts)')
    file_group.add_argument('--view', action='store_true',
                       help='View contents of a selected prompt')
    file_group.add_argument('--prompt', 
                       help='Specific prompt file to view (filename only, not full path)')
    
    # Server-based options
    server_group = parser.add_argument_group('Server API Options')
    server_group.add_argument('--server', 
                         help='URL of VoucherVisionGO server (e.g., https://example.com)')
    server_group.add_argument('--token', 
                         help='API token for server authentication')
    server_group.add_argument('--raw', action='store_true',
                         help='Output raw JSON instead of formatted text')
    
    args = parser.parse_args()
    
    # Check if server mode is requested
    if args.server:
        # Server API mode
        if args.prompt:
            # Fetch specific prompt from server
            response = fetch_prompts_from_server(
                args.server, 
                api_token=args.token, 
                specific_prompt=args.prompt,
                full_details=True
            )
        else:
            # Fetch list of prompts from server
            response = fetch_prompts_from_server(
                args.server,
                api_token=args.token,
                full_details=args.view
            )
        
        # Display the server response
        if response:
            display_prompts_from_server(response, format_output=not args.raw)
        
    else:
        # Local file mode
        prompt_files = list_prompts(args.dir)
        
        if not prompt_files:
            print(f"No prompt files found in '{args.dir}'")
            return
        
        # If a specific prompt was requested
        if args.prompt:
            target_file = None
            for file in prompt_files:
                if file.name == args.prompt:
                    target_file = file
                    break
                
            if target_file:
                display_prompt_contents(target_file)
            else:
                print(f"Prompt file '{args.prompt}' not found.")
                print("Available prompts:")
                for file in prompt_files:
                    print(f"  {file.name}")
        
        # Otherwise list all prompts
        else:
            prompt_info_list = [extract_prompt_info(file) for file in prompt_files]
            
            # Print table of available prompts
            table_data = []
            for i, info in enumerate(prompt_info_list, 1):
                # Format the description with proper text wrapping
                wrapped_description = textwrap.fill(info['description'], width=50)
                
                table_data.append([
                    i,
                    info['filename'],
                    wrapped_description,
                    info['version'],
                    info['author'],
                    info['institution']
                ])
            
            print("\nAvailable Prompt Templates:")
            print(tabulate(table_data, headers=['#', 'Filename', 'Description', 'Version', 'Author', 'Institution'], 
                        tablefmt='grid', maxcolwidths=[None, 30, 50, 15, 20, 25]))
            print(f"\nTotal: {len(prompt_files)} prompt file(s) found in '{args.dir}'")
            
            # If view flag is set, prompt user to select one
            if args.view and prompt_files:
                try:
                    selection = input("\nEnter prompt number to view (or 'q' to quit): ")
                    if selection.lower() != 'q':
                        idx = int(selection) - 1
                        if 0 <= idx < len(prompt_files):
                            display_prompt_contents(prompt_files[idx])
                        else:
                            print("Invalid selection.")
                except ValueError:
                    print("Invalid input. Please enter a number.")
                except KeyboardInterrupt:
                    print("\nOperation cancelled.")

if __name__ == "__main__":
    main()

# Usage examples:
# Local file usage:
# python list_prompts.py --dir ./prompts
# python list_prompts.py --dir ./prompts --view
# python list_prompts.py --dir ./prompts --prompt SLTPvM_default.yaml
#
# Server API usage:
# python list_prompts.py --server https://yourserver.com
# python list_prompts.py --server https://yourserver.com --token your_api_token
# python list_prompts.py --server https://yourserver.com --prompt SLTPvM_default.yaml
# python list_prompts.py --server https://yourserver.com --prompt SLTPvM_default.yaml --ra