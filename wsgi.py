"""
WSGI Entry Point for Production (Render + Gunicorn)
This is what Render uses to start your application.
"""
import os
import sys

# Make sure Python can find your app files
sys.path.insert(0, os.path.dirname(__file__))

# Import the Flask app
from app import app

# Required by gunicorn
application = app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)