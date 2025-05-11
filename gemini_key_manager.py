import requests
from flask import Flask, request, Response
from itertools import cycle
import logging
import logging.handlers
import os
import sys
from datetime import date, datetime, timezone # Import date, datetime, timezone
import json # Import json for usage tracking
import time
import uuid # For generating OpenAI response IDs

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
LOG_DIRECTORY = "." # Log files will be created in the current working directory
LOG_LEVEL = logging.DEBUG # Set to logging.INFO for less verbose logging
# --- End Configuration ---

# --- Global Variables ---
# Will hold the cycle iterator for API keys after loading
key_cycler = None
# List of all loaded API keys
all_api_keys = []
# Dictionary to store API key usage counts for the current day
key_usage_counts = {}
# Dictionary to store API key usage counts per model for the current day
model_usage_counts = {}
# Set to store keys that hit the 429 limit today
# Now a dictionary: {api_key: {model1, model2}}
exhausted_keys_today = {}
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

    # Log directory is now '.', the current working directory.
    # Ensure it exists if it's different from the script's location, though usually it's the same.
    # os.makedirs(LOG_DIRECTORY, exist_ok=True) # Generally not needed for '.'

    # Generate timestamp for log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Construct filename with timestamp directly in the LOG_DIRECTORY (/app)
    log_filename_with_ts = os.path.join(LOG_DIRECTORY, f"proxy_debug_{timestamp}.log")

    # File Handler (Rotates log file)
    # Rotates when the log reaches 1MB, keeps 3 backup logs
    try:
        # Use the full path with timestamp
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename_with_ts, maxBytes=1*1024*1024, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(log_level)
    except Exception as e:
        print(f"Error setting up file logger for {log_filename_with_ts}: {e}", file=sys.stderr)
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
    """Loads usage data (counts, model counts, and exhausted keys) from the specified file for today's date."""
    global key_usage_counts, model_usage_counts, current_usage_date, exhausted_keys_today
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
            model_usage_counts = data.get("model_counts", {}) # Load model counts
            
            # Load exhausted keys - handle new dict format and migrate from old list format
            loaded_exhausted_keys = data.get("exhausted_keys", {})
            if isinstance(loaded_exhausted_keys, list): # Old format (set of keys)
                logging.info("Old format for exhausted_keys detected (list). Resetting to new dictionary format for today.")
                exhausted_keys_today = {} # Reset for new structure
            elif isinstance(loaded_exhausted_keys, dict): # New format (dict of key -> list/set of models)
                exhausted_keys_today = {
                    key: set(models) for key, models in loaded_exhausted_keys.items()
                }
            else: # Unknown format or missing
                logging.warning(f"Unexpected format for 'exhausted_keys' in usage data: {type(loaded_exhausted_keys)}. Resetting.")
                exhausted_keys_today = {}

            logging.info(f"Successfully loaded usage data for {today_str}.")
            logging.info(f"  Total Counts: {key_usage_counts}")
            logging.info(f"  Model Counts: {model_usage_counts}")
            logging.info(f"  Exhausted keys/models today: {exhausted_keys_today}")
        else:
            logging.info(f"Usage data in {filepath} is for a previous date ({data.get('date')}). Starting fresh counts, model counts, and exhausted list for {today_str}.")
            key_usage_counts = {} # Reset counts
            model_usage_counts = {} # Reset model counts
            exhausted_keys_today = {} # Reset exhausted keys (new format)

    except FileNotFoundError:
        logging.info(f"Usage data file not found: {filepath}. Starting with empty counts, model counts, and exhausted list.")
        key_usage_counts = {}
        model_usage_counts = {}
        exhausted_keys_today = {}
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from usage data file: {filepath}. Starting with empty counts, model counts, and exhausted list.")
        key_usage_counts = {}
        model_usage_counts = {}
        exhausted_keys_today = {}
    except Exception as e:
        logging.error(f"An error occurred while loading usage data from {filepath}: {e}", exc_info=True)
        key_usage_counts = {}
        model_usage_counts = {}
        exhausted_keys_today = {}

