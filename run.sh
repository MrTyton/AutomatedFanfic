#!/bin/bash
# run.sh - Start AutomatedFanfic from within its virtual environment
# Usage: ./run.sh /path/to/install/location
# Example: ./run.sh ~/AutomatedFanfic

if [ -z "$1" ]; then
  echo "Usage: $0 /path/to/install/location"
  exit 1
fi

exec > "$1/aff.log" 2>&1
set -x

echo "Activating virtual environment..."
source "$1/.venv/bin/activate"

echo "Changing directory..."
cd "$1/root/app"

echo "Running Python script..."
"$1/.venv/bin/python" -u fanficdownload.py
