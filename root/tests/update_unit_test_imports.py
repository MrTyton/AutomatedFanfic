#!/usr/bin/env python3
"""
Script to update all unit test imports to use 'from app import' style
instead of sys.path manipulation.
"""

import re
from pathlib import Path
from typing import List, Tuple

def update_test_file_imports(file_path: Path) -> bool:
    """Update imports in a single test file."""
    print(f"Processing {file_path}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove sys.path manipulation block
    lines = content.split('\n')
    new_lines = []
    skip_lines = False
    
    for line in lines:
        # Skip sys.path manipulation block
        if 'sys.path.insert' in line or (skip_lines and line.strip() == ''):
            skip_lines = True
            continue
        
        # Stop skipping after the sys.path block
        if skip_lines and (line.startswith('from ') or line.startswith('import ')):
            skip_lines = False
        
        # Skip sys and pathlib imports that were only used for path manipulation
        if skip_lines:
            continue
            
        if (line.strip().startswith('import sys') or 
            line.strip().startswith('from pathlib import Path') or
            '# Add app directory to path for imports' in line):
            continue
            
        new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    # Define app modules that need to be imported with 'from app import'
    app_modules = [
        'fanficdownload', 'url_worker', 'url_ingester', 'ff_waiter', 
        'regex_parsing', 'fanfic_info', 'calibre_info', 'notification_wrapper',
        'notification_base', 'apprise_notification', 'ff_logging',
        'system_utils', 'process_manager'
    ]
    
    # Update imports to use 'from app import' style
    for module in app_modules:
        # Replace 'import module' with 'from app import module'
        content = re.sub(
            rf'^import {module}$',
            f'from app import {module}',
            content,
            flags=re.MULTILINE
        )
        
        # Replace 'from module import ...' with 'from app.module import ...'
        content = re.sub(
            rf'^from {module} import',
            f'from app.{module} import',
            content,
            flags=re.MULTILINE
        )
    
    # Handle config_models special case
    content = re.sub(
        r'^from config_models import',
        'from app.config_models import',
        content,
        flags=re.MULTILINE
    )
    
    # Write back to file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Updated {file_path}")
    return True

def main():
    """Update all test files."""
    unit_test_dir = Path("unit")
    
    if not unit_test_dir.exists():
        print("Error: unit test directory not found. Run from tests/ directory.")
        return
    
    test_files = list(unit_test_dir.glob("test_*.py"))
    
    print(f"Found {len(test_files)} test files to update")
    
    for test_file in test_files:
        try:
            update_test_file_imports(test_file)
        except Exception as e:
            print(f"  ✗ Error updating {test_file}: {e}")
    
    print("\nDone updating all test files!")

if __name__ == "__main__":
    main()
