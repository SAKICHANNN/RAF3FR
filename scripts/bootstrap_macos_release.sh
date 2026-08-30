#!/bin/zsh
set -euo pipefail

project_root=${0:A:h:h}
venv="$project_root/.tools/macos-packaging-venv"
python3 -m venv --clear "$venv"
"$venv/bin/python" -m pip install --index-url https://pypi.org/simple --timeout 300 \
  -r "$project_root/apps/macos/Support/requirements-packaging.txt"
"$venv/bin/python" -m pip check
"$venv/bin/python" -c 'import numpy; assert numpy.__version__ == "2.0.2", numpy.__version__'
