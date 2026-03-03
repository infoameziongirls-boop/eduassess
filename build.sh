#!/bin/bash
# Render build script - Database initialization moved to runtime (gunicorn startup)
# The build phase does not have access to PostgreSQL or the persistent disk

echo "=================================================="
echo "EDUASSESS - RENDER BUILD PROCESS"
echo "=================================================="

echo ""
echo "Step 1: Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✓ Build completed successfully!"
echo "   Database initialization will run when the app starts."
echo "=================================================="
