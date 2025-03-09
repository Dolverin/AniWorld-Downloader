#!/usr/bin/env python3
"""
Script zum Beheben häufiger Linting-Probleme in Python-Dateien.

Dieses Script wendet Autoformatierung mit autopep8 an,
sortiert Imports mit isort und behebt einige häufige Linting-Probleme.
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path


def install_dependencies():
    """Installiert erforderliche Abhängigkeiten, falls sie nicht vorhanden sind."""
    try:
        # Prüfe, ob autopep8 installiert ist
        import autopep8  # noqa: F401
    except ImportError:
        print("Installing autopep8...")
        subprocess.run([sys.executable, "-m", "pip", "install", "autopep8"], check=True)

    try:
        # Prüfe, ob isort installiert ist
        import isort  # noqa: F401
    except ImportError:
        print("Installing isort...")
        subprocess.run([sys.executable, "-m", "pip", "install", "isort"], check=True)


def find_python_files(directory):
    """Findet alle Python-Dateien in einem Verzeichnis."""
    return list(Path(directory).glob("**/*.py"))


def apply_fixes(files, verbose=False):
    """Wendet Linting-Fixes auf die angegebenen Dateien an."""
    for file in files:
        if verbose:
            print(f"Processing {file}...")
        
        # Fix imports with isort
        subprocess.run(["isort", str(file)], check=False)
        
        # Apply autopep8 fixes
        subprocess.run([
            "autopep8",
            "--in-place",
            "--aggressive",
            "--aggressive",
            str(file)
        ], check=False)
        
        if verbose:
            print(f"Fixed {file}")


def main():
    parser = argparse.ArgumentParser(description="Fix common linting issues in Python files")
    parser.add_argument(
        "directory",
        nargs="?",
        default="src",
        help="Directory to process (default: src)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check, don't fix"
    )
    
    args = parser.parse_args()
    
    # Install dependencies if needed
    install_dependencies()
    
    # Find Python files
    directory = args.directory
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a directory")
        return 1
    
    files = find_python_files(directory)
    if not files:
        print(f"No Python files found in {directory}")
        return 0
    
    if args.verbose:
        print(f"Found {len(files)} Python files")
    
    if args.check_only:
        # Just list the files that would be processed
        for file in files:
            print(file)
        return 0
    
    # Apply fixes
    apply_fixes(files, args.verbose)
    
    print(f"Successfully processed {len(files)} Python files")
    return 0


if __name__ == "__main__":
    sys.exit(main()) 