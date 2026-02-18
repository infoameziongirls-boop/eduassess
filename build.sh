#!/bin/bash
# Render build script
# Runs during deployment to initialize the application

echo "=================================================="
echo "EDUASSESS - RENDER BUILD PROCESS"
echo "=================================================="

echo ""
echo "Step 1: Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Step 2: Initializing application..."
python startup.py

echo ""
echo "Step 3: Running health check..."
python db_health_check.py

echo ""
echo "✓ Build process completed successfully!"
echo "=================================================="
