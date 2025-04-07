# Gemini Key Manager

[简体中文](README_zh.md) | English

A simple Python Flask proxy server designed to manage multiple Google Gemini API keys effectively. It allows clients to interact with the Gemini API using a single placeholder token, while the proxy handles key rotation, daily usage tracking, and rate limit management behind the scenes.

This is particularly useful when you have multiple API keys and want to distribute the load, track usage per key, and automatically handle keys that hit their daily rate limits (429 errors).

## Core Features

*   **API Key Rotation:** Cycles through a list of provided Gemini API keys (`key.txt`) for each incoming request.
*   **Placeholder Token:** Clients use a predefined placeholder token (`PLACEHOLDER_GEMINI_TOKEN`) for authentication against the proxy, keeping the real keys secure on the server.
*   **Daily Usage Tracking:** Monitors and logs the number of times each API key is used per day.
*   **Persistent Usage Data:** Saves daily usage counts and the list of exhausted keys to a local file (`key_usage.txt`) in JSON format, allowing state to be preserved across server restarts.
*   **Automatic Rate Limit (429) Handling:** Detects when a key receives a 429 "Resource Exhausted" error from the Gemini API.
    *   Marks the exhausted key as unusable for the rest of the current day.
    *   Automatically retries the request with the next available key in the pool.
    *   Returns a 503 "Service Unavailable" error if all keys become exhausted for the day.
*   **Daily Reset:** Automatically resets usage counts and the list of exhausted keys at the beginning of each new day.
*   **OpenAI API Compatibility:** Acts as an adapter for the `/v1/chat/completions` endpoint. Accepts requests in OpenAI format (including streaming) and translates them to/from the Gemini API format. Tested with CherryStudio and Cline.
*   **Configurable Logging:** Provides detailed logging to both console and rotating log files for debugging and monitoring.

## Prerequisites

*   **Python:** Version 3.7 or higher is recommended.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/bamboo-pan/gemini_key_manager.git
    cd gemini_key_manager
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *Alternatively, if you prefer not to clone, ensure you have `requests` and `flask` installed (`pip install requests flask`).*

## Configuration and Usage

1.  **Create Key File:** Create a file named `key.txt` in the project directory.
2.  **Add API Keys:** Add your Google Gemini API keys to `key.txt`, placing one key per line.
3.  **Configure Placeholder (Optional):** Review and optionally change the `PLACEHOLDER_GEMINI_TOKEN` value within the `gemini_key_manager.py` script. This is the token your clients will use.
4.  **Run the Proxy Server:**
    ```bash
    python gemini_key_manager.py
    ```
    The server will start listening on `http://0.0.0.0:5000` by default.
5.  **Configure Clients:**
    *   **For Direct Gemini API Usage:** Update your client applications to send requests to the proxy server's address (`http://<proxy_server_ip>:5000/<gemini_path>`, e.g., `http://localhost:5000/v1beta/models/gemini-pro:generateContent`). Ensure clients use the configured `PLACEHOLDER_GEMINI_TOKEN` in the `x-goog-api-key` header for authentication against the proxy.
    *   **For OpenAI API Compatibility:** Configure your client (like CherryStudio, etc.) to use the proxy server's address as the base URL and target the `/v1/chat/completions` endpoint (e.g., `http://localhost:5000/v1/chat/completions`). The client should use the `PLACEHOLDER_GEMINI_TOKEN` as the API Key (typically sent as a Bearer token in the `Authorization` header). The proxy will handle the translation to and from the Gemini API.

## Deployment Note

*   **WSGI Server:** For production environments, it is strongly recommended to run the Flask application using a production-grade WSGI server like Gunicorn or Waitress instead of the built-in Flask development server (`app.run()`).
    *   Example using Waitress: `pip install waitress` then `waitress-serve --host 0.0.0.0 --port 5000 gemini_key_manager:app`
*   **Network Accessibility:** The default configuration `LISTEN_HOST = "0.0.0.0"` makes the proxy server accessible from other devices on your local network. Ensure your network environment is secure or change `LISTEN_HOST` to `"127.0.0.1"` (localhost) if you only need to access it from the same machine.
