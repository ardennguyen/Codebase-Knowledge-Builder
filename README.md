[🇺🇸 English](#-english) | [🇻🇳 Tiếng Việt](#-tiếng-việt)

---

## 🇺🇸 English

# AI Codebase Knowledge Builder

## 🚀 Getting Started

1. Clone this repository
   ```bash
   git clone https://github.com/ardennguyen/Codebase-Knowledge-Builder
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up LLM in [`utils/call_llm.py`](./utils/call_llm.py) by providing credentials. To do so, you can put the values in a `.env` file. By default, you can use the AI Studio key with this client for Gemini Pro 2.5 by setting the `GEMINI_API_KEY` environment variable. If you want to use another LLM, you can set the `LLM_PROVIDER` environment variable (e.g. `OPENROUTER`), and then set the model, url, and API key (e.g. `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`,`OPENROUTER_API_KEY`). If using Ollama, the base url is `http://localhost:11434` (e.g. `OLLAMA_BASE_URL`) and the API key can be omitted.
   You can use your own models. We highly recommend the latest models with thinking capabilities (Claude 3.7 with thinking, O1). You can verify that it is correctly set up by running:
   ```bash
   python utils/call_llm.py
   ```

4. Generate a complete codebase tutorial by running the main script:
    ```bash
    # Analyze a GitHub repository
    python main.py --repo https://github.com/username/repo --include "*.py" "*.js" --exclude "tests/*" --max-size 50000

    # Or, analyze a local directory
    python main.py --dir /path/to/your/codebase --include "*.py" --exclude "*test*"

    # Or, generate a tutorial in Vietnamese
    python main.py --repo https://github.com/username/repo --language "Vietnamese"
    ```

    - `--repo` or `--dir` - Specify either a GitHub repo URL or a local directory path (required, mutually exclusive)
    - `-n, --name` - Project name (optional, derived from URL/directory if omitted)
    - `-t, --token` - GitHub token (or set GITHUB_TOKEN environment variable)
    - `-o, --output` - Output directory (default: ./output)
    - `-i, --include` - Files to include (e.g., `*.py` `*.js`). Defaults to `*` (all files).
    - `-e, --exclude` - Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native `.gitignore` rules.
    - `-s, --max-size` - Maximum file size in bytes (default: 100KB)
    - `--language` - Language for the generated tutorial (default: "english")
    - `--max-abstractions` - Maximum number of abstractions to identify (default: 10)
    - `--no-cache` - Disable LLM response caching (default: caching enabled)
    - `--thinking-level` - Thinking effort level for native Gemini, OpenRouter, and Ollama reasoning models (e.g., low, medium, high). Leave empty to use model defaults.
    - `--max-tokens` - Maximum number of tokens for the context window (default: fetched dynamically from the model).
    - `--advanced` - Load advanced prompts from `prompts/advanced/` directory instead of the tutorial prompts.
    - `--batch` - Maximum files per batch when using map-reduce mode (default: 50).
    - `--force-batch` - Force the pipeline to use map-reduce mode regardless of context limits.

The application will crawl the repository, analyze the codebase structure, generate tutorial content in the specified language, and save the output in the specified directory (default: ./output). This includes individual chapter files, an `index.md`, and a compiled `full_content.md` containing the complete tutorial with a Table of Contents.


<details>
 
<summary> 🐳 <b>Running with Docker</b> </summary>

To run this project in a Docker container, you'll need to pass your API keys as environment variables. 

1. Build the Docker image
   ```bash
   docker build -t pocketflow-app .
   ```

2. Run the container

   You'll need to provide your `GEMINI_API_KEY` for the LLM to function. If you're analyzing private GitHub repositories or want to avoid rate limits, also provide your `GITHUB_TOKEN`.
   
   Mount a local directory to `/app/output` inside the container to access the generated tutorials on your host machine.
   
   **Example for analyzing a public GitHub repository:**
   
   ```bash
   docker run -it --rm \
     -e GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE" \
     -v "$(pwd)/output_tutorials":/app/output \
     pocketflow-app --repo https://github.com/username/repo
   ```
   
   **Example for analyzing a local directory:**
   
   ```bash
   docker run -it --rm \
     -e GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE" \
     -v "/path/to/your/local_codebase":/app/code_to_analyze \
     -v "$(pwd)/output_tutorials":/app/output \
     pocketflow-app --dir /app/code_to_analyze
   ```
</details>

## 🙏 Acknowledgement

- Built using [Pocket Flow](https://github.com/The-Pocket/PocketFlow), a 100-line LLM framework that lets Agents (e.g., Cursor, Windsurf, Copilot, Cline, Antigravity, Claude Code) build for you.

---

## 🇻🇳 Tiếng Việt

# Trình Xây Dựng Kiến Thức Mã Nguồn Bằng AI

## 🚀 Bắt đầu

1. Sao chép kho lưu trữ này (Clone repository)
   ```bash
   git clone https://github.com/ardennguyen/Codebase-Knowledge-Builder
   ```

2. Cài đặt các thư viện phụ thuộc:
   ```bash
   pip install -r requirements.txt
   ```

3. Thiết lập LLM trong [`utils/call_llm.py`](./utils/call_llm.py) bằng cách cung cấp thông tin xác thực. Để thực hiện, bạn có thể đặt các giá trị trong tệp `.env`. Theo mặc định, bạn có thể sử dụng khóa API AI Studio với client này cho Gemini Pro 2.5 bằng cách cài đặt biến môi trường `GEMINI_API_KEY`. Nếu bạn muốn sử dụng LLM khác, bạn có thể thiết lập biến `LLM_PROVIDER` (ví dụ: `OPENROUTER`), và sau đó thiết lập model, url và khóa API (ví dụ: `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`,`OPENROUTER_API_KEY`). Nếu dùng Ollama, base url là `http://localhost:11434` (ví dụ: `OLLAMA_BASE_URL`) và có thể bỏ qua API key.
   Bạn có thể dùng model của riêng mình. Chúng tôi đặc biệt khuyến nghị các model mới nhất có khả năng suy luận (Claude 3.7 với tính năng suy luận, O1). Bạn có thể xác minh xem nó đã được thiết lập đúng hay chưa bằng cách chạy:
   ```bash
   python utils/call_llm.py
   ```

4. Tạo một bản hướng dẫn toàn diện về mã nguồn bằng cách chạy tập lệnh chính:
    ```bash
    # Phân tích một kho lưu trữ GitHub
    python main.py --repo https://github.com/username/repo --include "*.py" "*.js" --exclude "tests/*" --max-size 50000

    # Hoặc, phân tích một thư mục cục bộ
    python main.py --dir /path/to/your/codebase --include "*.py" --exclude "*test*"

    # Hoặc, tạo hướng dẫn bằng tiếng Việt
    python main.py --repo https://github.com/username/repo --language "Vietnamese"
    ```

    - `--repo` hoặc `--dir` - Chỉ định URL kho lưu trữ GitHub hoặc đường dẫn thư mục cục bộ (bắt buộc, chọn một trong hai)
    - `-n, --name` - Tên dự án (tùy chọn, được trích xuất từ URL/thư mục nếu để trống)
    - `-t, --token` - Token GitHub (hoặc thiết lập biến môi trường GITHUB_TOKEN)
    - `-o, --output` - Thư mục đầu ra (mặc định: ./output)
    - `-i, --include` - Các tệp cần bao gồm (ví dụ: `*.py` `*.js`). Mặc định: `*` (tất cả các tệp).
    - `-e, --exclude` - Các tệp cần loại trừ. Các mẫu (patterns) tùy chỉnh được tự động gộp với danh sách loại trừ toàn cầu (chứa các thư mục build cache, node_modules, binaries, media, biến môi trường AI) VÀ các quy tắc `.gitignore` gốc của dự án.
    - `-s, --max-size` - Kích thước tệp tối đa tính bằng byte (mặc định: 100KB)
    - `--language` - Ngôn ngữ cho bản hướng dẫn được tạo ra (mặc định: "english")
    - `--max-abstractions` - Số lượng các khái niệm trừu tượng tối đa để xác định (mặc định: 10)
    - `--no-cache` - Vô hiệu hóa bộ nhớ cache cho phản hồi LLM (mặc định: cache được bật)
    - `--thinking-level` - Mức độ nỗ lực suy luận cho các model Gemini, OpenRouter và Ollama (ví dụ: low, medium, high). Để trống để sử dụng mặc định của model.
    - `--max-tokens` - Số lượng token tối đa cho context window (mặc định: tự động lấy từ thông tin của model).
    - `--advanced` - Tải các prompt nâng cao từ thư mục `prompts/advanced/` thay vì các prompt tạo hướng dẫn (tutorial).
    - `--batch` - Số lượng tệp tối đa mỗi lô khi sử dụng chế độ map-reduce (mặc định: 50).
    - `--force-batch` - Bắt buộc sử dụng chế độ map-reduce bất kể giới hạn context.

Ứng dụng sẽ thu thập dữ liệu từ kho lưu trữ, phân tích cấu trúc mã nguồn, tạo nội dung hướng dẫn bằng ngôn ngữ được chỉ định và lưu kết quả vào thư mục đầu ra (mặc định: ./output). Thư mục này bao gồm các tệp chương riêng lẻ, tệp `index.md`, và tệp `full_content.md` tổng hợp toàn bộ nội dung hướng dẫn với Mục lục.

<details>
 
<summary> 🐳 <b>Chạy bằng Docker</b> </summary>

Để chạy dự án này trong container Docker, bạn cần truyền khóa API của mình dưới dạng các biến môi trường.

1. Build Docker image
   ```bash
   docker build -t pocketflow-app .
   ```

2. Chạy container

   Bạn sẽ cần cung cấp `GEMINI_API_KEY` để LLM hoạt động. Nếu bạn đang phân tích các kho lưu trữ GitHub riêng tư hoặc muốn tránh giới hạn tốc độ (rate limits), hãy cung cấp thêm `GITHUB_TOKEN`.
   
   Mount một thư mục cục bộ vào `/app/output` bên trong container để truy cập các bài hướng dẫn được tạo ra trên máy tính của bạn.
   
   **Ví dụ phân tích một kho lưu trữ GitHub công khai:**
   
   ```bash
   docker run -it --rm \
     -e GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE" \
     -v "$(pwd)/output_tutorials":/app/output \
     pocketflow-app --repo https://github.com/username/repo
   ```
   
   **Ví dụ phân tích một thư mục cục bộ:**
   
   ```bash
   docker run -it --rm \
     -e GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE" \
     -v "/path/to/your/local_codebase":/app/code_to_analyze \
     -v "$(pwd)/output_tutorials":/app/output \
     pocketflow-app --dir /app/code_to_analyze
   ```
</details>

## 🙏 Lời cảm ơn

- Được xây dựng bằng [Pocket Flow](https://github.com/The-Pocket/PocketFlow), một framework LLM vỏn vẹn 100 dòng code cho phép các Tác nhân (như Cursor, Windsurf, Copilot, Cline, Antigravity, Claude Code) lập trình thay bạn.
