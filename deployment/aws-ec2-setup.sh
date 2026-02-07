#!/bin/bash
# AWS EC2 Deployment Script for AI News Aggregator
# Supports: Ubuntu 22.04+ and Amazon Linux 2023

set -e

echo "=== AI News Aggregator - EC2 Setup ==="

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
else
    echo "ERROR: Cannot detect OS. This script supports Ubuntu 22.04+ and Amazon Linux 2023."
    exit 1
fi

echo "Detected OS: $OS $VERSION"

# Update system and install packages based on OS
if [ "$OS" = "ubuntu" ]; then
    echo "Installing packages for Ubuntu..."
    sudo apt update && sudo apt upgrade -y

    # Install Python 3.12
    sudo add-apt-repository ppa:deadsnakes/ppa -y
    sudo apt update
    sudo apt install python3.12 python3.12-venv python3.12-dev -y

    # Install Nginx and rsync
    sudo apt install nginx rsync -y

elif [ "$OS" = "amzn" ]; then
    echo "Installing packages for Amazon Linux 2023..."
    sudo dnf update -y

    # Install Python 3.12 (available in AL2023 repos)
    sudo dnf install -y python3.12 python3.12-pip python3.12-devel

    # Install Nginx, rsync, and cronie (for crontab)
    sudo dnf install -y nginx rsync cronie

    # Enable and start cronie service for crontab
    sudo systemctl enable crond
    sudo systemctl start crond

else
    echo "ERROR: Unsupported OS: $OS"
    echo "This script supports Ubuntu 22.04+ and Amazon Linux 2023 only."
    exit 1
fi

# Create application directory
APP_DIR="/opt/ainews"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo "Copying application files from $PROJECT_ROOT to $APP_DIR..."

# Copy application files (excluding venv, data, etc.)
rsync -av --exclude='.git' \
    --exclude='venv' \
    --exclude='.venv*' \
    --exclude='data/*.db' \
    --exclude='data/*.log' \
    --exclude='data/*.xml' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='config.yaml' \
    "$PROJECT_ROOT/" "$APP_DIR/"

# Verify requirements.txt exists
if [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo "ERROR: requirements.txt not found in $APP_DIR"
    echo "Please ensure you're running this script from the project directory."
    exit 1
fi

# Set up config.yaml from example
echo ""
echo "Setting up configuration..."
if [ ! -f "$APP_DIR/config.example.yaml" ]; then
    echo "ERROR: config.example.yaml not found!"
    exit 1
fi

if [ ! -f "$APP_DIR/config.yaml" ]; then
    cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"
    echo "✓ Created config.yaml from config.example.yaml"
else
    echo "✓ config.yaml already exists (not overwriting)"
fi

# Prompt for Anthropic API key
echo ""
echo "Anthropic API Key Setup:"
read -p "Would you like to set your Anthropic API key now? (y/N): " set_api_key

if [ "$set_api_key" = "y" ] || [ "$set_api_key" = "Y" ]; then
    read -p "Enter your Anthropic API key: " api_key
    if [ -n "$api_key" ]; then
        # Update the API key in config.yaml
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s/your_anthropic_api_key_here/$api_key/" "$APP_DIR/config.yaml"
        else
            # Linux
            sed -i "s/your_anthropic_api_key_here/$api_key/" "$APP_DIR/config.yaml"
        fi
        echo "✓ API key configured in config.yaml"
    else
        echo "⚠️  No API key entered. You'll need to edit config.yaml manually."
    fi
else
    echo "⚠️  Skipped API key setup. Remember to edit config.yaml before running the pipeline."
fi

# Create virtual environment
cd $APP_DIR
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Install Playwright system dependencies (OS-specific)
if [ "$OS" = "ubuntu" ]; then
    playwright install-deps chromium
elif [ "$OS" = "amzn" ]; then
    # AL2023: Manually install Playwright dependencies
    echo "Installing Playwright dependencies for Amazon Linux 2023..."
    sudo dnf install -y \
        alsa-lib \
        atk \
        cups-libs \
        libdrm \
        libX11 \
        libXcomposite \
        libXdamage \
        libXext \
        libXfixes \
        libXrandr \
        libgbm \
        libxcb \
        libxkbcommon \
        mesa-libgbm \
        nss \
        pango || echo "WARNING: Some Playwright dependencies may not be available on AL2023"
fi

# Create systemd service for Streamlit
sudo tee /etc/systemd/system/ainews-dashboard.service > /dev/null <<EOF
[Unit]
Description=AI News Aggregator Dashboard
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/streamlit run dashboard.py --server.port 8501 --server.address 127.0.0.1
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Configure Nginx reverse proxy (OS-specific)
if [ "$OS" = "ubuntu" ]; then
    echo "Configuring Nginx for Ubuntu (sites-available/sites-enabled pattern)..."

    sudo tee /etc/nginx/sites-available/ainews > /dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /rss {
        alias /opt/ainews/data;
        autoindex off;
        location ~ \.xml$ {
            add_header Content-Type application/rss+xml;
        }
    }
}
EOF

    sudo ln -sf /etc/nginx/sites-available/ainews /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default

