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
*   **Configurable Logging:** Provides detailed logging to both console and rotating log files for debugging and monitoring.

## Basic Setup

1.  Create a file named `key.txt` in the same directory as the script.
2.  Add your Google Gemini API keys to `key.txt`, one key per line.
3.  Configure the `PLACEHOLDER_GEMINI_TOKEN` in the script (optional, but recommended).
4.  Run the script: `python gemini_key_manager.py`
5.  Configure your client applications to send requests to `http://<proxy_server_ip>:5000` and use the `PLACEHOLDER_GEMINI_TOKEN` in the `x-goog-api-key` header.
