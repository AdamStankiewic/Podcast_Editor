FROM python:3.11

# Install system dependencies including Azure Speech SDK requirements
# Azure Speech SDK needs: OpenSSL, ALSA, C++ runtime, threading, atomic ops
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    libssl3 \
    libasound2 \
    libgcc-s1 \
    libstdc++6 \
    libgomp1 \
    libatomic1 \
    libc6 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data output assets frontend/static frontend/templates

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
