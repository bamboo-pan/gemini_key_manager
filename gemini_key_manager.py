import requests
from flask import Flask, request, Response
from itertools import cycle
import logging
import logging.handlers
import os
import sys
from datetime import date, datetime # Import date and datetime
import json # Import json for usage tracking

# --- Configuration ---
# Placeholder token that clients will use in the 'x-goog-api-key' header
PLACEHOLDER_TOKEN = "PLACEHOLDER_GEMINI_TOKEN"
# File containing the real Google Gemini API keys, one per line
API_KEY_FILE = "key.txt"
# Base URL for the actual Google Gemini API
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"
# Host and port for the proxy server to listen on
# '0.0.0.0' makes it accessible from other machines on the network
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5000
# Log file configuration
LOG_FILENAME = "proxy_debug.log"
LOG_LEVEL = logging.DEBUG # Set to logging.INFO for less verbose logging
# --- End Configuration ---

# --- Global Variables ---
# Will hold the cycle iterator for API keys after loading
key_cycler = None
# List of all loaded API keys
all_api_keys = []
# Dictionary to store API key usage counts for the current day
key_usage_counts = {}
# Set to store keys that hit the 429 limit today
exhausted_keys_today = set()
# Track the date for which the counts and exhausted list are valid
current_usage_date = date.today()
# File to store usage data
USAGE_DATA_FILE = "key_usage.txt"
# --- End Global Variables ---

# --- Logging Setup ---
def setup_logging():
    """Configures logging to both console and a rotating file."""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
    log_level = LOG_LEVEL

    # Generate timestamp for log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Construct filename with timestamp (e.g., proxy_debug_20250406_155700.log)
    log_filename_with_ts = f"proxy_debug_{timestamp}.log"

    # File Handler (Rotates log file)
    # Rotates when the log reaches 1MB, keeps 3 backup logs
    try:
        # Use the filename with timestamp
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename_with_ts, maxBytes=1*1024*1024, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(log_level)
    except Exception as e:
        print(f"Error setting up file logger for {LOG_FILENAME}: {e}", file=sys.stderr)
        file_handler = None

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    # Console handler might have a different level (e.g., INFO) if desired
    console_handler.setLevel(logging.INFO) 

    # Get the root logger and add handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level) # Set root logger level to the lowest level needed
    if file_handler:
        root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Update log message to show the generated filename
    logging.info("Logging configured. Level: %s, File: %s", logging.getLevelName(log_level), log_filename_with_ts if file_handler else "N/A")

# --- Usage Data Handling ---
def load_usage_data(filename=USAGE_DATA_FILE):
    """Loads usage data (counts and exhausted keys) from the specified file for today's date."""
    global key_usage_counts, current_usage_date, exhausted_keys_today
    today_str = date.today().isoformat()
    current_usage_date = date.today() # Ensure current_usage_date is set
    
    script_dir = os.path.dirname(__file__) if '__file__' in globals() else '.'
    filepath = os.path.join(script_dir, filename)
    logging.info(f"Attempting to load usage data for {today_str} from: {filepath}")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if data.get("date") == today_str:
            key_usage_counts = data.get("counts", {})
            # Load exhausted keys as a set
            exhausted_keys_today = set(data.get("exhausted_keys", [])) 
            logging.info(f"Successfully loaded usage data for {today_str}.")
            logging.info(f"  Counts: {key_usage_counts}")
            logging.info(f"  Exhausted keys today: {exhausted_keys_today}")
        else:
            logging.info(f"Usage data in {filepath} is for a previous date ({data.get('date')}). Starting fresh counts and exhausted list for {today_str}.")
            key_usage_counts = {} # Reset counts
            exhausted_keys_today = set() # Reset exhausted keys
            
    except FileNotFoundError:
        logging.info(f"Usage data file not found: {filepath}. Starting with empty counts and exhausted list.")
        key_usage_counts = {}
        exhausted_keys_today = set()
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from usage data file: {filepath}. Starting with empty counts and exhausted list.")
        key_usage_counts = {}
        exhausted_keys_today = set()
    except Exception as e:
        logging.error(f"An error occurred while loading usage data from {filepath}: {e}", exc_info=True)
        key_usage_counts = {}
        exhausted_keys_today = set()

