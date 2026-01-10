.PHONY: help setup start stop restart logs test clean

help:
	@echo "Podcast Language Converter - Makefile"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup      - Setup environment and assets"
	@echo "  make start      - Start all services (docker-compose)"
	@echo "  make stop       - Stop all services"
	@echo "  make restart    - Restart all services"
	@echo "  make logs       - Show logs (follow mode)"
	@echo "  make test       - Run unit tests"
	@echo "  make clean      - Clean data and temp files"

setup:
	@echo "Setting up environment..."
	cp -n .env.example .env || true
	python3 setup_assets.py
	@echo "✓ Setup complete! Edit .env with your API keys"

start:
	@echo "Starting services..."
	docker-compose up -d
	@echo "✓ Services started!"
	@echo "  Web UI: http://localhost:8000"
	@echo "  API docs: http://localhost:8000/docs"

stop:
	@echo "Stopping services..."
	docker-compose down

restart:
	@echo "Restarting services..."
	docker-compose restart

logs:
	docker-compose logs -f

logs-backend:
	docker-compose logs -f backend

logs-worker:
	docker-compose logs -f worker

test:
	@echo "Running tests..."
	pytest -v

test-coverage:
	@echo "Running tests with coverage..."
	pytest --cov=backend --cov-report=html tests/
	@echo "Coverage report: htmlcov/index.html"

clean:
	@echo "Cleaning temporary files..."
	rm -rf data/*
	rm -rf output/*
	rm -rf __pycache__
	rm -rf backend/__pycache__
	rm -rf backend/**/__pycache__
	rm -rf .pytest_cache
	@echo "✓ Cleaned!"

dev-install:
	@echo "Installing development dependencies..."
	pip install -r requirements.txt
	pip install black flake8 mypy pre-commit
	pre-commit install
	@echo "✓ Dev environment ready!"
