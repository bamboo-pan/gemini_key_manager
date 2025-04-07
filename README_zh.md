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
*   **OpenAI API 兼容性：** 可作为 `/v1/chat/completions` 端点的适配器。接受 OpenAI 格式的请求（包括流式传输），并将其与 Gemini API 格式进行相互转换。经 CherryStudio 和 Cline 测试通过。
*   **可配置日志记录：** 提供详细的日志记录到控制台和轮换日志文件，用于调试和监控。

## 先决条件

*   **Python:** 推荐使用 Python 3.7 或更高版本。

## 安装

1.  **克隆仓库：**
    ```bash
    git clone https://github.com/bamboo-pan/gemini_key_manager.git
    cd gemini_key_manager
    ```
2.  **安装依赖：**
    ```bash
    pip install -r requirements.txt
    ```
    *或者，如果您不想克隆仓库，请确保已安装 `requests` 和 `flask` (`pip install requests flask`)。*

## 配置与使用

1.  **创建密钥文件：** 在项目目录中创建一个名为 `key.txt` 的文件。
2.  **添加 API 密钥：** 将您的 Google Gemini API 密钥添加到 `key.txt` 文件中，每行放置一个密钥。
3.  **配置占位符（可选）：** 在 `gemini_key_manager.py` 脚本中检查并可选择地更改 `PLACEHOLDER_GEMINI_TOKEN` 的值。这是您的客户端将使用的令牌。
4.  **运行代理服务器：**
    ```bash
    python gemini_key_manager.py
    ```
    默认情况下，服务器将在 `http://0.0.0.0:5000` 上开始监听。
5.  **配置客户端：**
    *   **对于直接 Gemini API 调用：** 更新您的客户端应用程序，将请求发送到代理服务器的地址 (`http://<proxy_server_ip>:5000/<gemini_path>`，例如 `http://localhost:5000/v1beta/models/gemini-pro:generateContent`)。确保客户端在 `x-goog-api-key` 标头中使用配置的 `PLACEHOLDER_GEMINI_TOKEN` 以便向代理进行身份验证。
    *   **对于 OpenAI API 兼容模式：** 配置您的客户端（如 CherryStudio 等）使用代理服务器的地址作为基础 URL，并指向 `/v1/chat/completions` 端点（例如 `http://localhost:5000/v1/chat/completions`）。客户端应使用 `PLACEHOLDER_GEMINI_TOKEN` 作为 API 密钥（通常在 `Authorization` 标头中作为 Bearer 令牌发送）。代理将处理与 Gemini API 之间的格式转换。

## 部署说明

*   **WSGI 服务器：** 对于生产环境，强烈建议使用生产级的 WSGI 服务器（如 Gunicorn 或 Waitress）来运行 Flask 应用，而不是使用 Flask 内置的开发服务器 (`app.run()`)。
    *   使用 Waitress 的示例：`pip install waitress` 然后 `waitress-serve --host 0.0.0.0 --port 5000 gemini_key_manager:app`
*   **网络可访问性：** 默认配置 `LISTEN_HOST = "0.0.0.0"` 使代理服务器可以从您本地网络上的其他设备访问。请确保您的网络环境安全，或者如果您只需要从同一台机器访问，请将 `LISTEN_HOST` 更改为 `"127.0.0.1"` (localhost)。
