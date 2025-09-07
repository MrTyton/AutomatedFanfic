#!/usr/bin/env python3
"""
Script to revert unit test imports back to direct imports.
"""

import re
from pathlib import Path

def revert_test_file_imports(file_path: Path) -> bool:
    """Revert imports in a single test file to direct imports."""
    print(f"Processing {file_path}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Convert 'from app import module' back to 'import module'
    content = re.sub(
        r'^from app import ([a-zA-Z_][a-zA-Z0-9_]*)$',
        r'import \1',
        content,
        flags=re.MULTILINE
    )
    
    # Convert 'from app.module import ...' back to 'from module import ...'
    content = re.sub(
        r'^from app\.([a-zA-Z_][a-zA-Z0-9_]*) import',
        r'from \1 import',
        content,
        flags=re.MULTILINE
    )
    
    # Write back to file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Reverted {file_path}")
    return True

def main():
    """Revert all test files."""
    unit_test_dir = Path("unit")
    
    if not unit_test_dir.exists():
        print("Error: unit test directory not found. Run from tests/ directory.")
        return
    
    test_files = list(unit_test_dir.glob("test_*.py"))
    
    print(f"Found {len(test_files)} test files to revert")
    
    for test_file in test_files:
        try:
            revert_test_file_imports(test_file)
        except Exception as e:
            print(f"  ✗ Error reverting {test_file}: {e}")
    
    print("\nDone reverting all test files!")

if __name__ == "__main__":
    main()
