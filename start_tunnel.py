#!/usr/bin/env python3
"""Start ngrok tunnel for Creator AI Toolbox"""
from pyngrok import ngrok, conf
import time, sys, os

# Kill any existing tunnels
try:
    ngrok.kill()
except:
    pass

# Create tunnel
print("Creating ngrok tunnel to port 5000...")
try:
    tunnel = ngrok.connect(5000, "http")
    url = tunnel.public_url
    print(f"\n{'='*50}")
    print(f"✅ Creator AI Toolbox is LIVE!")
    print(f"🔗 {url}")
    print(f"{'='*50}\n")
    
    # Keep alive
    print("Tunnel running. Press Ctrl+C to stop.")
    while True:
        time.sleep(10)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
