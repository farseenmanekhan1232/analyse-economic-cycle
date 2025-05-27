from flask import Flask, redirect, request, jsonify
from kiteconnect import KiteConnect
import logging
import os

app = Flask(__name__)



API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")

REDIRECT_URL = "http://127.0.0.1:5000/callback"

kite = KiteConnect(api_key=API_KEY)
access_token = None

# Set up logging
logging.basicConfig(level=logging.INFO)

@app.route('/')
def home():
    return "Welcome! Visit /login to authenticate with Kite Connect."

@app.route('/login')
def login():
    login_url = kite.login_url()
    return redirect(login_url)

@app.route('/callback')
def callback():
    global access_token
    request_token = request.args.get('request_token')
    try:
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]
        logging.info("Access token generated successfully.")
        return "Access token generated successfully! You can now run your script."
    except Exception as e:
        logging.error(f"Error generating access token: {e}")
        return f"Error generating access token: {e}"

@app.route('/get_token')
def get_token():
    if access_token:
        return jsonify({"access_token": access_token})
    else:
        return jsonify({"error": "No access token available. Please visit /login first."}), 401

if __name__ == '__main__':
    app.run(port=5000)