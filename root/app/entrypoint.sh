#!/bin/sh
# Exit immediately if a command exits with a non-zero status.
set -e

# Check the VERBOSE environment variable and prepare arguments
if [ "$VERBOSE" = "true" ]; then
  exec python -u /app/fanficdownload.py --config="/config/config.toml" --verbose
else
  exec python -u /app/fanficdownload.py --config="/config/config.toml"
fi
