exec > "$1/aff.log" 2>&1
set -x
echo "Activating virtual environment..."
source "$1/.venv/bin/activate"

echo "Changing directory..."
cd "$1/root/app"

echo "Running Python script..."
"$1/.venv/bin/python" -u fanficdownload.py --verbose