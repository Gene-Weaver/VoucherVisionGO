#!/usr/bin/env python
"""
List and display custom prompts for VoucherVision

This utility lists available prompt templates in the specified directory
and allows viewing the contents of selected prompts.
"""

import os
import sys
import argparse
import yaml
import textwrap
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

def main():
    parser = argparse.ArgumentParser(description='List and view VoucherVision prompt templates')
    parser.add_argument('--dir', default='./prompts', 
                        help='Directory containing prompt templates (default: ./prompts)')
    parser.add_argument('--view', action='store_true',
                        help='View contents of a selected prompt')
    parser.add_argument('--prompt', 
                        help='Specific prompt file to view (filename only, not full path)')
    
    args = parser.parse_args()
    
    # List available prompts
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
# python list_prompts.py --dir ./prompts
# python list_prompts.py --dir ./prompts --view
# python list_prompts.py --dir ./prompts --prompt SLTPvM_default.yaml