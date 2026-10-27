#!/usr/bin/env bash
# Unified CI verification script for Linux / macOS / WSL
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
echo "Step 1: Running pre-commit hooks..."
echo "=========================================="
pre-commit run --all-files

echo ""
echo "=========================================="
echo "Step 2: Running Pyright type checker..."
echo "=========================================="
npx --yes pyright

echo ""
echo "=========================================="
echo "Step 3: Running pytest suite..."
echo "=========================================="
pytest --tb=short -m "not flaky_ci" -q

echo ""
echo "=========================================="
echo "All CI verification gates passed cleanly!"
echo "=========================================="