def save_usage_data(filename=USAGE_DATA_FILE):
    """Saves the current usage data (date, counts, model counts, exhausted keys) to the specified file."""
    global key_usage_counts, model_usage_counts, current_usage_date, exhausted_keys_today
    today_str = current_usage_date.isoformat() # Use the tracked date
    
    # Convert sets in exhausted_keys_today to lists for JSON serialization
    serializable_exhausted_keys = {
        key: list(models) for key, models in exhausted_keys_today.items()
    }
    
    data_to_save = {
        "date": today_str,
        "counts": key_usage_counts,
        "model_counts": model_usage_counts, # Save model counts
        "exhausted_keys": serializable_exhausted_keys # Save new format
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

# --- Helper Functions ---

def is_openai_chat_request(path):
    """Checks if the request path matches the OpenAI chat completions endpoint."""
    return path.strip('/') == "v1/chat/completions"

def convert_openai_to_gemini_request(openai_data):
    """Converts OpenAI request JSON to Gemini request JSON."""
    gemini_request = {"contents": [], "generationConfig": {}, "safetySettings": []}
    target_model = "gemini-pro" # Default model, can be overridden

    # --- Model Mapping (Simple: Use OpenAI model name directly for now) ---
    # A more robust solution might involve explicit mapping or configuration
    if "model" in openai_data:
        # Assuming the model name provided is Gemini-compatible
        # Remove potential prefix like "openai/" if present
        target_model = openai_data["model"].split('/')[-1]
        logging.debug(f"Using model from OpenAI request: {target_model}")
        # We won't put the model in the Gemini request body, it's part of the URL

    # --- Message Conversion ---
    system_prompt = None
    gemini_contents = []
    for message in openai_data.get("messages", []):
        role = message.get("role")
        content = message.get("content")

        if not content: # Skip messages without content
             continue

        # Handle system prompt separately
        if role == "system":
            if isinstance(content, str):
                 system_prompt = {"role": "system", "parts": [{"text": content}]}
            # Note: Gemini API might prefer system prompt at the start or via specific field
            continue # Don't add system prompt directly to contents here

        # Map roles
        gemini_role = "user" if role == "user" else "model" # Treat 'assistant' as 'model'

        # Ensure content is in the correct parts format
        if isinstance(content, str):
            # Simple string content
            gemini_contents.append({"role": gemini_role, "parts": [{"text": content}]})
        elif isinstance(content, list):
            # Handle list of parts (like from multimodal requests or specific clients)
            combined_text = ""
            # TODO: Handle non-text parts if necessary (e.g., images)
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    combined_text += part.get("text", "")
            if combined_text: # Only add if we extracted some text
                 gemini_contents.append({"role": gemini_role, "parts": [{"text": combined_text}]})
            else:
                 logging.warning(f"Message with role '{role}' had list content, but no text parts found: {content}")
        else:
             logging.warning(f"Unsupported content type for role '{role}': {type(content)}")

    # Add system prompt if found (Gemini prefers it at the start or via systemInstruction)
    # Let's try adding it via systemInstruction if present
    if system_prompt:
         gemini_request["systemInstruction"] = system_prompt
         # Alternatively, prepend to contents: gemini_contents.insert(0, system_prompt)

    gemini_request["contents"] = gemini_contents


    # --- Generation Config Mapping ---
    if "temperature" in openai_data:
        gemini_request["generationConfig"]["temperature"] = openai_data["temperature"]
    if "max_tokens" in openai_data:
        gemini_request["generationConfig"]["maxOutputTokens"] = openai_data["max_tokens"]
    if "stop" in openai_data:
        # Gemini expects `stopSequences` which is an array of strings
        stop_sequences = openai_data["stop"]
        if isinstance(stop_sequences, str):
            gemini_request["generationConfig"]["stopSequences"] = [stop_sequences]
        elif isinstance(stop_sequences, list):
            gemini_request["generationConfig"]["stopSequences"] = stop_sequences
    # Add other mappings as needed (topP, topK etc.)
    if "top_p" in openai_data:
         gemini_request["generationConfig"]["topP"] = openai_data["top_p"]
    # if "top_k" in openai_data: gemini_request["generationConfig"]["topK"] = openai_data["top_k"] # Map if needed

    # --- Safety Settings (Optional: Default to BLOCK_NONE for compatibility) ---
    # You might want to make this configurable or map from OpenAI safety params if they existed
    gemini_request["safetySettings"] = [
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    # --- Streaming ---
    # The actual Gemini endpoint URL will determine streaming, not a body parameter
    is_streaming = openai_data.get("stream", False)

    return gemini_request, target_model, is_streaming

# --- Flask Application ---
app = Flask(__name__)

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def proxy(path):
    """
    Handles incoming requests, validates placeholder token, selects an available API key
    (skipping exhausted ones), tracks usage, handles 429 errors by marking keys
    as exhausted for the day, forwards the request (potentially converting formats),
    and returns the response (potentially converting formats).
    """
    global key_cycler, key_usage_counts, model_usage_counts, current_usage_date, exhausted_keys_today, all_api_keys

    request_start_time = time.time()
    original_request_path = path
    is_openai_format = is_openai_chat_request(original_request_path)
    logging.info(f"Request received for path: {original_request_path}. OpenAI format detected: {is_openai_format}")

    # --- Daily Usage Reset Check ---
    today = date.today()
    if today != current_usage_date:
        logging.info(f"Date changed from {current_usage_date} to {today}. Resetting daily usage counts, model counts, and exhausted keys list.")
        current_usage_date = today
        key_usage_counts = {}
        model_usage_counts = {} # Reset model counts as well
        exhausted_keys_today = {} # Reset exhausted keys (new dict format)
        save_usage_data() # Save the reset state

    # Ensure keys were loaded and the cycler is available
    if not all_api_keys or key_cycler is None: # Check all_api_keys as well
        logging.error("API keys not loaded or cycler not initialized. Cannot process request.")
        return Response("Proxy server error: API keys not loaded.", status=503, mimetype='text/plain') # Service Unavailable

    # --- Request Body Handling & Potential Conversion ---
    request_data_bytes = request.get_data()
    gemini_request_body_json = None
    target_gemini_model = None
    use_stream_endpoint = False
    target_path = path # Default to original path

    if is_openai_format:
        if request.method != 'POST':
             return Response("OpenAI compatible endpoint only supports POST.", status=405, mimetype='text/plain')
        try:
            openai_request_data = json.loads(request_data_bytes)
            logging.debug(f"Original OpenAI request data: {openai_request_data}")
            gemini_request_body_json, target_gemini_model, use_stream_endpoint = convert_openai_to_gemini_request(openai_request_data)
            logging.debug(f"Converted Gemini request data: {gemini_request_body_json}")
            logging.info(f"OpenAI request mapped to Gemini model: {target_gemini_model}, Streaming: {use_stream_endpoint}")

            # Determine target Gemini endpoint
            action = "streamGenerateContent" if use_stream_endpoint else "generateContent"
            # Construct the Gemini API path using the extracted/defaulted model
            target_path = f"v1beta/models/{target_gemini_model}:{action}"

        except json.JSONDecodeError:
            logging.error("Failed to decode OpenAI request body as JSON.")
            return Response("Invalid JSON in request body.", status=400, mimetype='text/plain')
        except Exception as e:
            logging.error(f"Error during OpenAI request conversion: {e}", exc_info=True)
            return Response("Error processing OpenAI request.", status=500, mimetype='text/plain')
    else:
        # Assume it's a direct Gemini request, pass body through (if method allows)
        if request_data_bytes and request.method in ['POST', 'PUT', 'PATCH']:
             # We don't strictly need to parse it here, but might be useful for logging
             try:
                  gemini_request_body_json = json.loads(request_data_bytes)
                  logging.debug(f"Direct Gemini request data: {gemini_request_body_json}")
             except json.JSONDecodeError:
                  logging.warning("Could not parse direct Gemini request body as JSON for logging.")
                  # Send bytes directly if not JSON? Or assume JSON? Let's assume JSON for now.
                  # If non-JSON needed, this needs adjustment.
        target_path = path # Use original path for direct Gemini requests


    # Construct the target URL for the actual Google API
    target_url = f"{GEMINI_API_BASE_URL}/{target_path}"
    logging.debug(f"Target Gemini URL: {target_url}")

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
    auth_header_openai = 'authorization' # Define variable *before* use

    # If the original request was OpenAI format, remove the Authorization header
    # as we will use x-goog-api-key for the upstream request.
    if is_openai_format and auth_header_openai in outgoing_headers:
        del outgoing_headers[auth_header_openai]
        logging.debug(f"Removed '{auth_header_openai}' header before forwarding.")

    api_key_header_gemini = 'x-goog-api-key'
    # auth_header_openai = 'authorization' # Definition moved up
    next_key = None

    # --- API Key Validation (Handles both OpenAI and Gemini style auth to the proxy) ---
    placeholder_token_provided = None
    if is_openai_format:
        # Expect OpenAI style "Authorization: Bearer PLACEHOLDER_TOKEN"
        auth_value = incoming_headers.get(auth_header_openai)
        if not auth_value:
            logging.warning(f"OpenAI Request rejected: Missing '{auth_header_openai}' header.")
            return Response(f"Missing '{auth_header_openai}' header", status=401, mimetype='text/plain')
        parts = auth_value.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            logging.warning(f"OpenAI Request rejected: Invalid '{auth_header_openai}' header format. Expected 'Bearer <token>'.")
            return Response(f"Invalid '{auth_header_openai}' header format.", status=401, mimetype='text/plain')
        placeholder_token_provided = parts[1]
    else:
        # Expect Gemini style "x-goog-api-key: PLACEHOLDER_TOKEN"
        if api_key_header_gemini not in incoming_headers:
            logging.warning(f"Gemini Request rejected: Missing '{api_key_header_gemini}' header.")
            return Response(f"Missing '{api_key_header_gemini}' header", status=400, mimetype='text/plain') # Bad Request might be more appropriate
        placeholder_token_provided = incoming_headers[api_key_header_gemini]

    # Validate the provided token against the configured placeholder
    if placeholder_token_provided != PLACEHOLDER_TOKEN:
        logging.warning(f"Request rejected: Invalid placeholder token provided. Received: '{placeholder_token_provided}', Expected: '{PLACEHOLDER_TOKEN}'")
        return Response(f"Invalid API key/token provided.", status=401, mimetype='text/plain') # Unauthorized

    logging.debug("Placeholder token validated successfully.")

    # --- Determine Effective Model for Exhaustion Logic ---
    effective_model_for_request = None
    if is_openai_format:
        effective_model_for_request = target_gemini_model # Determined during OpenAI to Gemini conversion
    else: # Direct Gemini request
        try:
            # target_path is like "v1beta/models/gemini-pro:generateContent" or "v1/models/gemini-1.5-flash"
            path_segments = target_path.split('/')
            if 'models' in path_segments:
                models_idx = path_segments.index('models')
                if models_idx + 1 < len(path_segments):
                    effective_model_for_request = path_segments[models_idx + 1].split(':')[0]
            
            if not effective_model_for_request: # Fallback for slightly different structures if needed
                 logging.warning(f"Could not determine model from direct Gemini path structure: {target_path}")

        except ValueError: # 'models' not in path_segments
            logging.warning(f"Path structure for direct Gemini request does not contain 'models' segment: {target_path}")
        except Exception as e:
            logging.error(f"Error parsing model from direct Gemini path {target_path}: {e}", exc_info=True)

    if not effective_model_for_request:
        logging.error(f"Critical: Model for request could not be determined for path '{original_request_path}' (target: '{target_path}'). Cannot apply model-specific exhaustion logic.")
        return Response("Proxy error: Could not determine model for request to apply exhaustion rules.", status=500, mimetype='text/plain')
    
    logging.info(f"Effective model for this request (for exhaustion logic): {effective_model_for_request}")

    # --- Key Selection and Request Loop (Selects actual Gemini key for upstream) ---
    max_retries = len(all_api_keys) # Max attempts = number of keys
    keys_tried_this_request = 0

    # Check if all keys are already exhausted for this specific model before starting the loop
    if not all_api_keys: # Should be caught by earlier check, but defensive
        logging.error("API keys not loaded. Cannot process request.")
        return Response("Proxy server error: API keys not loaded.", status=503)

    all_keys_exhausted_for_model = True
    for key_in_list in all_api_keys:
        if effective_model_for_request not in exhausted_keys_today.get(key_in_list, set()):
            all_keys_exhausted_for_model = False
            break
    if all_keys_exhausted_for_model:
        logging.warning(f"All API keys are marked as exhausted for model '{effective_model_for_request}' today. Rejecting request.")
        return Response(f"All available API keys have reached their daily limit for model '{effective_model_for_request}'.", status=503, mimetype='text/plain')

    while keys_tried_this_request < max_retries:
        try:
            next_key = next(key_cycler)
            keys_tried_this_request += 1

            # Skip if key is already known to be exhausted for this specific model today
            if effective_model_for_request in exhausted_keys_today.get(next_key, set()):
                logging.debug(f"Skipping key ending ...{next_key[-4:]} for model '{effective_model_for_request}' as it's marked exhausted today.")
                continue # Try the next key in the cycle

            logging.info(f"Attempting request for model '{effective_model_for_request}' with key ending ...{next_key[-4:]}")
            outgoing_headers[api_key_header_gemini] = next_key # Set the actual Gemini key for the upstream request

            # --- Request Forwarding ---
            # Use the potentially converted JSON body
            request_body_to_send = json.dumps(gemini_request_body_json).encode('utf-8') if gemini_request_body_json else b''

            logging.debug(f"Forwarding request body size: {len(request_body_to_send)} bytes")
            if LOG_LEVEL == logging.DEBUG and request_body_to_send:
                 try:
                      logging.debug(f"Forwarding request body: {request_body_to_send.decode('utf-8', errors='ignore')}")
                 except Exception:
                      logging.debug("Could not decode forwarding request body for logging.")

            # Determine method - OpenAI endpoint is always POST
            forward_method = 'POST' if is_openai_format else request.method
            logging.info(f"Forwarding {forward_method} request to: {target_url} with key ...{next_key[-4:]}")
            logging.debug(f"Forwarding with Query Params: {query_params}")
            logging.debug(f"Forwarding with Headers: {outgoing_headers}")

            # Make the request to the actual Google Gemini API
            # Pass query params only if it wasn't an OpenAI request (OpenAI params are in body)
            forward_params = query_params if not is_openai_format else None
            # Determine if the *forwarded* request should be streaming based on Gemini endpoint
            forward_stream = target_path.endswith("streamGenerateContent")

            resp = requests.request(
                method=forward_method,
                url=target_url,
                headers=outgoing_headers,
                params=forward_params,
                data=request_body_to_send,
                stream=forward_stream, # Use stream based on Gemini target path
                timeout=120
            )

            logging.info(f"Received response Status: {resp.status_code} from {target_url} using key ...{next_key[-4:]}")

            # --- Handle 429 Rate Limit Error ---
            if resp.status_code == 429:
                logging.warning(f"Key ending ...{next_key[-4:]} hit rate limit (429) for model '{effective_model_for_request}'. Marking this model as exhausted for this key today.")
                exhausted_keys_today.setdefault(next_key, set()).add(effective_model_for_request)
                save_usage_data() # Save the updated exhausted list

                # Check if all keys are now exhausted for this specific model after this failure
                all_now_exhausted_for_model = True
                for key_in_all_keys in all_api_keys:
                    if effective_model_for_request not in exhausted_keys_today.get(key_in_all_keys, set()):
                        all_now_exhausted_for_model = False
                        break
                if all_now_exhausted_for_model:
                    logging.warning(f"All API keys are now exhausted for model '{effective_model_for_request}' after 429 error. Last key tried: ...{next_key[-4:]}")
                    return Response(f"All available API keys have reached their daily limit for model '{effective_model_for_request}'.", status=503, mimetype='text/plain')
                
                continue # Continue the loop to try the next available key

            # --- Success or Other Error ---
            # Increment usage count ONLY if the request didn't result in 429
            current_total_count = key_usage_counts.get(next_key, 0) + 1
            key_usage_counts[next_key] = current_total_count

            # Determine the model used for this request (for usage logging, distinct from effective_model_for_request used for exhaustion)
            # `effective_model_for_request` is already determined and should be the same as `actual_model_used` here.
            actual_model_used = effective_model_for_request 
            # The old logic for actual_model_used is fine, but effective_model_for_request is already available and more robustly determined earlier.

            # Update model-specific usage count
            if next_key not in model_usage_counts:
                model_usage_counts[next_key] = {}
            current_model_count = model_usage_counts[next_key].get(actual_model_used, 0) + 1
            model_usage_counts[next_key][actual_model_used] = current_model_count

            logging.info(f"Key ending ...{next_key[-4:]} used for model '{actual_model_used}'. Today's model usage: {current_model_count}. Total usage for key: {current_total_count}")
            save_usage_data() # Save updated counts, model counts, and potentially exhausted list

            # --- Response Handling ---
            logging.debug(f"Response Headers from Google: {dict(resp.headers)}")
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            response_headers = [
                (key, value) for key, value in resp.raw.headers.items()
                if key.lower() not in excluded_headers
            ]
            logging.debug(f"Forwarding response headers to client: {response_headers}")

            # --- Response Handling & Potential Conversion ---

            final_headers_to_client = response_headers
            final_status_code = resp.status_code

            # --- Handle Non-Streaming and Direct Gemini Requests / Read Content ---
            # Read the raw content for all non-streaming cases or direct Gemini requests
            raw_response_content = resp.content
            final_content_to_client = raw_response_content # Default

            # --- Filter out trailing Google API error JSON (if applicable and status was 200) ---
            if final_status_code == 200 and raw_response_content:
                try:
                    # Decode the whole content
                    decoded_content = raw_response_content.decode('utf-8', errors='replace').strip()

                    # Check if it potentially ends with a JSON object
                    if decoded_content.endswith('}'):
                        # Find the start of the last potential JSON object (look for the last '{' preceded by a newline)
                        # This is heuristic, assuming the error JSON is the last significant block.
                        last_block_start = decoded_content.rfind('\n{') # Find last occurrence
                        if last_block_start == -1:
                             last_block_start = decoded_content.rfind('\n\n{') # Try double newline just in case

                        if last_block_start != -1:
                            potential_error_json_str = decoded_content[last_block_start:].strip()
                            try:
                                error_json = json.loads(potential_error_json_str)
                                # Check if it matches the Google error structure
                                if isinstance(error_json, dict) and 'error' in error_json and isinstance(error_json['error'], dict) and 'code' in error_json['error'] and 'status' in error_json['error']:
                                    logging.warning(f"Detected and filtering out trailing Google API error JSON: {potential_error_json_str}")
                                    # Truncate the content *before* the start of this detected error block
                                    valid_content = decoded_content[:last_block_start].strip()
                                    # Add back trailing newline(s) for SSE format consistency
                                    if valid_content:
                                         valid_content += '\n\n' # Add double newline typical for SSE

                                    raw_response_content = valid_content.encode('utf-8') # Update raw_response_content
                                else:
                                    logging.debug("Potential JSON at end doesn't match Google error structure.")
                            except json.JSONDecodeError:
                                logging.debug("String at end ending with '}' is not valid JSON.")
                        else:
                             logging.debug("Could not find a potential start ('\\n{') for a JSON block at the end.")
                    else:
                        logging.debug("Content does not end with '}'.")

                except Exception as filter_err:
                    logging.error(f"Error occurred during revised response filtering: {filter_err}", exc_info=True)
                    # Keep raw_response_content as is if filtering fails
            # --- End Filtering ---

            # --- Convert OpenAI response format (Streaming or Non-Streaming) ---
            if is_openai_format and final_status_code == 200:
                 try:
                      logging.debug("Attempting to convert Gemini response to OpenAI format (Streaming or Non-Streaming).")
                      # Use the potentially filtered raw_response_content here
                      decoded_gemini_content = raw_response_content.decode('utf-8', errors='replace')

                      # --- Streaming Conversion (from JSON Array) ---
                      if use_stream_endpoint:
                           def stream_converter_from_array():
                                chunk_id_counter = 0
                                created_timestamp = int(time.time())
                                try:
                                     gemini_response_array = json.loads(decoded_gemini_content)
                                     if not isinstance(gemini_response_array, list):
                                          logging.error("Gemini stream response was not a JSON array as expected.")
                                          # Optionally yield an error chunk?
                                          yield "data: [DONE]\n\n".encode('utf-8') # Send DONE anyway?
                                          return

                                     for gemini_chunk in gemini_response_array:
                                          # Extract text content from Gemini chunk
                                          text_content = ""
                                          # Check for potential errors within the stream itself
                                          if gemini_chunk.get("candidates") is None and gemini_chunk.get("error"):
                                               logging.error(f"Error object found within Gemini response array: {gemini_chunk['error']}")
                                               # Stop processing this stream
                                               break

                                          if gemini_chunk.get("candidates"):
                                               content = gemini_chunk["candidates"][0].get("content", {})
                                               if content.get("parts"):
                                                    text_content = content["parts"][0].get("text", "")

                                          if text_content: # Only yield if there's content
                                               # Construct OpenAI SSE chunk
                                               openai_chunk = {
                                                    "id": f"chatcmpl-{uuid.uuid4()}",
                                                    "object": "chat.completion.chunk",
                                                    "created": created_timestamp,
                                                    "model": target_gemini_model,
                                                    "choices": [{
                                                         "index": 0,
                                                         "delta": { "content": text_content },
                                                         "finish_reason": None
                                                    }]
                                               }
                                               sse_data = f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"
                                               yield sse_data.encode('utf-8')
                                               chunk_id_counter += 1

                                except json.JSONDecodeError:
                                     logging.error(f"Failed to decode Gemini response array: {decoded_gemini_content}")
                                     # Optionally yield an error chunk?
                                except Exception as e:
                                     logging.error(f"Error processing Gemini response array: {e}", exc_info=True)

                                # Send the final [DONE] signal
                                yield "data: [DONE]\n\n".encode('utf-8')
                                logging.info(f"Finished streaming conversion from array, sent {chunk_id_counter} content chunks.")

                           # Set the response to use the generator and correct headers
                           final_headers_to_client = [('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-cache')] + [h for h in response_headers if h[0].lower() not in ['content-type', 'content-length', 'transfer-encoding']]
                           # Return the generator directly
                           return Response(stream_converter_from_array(), status=final_status_code, headers=final_headers_to_client)

                      # --- Non-Streaming Conversion ---
                      else:
                           gemini_full_response = json.loads(decoded_gemini_content)
                      # Extract text content (simplified)
                      full_text = ""
                      openai_finish_reason = "stop" # Default

                      if gemini_full_response.get("candidates"):
                           candidate = gemini_full_response["candidates"][0]
                           full_text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                           # Map finish reason
                           gemini_finish_reason = candidate.get("finishReason", "STOP")
                           if gemini_finish_reason == "MAX_TOKENS":
                                openai_finish_reason = "length"
                           elif gemini_finish_reason == "SAFETY":
                                openai_finish_reason = "content_filter"
                           # Add other mappings if needed (RECITATION, OTHER)

                      # Corrected structure for openai_response
                      openai_response = {
                          "id": f"chatcmpl-{uuid.uuid4()}",
                          "object": "chat.completion",
                          "created": int(time.time()),
                          "model": target_gemini_model,
                          "choices": [{
                              "index": 0,
                              "message": {
                                  "role": "assistant",
                                  "content": full_text,
                              },
                              "finish_reason": openai_finish_reason # Use mapped reason
                          }],
                          "usage": { # Map from Gemini usageMetadata
                              "prompt_tokens": gemini_full_response.get("usageMetadata", {}).get("promptTokenCount", 0),
                              "completion_tokens": gemini_full_response.get("usageMetadata", {}).get("candidatesTokenCount", 0),
                              "total_tokens": gemini_full_response.get("usageMetadata", {}).get("totalTokenCount", 0)
                          }
                      }
                      final_content_to_client = json.dumps(openai_response, ensure_ascii=False).encode('utf-8') # Use correct variable
                      # Update headers for JSON
                      final_headers_to_client = [('Content-Type', 'application/json')] + [h for h in response_headers if h[0].lower() not in ['content-type', 'content-length', 'transfer-encoding']]

                      logging.info("Successfully converted non-streaming Gemini response to OpenAI format.")

                 except Exception as convert_err:
                      logging.error(f"Error converting Gemini response to OpenAI format: {convert_err}", exc_info=True)
                      # Fallback: Return original Gemini content but maybe signal error?
                      # For now, just return the filtered Gemini content with original headers/status
                      final_content_to_client = raw_response_content # Use the (potentially filtered) raw content
                      final_headers_to_client = response_headers
                      # Consider changing status code? Maybe 500?
                      # final_status_code = 500 # Indicate conversion failure

            else:
                 # Use the potentially filtered content directly for non-OpenAI requests or errors
                 final_content_to_client = raw_response_content


            # --- Create final response (only if not streaming OpenAI, which returns earlier) ---
            response = Response(final_content_to_client, final_status_code, final_headers_to_client)

            # Logging the final response size might be misleading for streams handled by the generator
            if not (is_openai_format and use_stream_endpoint):
                 logging.debug(f"Final response body size sent to client: {len(final_content_to_client)} bytes")
            # Log the full final response body if debug level is enabled
            if LOG_LEVEL == logging.DEBUG and final_content_to_client:
                try:
                    # Attempt to decode for readability, log raw bytes on failure
                    # Use final_content_to_client here
                    decoded_body = final_content_to_client.decode('utf-8', errors='replace')
                    logging.debug(f"Full Response body sent to client (decoded): {decoded_body}")
                except Exception as log_err:
                    # Log the correct variable in the error message too
                    logging.debug(f"Could not decode final response body for logging, logging raw bytes: {final_content_to_client!r}. Error: {log_err}")
            elif final_content_to_client: # Log first 500 chars if not in DEBUG mode but content exists
                 try:
                      logging.info(f"Response body sent to client (first 500 chars): {final_content_to_client[:500].decode('utf-8', errors='ignore')}")
                 except Exception:
                      logging.info("Could not decode start of final response body for logging.")


            return response # Return the potentially filtered response

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
