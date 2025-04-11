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

## 使用 Docker

您可以使用 Docker 来构建和运行此代理服务器，这可以简化部署和环境管理。

### 构建本地镜像

如果您想自己构建 Docker 镜像：

1.  确保您已安装 Docker。
2.  在项目根目录下（包含 `Dockerfile` 的目录）运行以下命令：
    ```bash
    docker build -t gemini-key-manager .
    ```
    这将使用当前目录下的 `Dockerfile` 构建一个名为 `gemini-key-manager` 的本地镜像。

### 使用预构建镜像

我们提供了一个预构建的 Docker 镜像，您可以直接使用：

```bash
docker pull bamboo2019/gemini-key-manager:latest # 或者指定特定 tag
```
*(请将 `latest` 替换为您需要的具体 tag)*

### 运行 Docker 容器

无论您是构建了本地镜像还是拉取了预构建镜像，运行容器的命令类似。**在运行之前，请确保您已经在本地创建了 `key.txt` 文件，并将您的 Gemini API 密钥放入其中。**

以下是运行容器的示例命令：

```bash
# 替换 <your_local_key_file_path> 为您本地 key.txt 文件的 **绝对路径** 或 **相对路径** (例如 ./key.txt)
# 替换 <your_local_usage_data_file_path> 为您希望存储持久化数据的本地 **文件路径** (例如 ./key_usage.txt)
# 替换 <your_local_log_dir> 为您希望存储日志文件的本地 **目录路径** (例如 ./logs)
# 替换 <image_name> 为您构建的本地镜像名 (例如 gemini-key-manager) 或预构建镜像名 (例如 bamboo2019/gemini-key-manager:latest)

docker run -d \
  -p 5000:5000 \
  -v "<your_local_key_file_path>:/app/key.txt" \
  -v "<your_local_usage_data_file_path>:/app/key_usage.txt" \
  -v "<your_local_log_dir>:/app/logs" \
  --name gemini-proxy \
  <image_name>
```

**参数说明：**

*   `-d`: 在后台（分离模式）运行容器。
*   `-p 5000:5000`: 将主机的 5000 端口映射到容器的 5000 端口。
*   `-v "<your_local_key_file_path>:/app/key.txt"`: **（必需）** 将您本地的 `key.txt` 文件挂载到容器内的 `/app/key.txt`。这是应用程序读取 API 密钥所必需的。请务必提供正确的本地文件路径。
*   `-v "<your_local_usage_data_file_path>:/app/key_usage.txt"`: **（推荐）** 将您本地的一个 **文件** 挂载到容器内的 `/app/key_usage.txt`。这用于持久化存储密钥使用情况和已耗尽密钥列表，即使容器重启也能保留状态。请提供一个本地文件的完整路径（例如 `/path/to/my/usage_data.txt` 或 `c:\data\usage_data.txt`）。如果本地文件不存在，Docker 通常会自动创建它（但建议您先手动创建一个空文件）。
*   `-v "<your_local_log_dir>:/app/logs"`: **（推荐）** 将本地 **目录** 挂载到容器内的 `/app/logs` 目录。这用于持久化存储应用程序日志文件，方便调试和监控。如果 `<your_local_log_dir>` 不存在，Docker 会创建它。
*   `--name gemini-proxy`: 为容器指定一个易于识别的名称。
*   `<image_name>`: 指定要使用的 Docker 镜像。

**重要提示：**

*   请确保为 `-v` 参数提供的本地文件或目录路径是正确的。对于相对路径，它们是相对于您运行 `docker run` 命令的当前目录。
*   挂载 `key_usage.txt` 文件和 `logs` 目录对于在容器重启或更新后保留状态和历史记录非常重要。
