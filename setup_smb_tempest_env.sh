#!/bin/bash
################################################################################
# Script: setup_smb_tempest_env.sh
# Purpose: Interactive, safe setup for smb_tempest.py Python environment
# Author: KMac and Sheila
# Date: April 28th, 2025
################################################################################

set -e

PYTHON_VERSION_REQUIRED="3.10"
VENV_DIR="smb_tempest_env"

confirm_and_run() {
    local prompt_message="$1"
    local command_to_run="$2"
    echo "$prompt_message"
    echo -n "Proceed? [y/n]: "
    read answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        echo "Running: $command_to_run"
        eval "$command_to_run"
    else
        echo "You chose not to continue. Exiting."
        exit 1
    fi
}

echo "Checking Python 3 installation..."

# Check if python3 is installed
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python3 is not installed."
    if [[ "$(uname)" == "Darwin" ]]; then
        confirm_and_run "Would you like me to install python3 via Homebrew?" "brew install python"
    elif [[ -f /etc/debian_version ]]; then
        confirm_and_run "Would you like me to install python3 via apt?" "sudo apt update -y && sudo apt install -y python3"
    else
        echo "Unsupported OS. Please install Python 3 manually."
        exit 1
    fi
fi

# Correct Python version checking
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

REQUIRED_MAJOR=3
REQUIRED_MINOR=10

if (( PYTHON_MAJOR > REQUIRED_MAJOR )) || \
   (( PYTHON_MAJOR == REQUIRED_MAJOR && PYTHON_MINOR >= REQUIRED_MINOR )); then
    echo "Python version ${PYTHON_MAJOR}.${PYTHON_MINOR} is OK."
else
    echo "Python version ${PYTHON_MAJOR}.${PYTHON_MINOR} is too old. Please upgrade Python 3 manually."
    exit 1
fi

# Function to create virtual environment safely
create_virtualenv() {
    if ! python3 -m venv "$VENV_DIR"; then
        echo "Virtual environment creation failed. Checking for missing venv module..."

        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        VENV_PACKAGE="python${PYTHON_VERSION}-venv"

        echo "Looks like you may be missing $VENV_PACKAGE."

        confirm_and_run "Would you like me to install $VENV_PACKAGE now?" "sudo apt update -y && sudo apt install -y $VENV_PACKAGE"

        echo "Retrying virtual environment creation..."
        python3 -m venv "$VENV_DIR"
    fi
}

echo "Setting up virtual environment..."

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment..."
    create_virtualenv
    echo "Virtual environment created at $VENV_DIR."
else
    if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
        echo "Virtual environment appears incomplete. Recreating it..."
        rm -rf "$VENV_DIR"
        create_virtualenv
        echo "Virtual environment recreated at $VENV_DIR."
    else
        echo "Virtual environment already exists at $VENV_DIR."
    fi
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "Upgrading pip..."
pip install --upgrade pip

# Check if smbprotocol is installed
if ! python -c "import smbprotocol" >/dev/null 2>&1; then
    echo "smbprotocol module not found."
    confirm_and_run "Would you like me to install smbprotocol inside the virtual environment?" "pip install smbprotocol"
else
    echo "smbprotocol module already installed."
fi

echo "Freezing environment to requirements.txt..."
pip freeze > requirements.txt

echo ""
echo "✅ Virtual environment setup complete!"
echo "----------------------------------------"
echo "To activate it later, run:"
echo "  source $VENV_DIR/bin/activate"
echo "----------------------------------------"