def save_usage_data(filename=USAGE_DATA_FILE):
    """Saves the current usage data (date, counts, exhausted keys) to the specified file."""
    global key_usage_counts, current_usage_date, exhausted_keys_today
    today_str = current_usage_date.isoformat() # Use the tracked date
    data_to_save = {
        "date": today_str,
        "counts": key_usage_counts,
        "exhausted_keys": list(exhausted_keys_today) # Convert set to list for JSON
    }
    
    script_dir = os.path.dirname(__file__) if '__file__' in globals() else '.'
    filepath = os.path.join(script_dir, filename)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4)
        logging.debug(f"Successfully saved usage data for {today_str} to {filepath}. Counts: {key_usage_counts}")
    except Exception as e:
        logging.error(f"An error occurred while saving usage data to {filepath}: {e}", exc_info=True)

# --- API Key Loading ---
def load_api_keys(filename):
    """
    Loads API keys from a specified file (one key per line), stores them globally.
    Handles potential errors like file not found or empty file.
    Returns the list of keys or None if loading fails.
    """
    global all_api_keys # Ensure we modify the global list
    keys = []
    # Construct the full path relative to the script's directory or CWD
    script_dir = os.path.dirname(__file__) if '__file__' in globals() else '.'
    filepath = os.path.join(script_dir, filename)
    
    logging.info(f"Attempting to load API keys from: {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # Read non-empty lines and strip whitespace
            keys = [line.strip() for line in f if line.strip()] 
        
        if not keys:
            logging.error(f"No API keys found in {filepath}. File might be empty or contain only whitespace.")
            return None
        else:
            logging.info(f"Successfully loaded {len(keys)} API keys.")
            # Log loaded keys partially masked for security (DEBUG level)
            for i, key in enumerate(keys):
                 logging.debug(f"  Key {i+1}: ...{key[-4:]}")
            all_api_keys = keys # Store the loaded keys globally
            return keys
            
    except FileNotFoundError:
        logging.error(f"API key file not found: {filepath}")
        return None
    except Exception as e:
        # Log the full exception details for debugging
        logging.error(f"An error occurred while loading API keys from {filepath}: {e}", exc_info=True)
        return None

# --- Flask Application ---
app = Flask(__name__)

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def proxy(path):
    """
    Handles incoming requests, validates placeholder token, selects an available API key 
    (skipping exhausted ones), tracks usage, handles 429 errors by marking keys 
    as exhausted for the day, forwards the request, and returns the response.
    """
    global key_cycler, key_usage_counts, current_usage_date, exhausted_keys_today, all_api_keys
    
    # --- Daily Usage Reset Check ---
    today = date.today()
    if today != current_usage_date:
        logging.info(f"Date changed from {current_usage_date} to {today}. Resetting daily usage counts and exhausted keys list.")
        current_usage_date = today
        key_usage_counts = {}
        exhausted_keys_today = set() # Reset exhausted keys as well
        save_usage_data() # Save the reset state

    # Ensure keys were loaded and the cycler is available
    if not all_api_keys or key_cycler is None: # Check all_api_keys as well
        logging.error("API keys not loaded or cycler not initialized. Cannot process request.")
        return Response("Proxy server error: API keys not loaded.", status=503, mimetype='text/plain') # Service Unavailable

    # Construct the target URL for the actual Google API
    target_url = f"{GEMINI_API_BASE_URL}/{path}"
    logging.debug(f"Incoming request for path: {path}")
    logging.debug(f"Target URL: {target_url}")

    # Get query parameters (passed through but not used for key auth)
    query_params = request.args.to_dict()
    logging.debug(f"Incoming query parameters: {query_params}")

    # Prepare headers for the outgoing request
    # Copy headers from incoming request, excluding 'Host'
    # Use lowercase keys for case-insensitive lookup
    incoming_headers = {key.lower(): value for key, value in request.headers.items() if key.lower() != 'host'}
    logging.debug(f"Incoming headers (excluding Host): {incoming_headers}")
    
    # Start with a copy of incoming headers for the outgoing request
    outgoing_headers = incoming_headers.copy() 

    api_key_header = 'x-goog-api-key' # Standard header for Google API keys
    next_key = None

    # --- API Key Validation and Rotation ---
    if api_key_header not in incoming_headers:
        logging.warning(f"Request rejected: Missing '{api_key_header}' header.")
        return Response(f"Missing '{api_key_header}' header", status=400, mimetype='text/plain')
    
    if incoming_headers[api_key_header] != PLACEHOLDER_TOKEN:
        logging.warning(f"Request rejected: Invalid API key provided in header. Expected placeholder.")
        # Optionally log the received key if needed for debugging, but be careful with sensitive data
        # logging.debug(f"Received non-placeholder key: {incoming_headers[api_key_header]}")
        return Response(f"Invalid API key provided in header. Use the placeholder token '{PLACEHOLDER_TOKEN}'.", status=401, mimetype='text/plain') # Unauthorized

    # --- Key Selection and Request Loop ---
    max_retries = len(all_api_keys) # Max attempts = number of keys
    keys_tried_this_request = 0
    
    # Check if all keys are already exhausted before starting the loop
    if len(exhausted_keys_today) >= len(all_api_keys):
            logging.warning("All API keys are marked as exhausted for today. Rejecting request.")
            return Response("All available API keys have reached their daily limit.", status=503, mimetype='text/plain') # Service Unavailable

    while keys_tried_this_request < max_retries:
        try:
            next_key = next(key_cycler)
            keys_tried_this_request += 1

            # Skip if key is already known to be exhausted today
            if next_key in exhausted_keys_today:
                logging.debug(f"Skipping exhausted key ending ...{next_key[-4:]}")
                continue # Try the next key in the cycle

            logging.info(f"Attempting request with key ending ...{next_key[-4:]}")
            outgoing_headers[api_key_header] = next_key # Set the key for this attempt

            # --- Request Forwarding ---
            data = request.get_data() # Get data inside loop in case of retry? No, data is static for the request. Get it once before loop.
            # Get the request body data (moved outside loop)
            # data = request.get_data() 
            logging.debug(f"Request body size: {len(data)} bytes")
            if LOG_LEVEL == logging.DEBUG and data:
                 try:
                      logging.debug(f"Request body: {data.decode('utf-8', errors='ignore')}")
                 except Exception:
                      logging.debug("Could not decode request body for logging.")

            logging.info(f"Forwarding {request.method} request to: {target_url} with key ...{next_key[-4:]}")
            logging.debug(f"Forwarding with Query Params: {query_params}")
            logging.debug(f"Forwarding with Headers: {outgoing_headers}")

            # Make the request to the actual Google Gemini API
            resp = requests.request(
                method=request.method,
                url=target_url,
                headers=outgoing_headers,
                params=query_params,
                data=data,
                stream=True,
                timeout=120
            )

            logging.info(f"Received response Status: {resp.status_code} from {target_url} using key ...{next_key[-4:]}")

            # --- Handle 429 Rate Limit Error ---
            if resp.status_code == 429:
                logging.warning(f"Key ending ...{next_key[-4:]} hit rate limit (429). Marking as exhausted for today.")
                exhausted_keys_today.add(next_key)
                save_usage_data() # Save the updated exhausted list

                # Check if all keys are now exhausted after this failure
                if len(exhausted_keys_today) >= len(all_api_keys):
                    logging.warning("All API keys are now exhausted after 429 error. Rejecting request.")
                    # Return the 429 response from the last failed key? Or a generic 503? Let's return 503.
                    return Response("All available API keys have reached their daily limit.", status=503, mimetype='text/plain')
                
                continue # Continue the loop to try the next available key

            # --- Success or Other Error ---
            # Increment usage count ONLY if the request didn't result in 429
            current_count = key_usage_counts.get(next_key, 0) + 1
            key_usage_counts[next_key] = current_count
            logging.info(f"Key ending ...{next_key[-4:]} used successfully. Today's usage count: {current_count}")
            save_usage_data() # Save updated counts and potentially exhausted list (if changed by another thread/process, though unlikely here)

            # --- Response Handling ---
            logging.debug(f"Response Headers from Google: {dict(resp.headers)}")
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            response_headers = [
                (key, value) for key, value in resp.raw.headers.items()
                if key.lower() not in excluded_headers
            ]
            logging.debug(f"Forwarding response headers to client: {response_headers}")

            response_content = resp.content 
            response = Response(response_content, resp.status_code, response_headers)
            
            logging.debug(f"Response body size: {len(response_content)} bytes")
            if LOG_LEVEL == logging.DEBUG and response_content:
                try:
                    logging.debug(f"Response body (first 500 chars): {response_content[:500].decode('utf-8', errors='ignore')}")
                except Exception:
                    logging.debug("Could not decode response body for logging.")
                    
            return response # Success or non-429 error, return response

        except requests.exceptions.Timeout:
            logging.error(f"Timeout error when forwarding request to {target_url} with key ...{next_key[-4:]}")
            # Don't mark key as exhausted for timeout, but stop trying for this request.
            return Response("Proxy error: Upstream request timed out.", status=504, mimetype='text/plain')
        except requests.exceptions.RequestException as e:
            logging.error(f"Error forwarding request to {target_url} with key ...{next_key[-4:]}: {e}", exc_info=True)
            # Don't mark key as exhausted, stop trying for this request.
            return Response(f"Proxy error: Could not connect to upstream server. {e}", status=502, mimetype='text/plain')
        except StopIteration:
             # This should theoretically not be reached due to the keys_tried_this_request check, but handle defensively.
             logging.error("Key cycler unexpectedly exhausted during request processing.")
             return Response("Proxy server error: Key rotation failed.", status=500, mimetype='text/plain')
        except Exception as e:
            logging.error(f"An unexpected error occurred in the proxy function with key ...{next_key[-4:]}: {e}", exc_info=True)
            # Stop trying for this request.
            return Response("Proxy server internal error.", status=500, mimetype='text/plain')

    # If the loop finishes without returning (meaning all keys were tried and failed or were exhausted)
    logging.error("Failed to forward request after trying all available API keys.")
    return Response("Proxy error: Failed to find a usable API key.", status=503, mimetype='text/plain') # Service Unavailable
        
    # --- Request Forwarding --- (This section is now inside the loop)
    # Get the request body data once before the loop
    data = request.get_data()


# --- Main Execution ---
if __name__ == '__main__':
    setup_logging() # Configure logging first

    # Load API keys from the specified file
    api_keys = load_api_keys(API_KEY_FILE)

    if api_keys:
        # Initialize the key cycler if keys were loaded successfully
        key_cycler = cycle(api_keys)
        
        # Load usage data after keys are loaded but before starting server
        load_usage_data() 
        
        logging.info(f"Starting Gemini proxy server on http://{LISTEN_HOST}:{LISTEN_PORT}")
        logging.info(f"Proxy configured to use placeholder token: {PLACEHOLDER_TOKEN}")
        logging.info(f"Requests will be forwarded to: {GEMINI_API_BASE_URL}")
        logging.info(f"Ready to process requests...")
        # Run the Flask development server
        # For production, consider using a proper WSGI server like Gunicorn or Waitress
        app.run(host=LISTEN_HOST, port=LISTEN_PORT)
    else:
        logging.critical("Proxy server failed to start: Could not load API keys.")
        sys.exit(1) # Exit if keys could not be loaded
