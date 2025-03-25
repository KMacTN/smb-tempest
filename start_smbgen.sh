#!/bin/bash
#===============================================================================
#
#  Wrapper Script: start_smbgen.sh
#
#  Description:
#      This script launches the SMB Session Generator Python application
#      (smbgen.py) with pre-configured parameters inside a Python virtual
#      environment.
#
#  Note:
#      This is an optional "Helper Script" used to pre-set the values for a simple rerun.
#
#  Pre-requisites:
#      - A Python virtual environment must exist at the specified VENV_PATH.
#      - The Python script smbgen.py must exist at the specified PYTHON_SCRIPT location.
#
#  Usage:
#      ./start_smbgen.sh
#
#  Author: KMac (kmac@qumulo.com)
#  Date:   March 24, 2025
#
#===============================================================================

set -e
set -u

VENV_PATH="$HOME/Documents/venv/Scripts/activate"
PYTHON_SCRIPT="/q/smbgen.py"

USERNAME="admin"
PASSWORD="YOUR_PASSWORD_HERE"
SERVER_IP="SMB_SERVER_IP_ADDRESS"
SHARE_NAME="YOUR_SHARENAME"
NUM_ACTIVE_FILES=1
NUM_INACTIVE_SESSIONS=0

if [[ ! -f "$VENV_PATH" ]]; then
  echo "Error: Virtual environment activation script not found: $VENV_PATH"
  exit 1
fi

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  echo "Activating the Python virtual environment..."
  source "$VENV_PATH"
fi

if [[ ! -f "$PYTHON_SCRIPT" ]]; then
  echo "Error: Python script not found: $PYTHON_SCRIPT"
  exit 1
fi

echo "Launching the SMB Session Generator script: $PYTHON_SCRIPT..."

"$VIRTUAL_ENV/Scripts/python" "$PYTHON_SCRIPT" \
  --username "$USERNAME" \
  --password "$PASSWORD" \
  --server_ip "$SERVER_IP" \
  --share_name "$SHARE_NAME" \
  --num_inactive_sessions "$NUM_INACTIVE_SESSIONS" \
  --num_active_files "$NUM_ACTIVE_FILES"

EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo "SMB Session Generator executed successfully."
else
  echo "SMB Session Generator returned an error. Exit code: $EXIT_CODE"
fi