elif [ "$OS" = "amzn" ]; then
    echo "Configuring Nginx for Amazon Linux 2023 (conf.d pattern)..."

    # Create main nginx.conf
    sudo tee /etc/nginx/nginx.conf > /dev/null <<'EOF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    types_hash_max_size 2048;
    access_log /var/log/nginx/access.log;
    sendfile on;
    keepalive_timeout 65;
    include /etc/nginx/conf.d/*.conf;
}
EOF

    # Create site config
    sudo tee /etc/nginx/conf.d/ainews.conf > /dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /rss {
        alias /opt/ainews/data;
        autoindex off;
        location ~ \.xml$ {
            add_header Content-Type application/rss+xml;
        }
    }
}
EOF
fi

# Test and restart Nginx
echo "Testing Nginx configuration..."
sudo nginx -t
echo "Starting Nginx..."
sudo systemctl enable nginx
sudo systemctl restart nginx

# Create cron job for fetch pipeline (every 15 minutes)
(crontab -l 2>/dev/null || echo ""; echo "# AI News Aggregator - Run pipeline every 15 minutes") | crontab -
(crontab -l; echo "*/15 * * * * cd $APP_DIR && $APP_DIR/venv/bin/python fetch_news.py >> $APP_DIR/data/pipeline.log 2>&1") | crontab -

# Start dashboard service
sudo systemctl daemon-reload
sudo systemctl enable ainews-dashboard
sudo systemctl start ainews-dashboard

# Verify critical files exist
echo ""
echo "Verifying installation..."
for file in "config.yaml" "dashboard.py" "fetch_news.py" "requirements.txt"; do
    if [ -f "$APP_DIR/$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file MISSING!"
        exit 1
    fi
done

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "OS: $OS $VERSION"
echo "Python: $(python3.12 --version)"
echo "Nginx: $(nginx -v 2>&1)"
echo ""
echo "Next steps:"
echo "1. If you didn't set your API key during setup, edit config.yaml:"
echo "   nano $APP_DIR/config.yaml"
echo ""
echo "2. Check dashboard status:"
echo "   sudo systemctl status ainews-dashboard"
echo ""
echo "3. View dashboard logs:"
echo "   sudo journalctl -u ainews-dashboard -f"
echo ""
echo "4. Run the pipeline manually:"
echo "   cd $APP_DIR && ./venv/bin/python fetch_news.py"
echo ""
echo "5. Access dashboard at: http://YOUR_EC2_PUBLIC_IP/"
echo "6. RSS feed available at: http://YOUR_EC2_PUBLIC_IP/rss/high_priority.xml"
echo ""
echo "⚠️  IMPORTANT - Security Group Configuration:"
echo "=================================================="
echo ""
echo "Your EC2 security group MUST allow these inbound rules:"
echo "  • HTTP (port 80) from 0.0.0.0/0"
echo "  • HTTPS (port 443) from 0.0.0.0/0 (if using SSL)"
echo "  • SSH (port 22) from YOUR_IP/32 (for management)"
echo ""
echo "Without port 80 open, the dashboard won't be accessible!"
echo ""
echo "To check if it's working:"
echo "  1. Get your EC2 public IP: curl -4 ifconfig.me"
echo "  2. Visit: http://YOUR_EC2_PUBLIC_IP/"
echo "  3. Check Nginx status: sudo systemctl status nginx"
echo "  4. Check Streamlit status: sudo systemctl status ainews-dashboard"
echo ""
echo "Next steps:"
echo "  • Set up an Elastic IP for a stable address"
echo "  • Configure SSL with Let's Encrypt: sudo certbot --nginx -d yourdomain.com"
echo "  • Enable authentication: ./deployment/add-basic-auth.sh"
echo ""
echo "Troubleshooting:"
echo "  • If you can't connect: Check security group allows port 80"
echo "  • Test Nginx: curl http://localhost"
echo "  • Test Streamlit: curl http://localhost:8501"
echo "  • View logs: sudo journalctl -u ainews-dashboard -f"
