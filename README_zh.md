# Gemini Key Manager

简体中文 | [English](README.md)

一个简单的 Python Flask 代理服务器，旨在有效管理多个 Google Gemini API 密钥。它允许客户端使用单个占位符令牌与 Gemini API 交互，而代理服务器则在后台处理密钥轮换、每日使用情况跟踪和速率限制管理。

当您拥有多个 API 密钥并希望分摊负载、跟踪每个密钥的使用情况以及自动处理达到每日速率限制（429 错误）的密钥时，此工具特别有用。

## 核心功能

*   **API 密钥轮换：** 为每个传入请求轮流使用提供的 Gemini API 密钥列表（`key.txt`）中的密钥。
*   **占位符令牌：** 客户端使用预定义的占位符令牌（`PLACEHOLDER_GEMINI_TOKEN`）对代理进行身份验证，从而将真实密钥安全地保留在服务器上。
*   **每日使用情况跟踪：** 监控并记录每个 API 密钥每天的使用次数。
*   **持久化使用数据：** 将每日使用计数和已耗尽密钥列表以 JSON 格式保存到本地文件（`key_usage.txt`）中，允许在服务器重启后保留状态。
*   **自动速率限制 (429) 处理：** 检测密钥何时从 Gemini API 收到 429 "Resource Exhausted" 错误。
    *   将耗尽的密钥标记为当天剩余时间内不可用。
    *   使用密钥池中的下一个可用密钥自动重试请求。
    *   如果当天所有密钥都已耗尽，则返回 503 "Service Unavailable" 错误。
*   **每日重置：** 在每个新的一天开始时自动重置使用计数和已耗尽密钥列表。
*   **可配置日志记录：** 提供详细的日志记录到控制台和轮换日志文件，用于调试和监控。

## 基本设置

1.  在脚本所在的同一目录中创建一个名为 `key.txt` 的文件。
2.  将您的 Google Gemini API 密钥添加到 `key.txt` 文件中，每行一个密钥。
3.  在脚本中配置 `PLACEHOLDER_GEMINI_TOKEN`（可选，但建议）。
4.  运行脚本：`python gemini_key_manager.py`
5.  配置您的客户端应用程序，将请求发送到 `http://<proxy_server_ip>:5000`，并在 `x-goog-api-key` 标头中使用 `PLACEHOLDER_GEMINI_TOKEN`。
