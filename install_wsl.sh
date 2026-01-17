#!/bin/bash
# WSL Installation Script for Podcast Editor
# Sets up all system dependencies and Python packages

set -e  # Exit on error

echo "==================================================="
echo "Installing Podcast Editor dependencies on WSL"
echo "==================================================="

# Update system
echo ""
echo "[1/4] Updating system packages..."
sudo apt update

# Install system dependencies
echo ""
echo "[2/4] Installing system dependencies..."
sudo apt install -y \
    ffmpeg \
    python3-pip \
    python3-venv \
    redis-server

# Check Python version
echo ""
echo "[3/4] Checking Python version..."
python3 --version

# Install Python packages
echo ""
echo "[4/4] Installing Python packages..."

# First install PyTorch with CUDA support
echo "Installing PyTorch with CUDA 12.1..."
python -m pip install torch==2.1.1 torchvision==0.16.1 torchaudio==2.1.1 --index-url https://download.pytorch.org/whl/cu121

# Install other requirements
echo "Installing other requirements..."
python -m pip install -r requirements.txt

echo ""
echo "==================================================="
echo "✅ Installation complete!"
echo "==================================================="
echo ""
echo "Next steps:"
echo "1. Make sure Redis is running: sudo service redis-server start"
echo "2. Configure .env file with your API keys"
echo "3. Start Celery worker: celery -A backend.celery_app worker --loglevel=info"
echo "4. Start web server: python -m uvicorn backend.main:app --reload"
echo ""
echo "To test audio enhancement:"
echo "  python test_audio_enhancement.py <job_id>"
echo ""
