#!/usr/bin/env bash
set -euo pipefail

if ! command -v pip-compile >/dev/null 2>&1; then
  echo "pip-compile not found. Install pip-tools to generate lock files: pip install pip-tools"
  exit 1
fi

echo "Generating requirements.txt.lock from requirements.txt"
pip-compile --output-file=requirements.txt.lock requirements.txt
if [ -f requirements-dev.txt ]; then
  echo "Generating requirements-dev.txt.lock from requirements-dev.txt"
  pip-compile --output-file=requirements-dev.txt.lock requirements-dev.txt
fi

echo "Lock files generated."
