#!/bin/bash
# Setup Streamlit Authenticator

set -e

echo "=================================================="
echo "  AI News Aggregator - Authentication Setup"
echo "=================================================="
echo ""

# Detect if we're in a virtual environment or on EC2
PYTHON_BIN="python"
PIP_BIN="pip"

# Check for /opt/ainews venv (EC2 deployment)
if [ -f "/opt/ainews/venv/bin/python" ]; then
    PYTHON_BIN="/opt/ainews/venv/bin/python"
    PIP_BIN="/opt/ainews/venv/bin/pip"
    echo "Detected EC2 deployment - using virtual environment"
# Check for local venv
elif [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
    PIP_BIN="venv/bin/pip"
    echo "Detected local virtual environment"
# Check if we're already in an activated venv
elif [ -n "$VIRTUAL_ENV" ]; then
    echo "Using activated virtual environment"
else
    echo "Using system Python (consider using a virtual environment)"
fi

echo ""

# Check if auth_config.yaml already exists
if [ -f "auth_config.yaml" ]; then
    echo "⚠️  auth_config.yaml already exists!"
    read -p "Overwrite it? (y/N): " confirm
    if [ "$confirm" != "y" ]; then
        echo "Cancelled."
        exit 0
    fi
fi

# Install streamlit-authenticator if needed
echo "[1/4] Checking dependencies..."
if ! $PYTHON_BIN -c "import streamlit_authenticator" 2>/dev/null; then
    echo "Installing streamlit-authenticator..."
    $PIP_BIN install streamlit-authenticator
else
    echo "✓ streamlit-authenticator already installed"
fi

# Copy example config
echo ""
echo "[2/4] Creating auth_config.yaml from template..."
cp auth_config.example.yaml auth_config.yaml

# Generate random cookie key
echo ""
echo "[3/4] Generating secure cookie key..."
COOKIE_KEY=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(32))")
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s/change_this_to_a_random_string_32_characters_long/$COOKIE_KEY/" auth_config.yaml
else
    # Linux
    sed -i "s/change_this_to_a_random_string_32_characters_long/$COOKIE_KEY/" auth_config.yaml
fi

# Generate password
echo ""
echo "[4/4] Setting admin password..."
echo ""
echo "The default password is 'changeme123'"
read -p "Would you like to set a custom password now? (y/N): " set_password

if [ "$set_password" = "y" ]; then
    $PYTHON_BIN scripts/generate_password_hash.py
    echo ""
    echo "Copy the hash above and paste it into auth_config.yaml"
    echo "at line 10 (replace the existing password hash)"
else
    echo ""
    echo "Using default password: changeme123"
    echo "⚠️  IMPORTANT: Change this before deploying!"
fi

echo ""
echo "=================================================="
echo "  ✓ Authentication Setup Complete!"
echo "=================================================="
echo ""
echo "Configuration file: auth_config.yaml"
echo ""
echo "Default credentials:"
echo "  Username: admin"
echo "  Password: changeme123"
echo ""
echo "To add more users or change passwords:"
echo "  1. Run: python scripts/generate_password_hash.py"
echo "  2. Edit auth_config.yaml"
echo "  3. Add new username entries under 'credentials > usernames'"
echo ""
echo "To disable authentication:"
echo "  Delete or rename auth_config.yaml"
echo ""
echo "Start the dashboard:"
echo "  streamlit run dashboard.py"
echo ""
