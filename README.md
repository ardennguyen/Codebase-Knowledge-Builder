[🇺🇸 English](#-english) | [🇻🇳 Tiếng Việt](#-tiếng-việt)

---

## 🇺🇸 English

# AI Codebase Knowledge Builder

## 🚀 Getting Started

1. Clone this repository
   ```bash
   git clone https://github.com/ardennguyen/Codebase-Knowledge-Builder
   ```

2. Install dependencies (we highly recommend using a virtual environment of your choice like `venv`, `conda`, `uv`, or `pyenv` to avoid polluting your global system):
   ```bash
   pip install -r requirements.txt
   ```

   > **Note:** CLI output language matches the `--language` flag. String translations are stored in `utils/strings.csv` and auto-translated via LLM for missing languages.

3. Set up LLM by copying `.env.sample` to `.env` and providing credentials. By default, you can use the AI Studio key for Gemini by setting the `GEMINI_API_KEY` environment variable (or `GEMINI_PROJECT_ID` for Vertex AI). If you want to use another LLM, you can set the `LLM_PROVIDER` environment variable (e.g. `OPENROUTER`), and then set the model, url, and API key (e.g. `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`,`OPENROUTER_API_KEY`). If using Ollama, set `LLM_PROVIDER=OLLAMA` and the base url (e.g. `OLLAMA_BASE_URL=http://localhost:11434`) — the API key can be omitted.
   To use Claude natively, set `LLM_PROVIDER=ANTHROPIC` (required — Claude is never auto-selected from `ANTHROPIC_API_KEY` alone) and `ANTHROPIC_API_KEY` (the model defaults to `claude-opus-5-5`; override with `ANTHROPIC_MODEL`). Claude runs with adaptive thinking, a per-node effort plan (`--thinking-profile balanced` by default), streaming, automatic refusal fallbacks (`ANTHROPIC_FALLBACKS`), and prints a token/cost summary at the end of the run. See `.env.sample` for the optional `ANTHROPIC_*` settings.

   **Claude without an API key (`ant auth login`):** instead of `ANTHROPIC_API_KEY`, you can sign in with Anthropic's `ant` CLI. Usage is billed to the API organization and workspace you pick at login (not a Claude.ai Pro/Max plan; Claude Code's own `/login` can't be reused).
   1. Install `ant`:
      - Windows: `winget install Anthropic.Ant`, then open a new terminal (fallback: download `ant_<version>_windows_amd64.zip` from the [releases page](https://github.com/anthropics/anthropic-cli/releases) and put `ant.exe` on your `PATH`)
      - macOS: `brew install anthropics/tap/ant`
      - Linux: the `.tar.gz` / `.deb` / `.rpm` for your architecture from the [releases page](https://github.com/anthropics/anthropic-cli/releases)
      - Any OS with Go 1.25+: `go install github.com/anthropics/anthropic-cli/cmd/ant@latest`
   2. Sign in once (a browser opens; pick your organization and workspace), then confirm the login is active:
      ```bash
      ant auth login
      ```
      ```bash
      ant auth status
      ```
   3. In `.env`, set `LLM_PROVIDER=ANTHROPIC` and leave `ANTHROPIC_API_KEY` unset — any non-empty key overrides the login.

   **Thinking on every provider:** `--thinking-profile` (default `auto` = `balanced` on Anthropic, Gemini and OpenRouter) is mapped per model:
   - **Gemini 3.1+** (native): `thinking_level` with the levels each model accepts (e.g. 3.7/3.8 Flash and 3.1 Pro have no `minimal`); Gemini 2.5 uses a thinking budget. Output (`max_output_tokens`, incl. thinking) is sized per level, requests stream, and truncation or safety/recitation blocks are detected (sampling-dependent blocks are retried, policy blocks are not). Vertex AI defaults to `GEMINI_LOCATION=global`; `gemini-flash-latest` / `gemini-pro-latest` aliases work. Needs `google-genai` >= 1.56.
   - **OpenRouter** (any model): `reasoning.effort` clamped to the model's catalog `supported_efforts` (or `reasoning.max_tokens` for budget-only models), `max_tokens` from the catalog limits, streaming, and temperature only where the model accepts it — e.g. `anthropic/claude-opus-4.6`, `anthropic/claude-sonnet-4.6`, `google/gemini-3.1-pro-preview`, `qwen/qwen3.8-flash`.
   - **Claude 4.6+** (native): adaptive thinking + effort (`xhigh` → `high` on the 4.6 family); Haiku 4.5 uses a thinking budget.
   Every run ends with a token/cost summary (cost estimated from list prices for Claude and Gemini, reported by OpenRouter, n/a for Ollama and other endpoints), and `main.py` / `utils/call_llm.py` check the SDK and credentials of the configured provider before any LLM call.

   With `LLM_PROVIDER=ANTHROPIC` and no API key, both `python main.py` and `python utils/call_llm.py` check your credentials before any LLM call (running `ant auth status`) and print what to install or run if the `anthropic` package, the `ant` CLI, or an active login is missing.
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

    - `--repo` or `--dir` - Specify either a GitHub repo URL or a local directory path (required, mutually exclusive).
    - `-n, --name` - Project name (optional, derived from repo/directory if omitted).
    - `-t, --token` - GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided).
    - `-o, --output` - Base directory for output (default: ./output).
    - `-i, --include` - Files to include (e.g., `*.py` `*.js`). Defaults to `*` (all files).
    - `-e, --exclude` - Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native `.gitignore` rules.
    - `-s, --max-size` - Maximum file size in bytes (default: 200000, about 200KB).
    - `--language` - Language for the generated tutorial (default: english).
    - `--max-abstractions` - Maximum number of abstractions to identify (default: 10).
    - `--no-cache` - Disable LLM response caching (default: caching enabled).
    - `--thinking-level` - Global thinking effort for every LLM call: `minimal`, `low`, `medium`, `high`, `xhigh`, `max` (`default` = model default). Overrides `--thinking-profile`. Mapped per provider (Anthropic effort — a thinking budget on Haiku 4.5; Gemini `thinking_level` on 3.x, thinking budget on 2.5; OpenRouter reasoning effort or budget; Ollama reasoning effort — clamped to what the model supports).
    - `--thinking-profile` - Per-node effort profile: `auto` (default: `balanced` on `ANTHROPIC`, `GEMINI` and `OPENROUTER`, model defaults elsewhere), `off`, `economy`, `balanced`, `quality`, `max`. Abstraction discovery gets the most effort, chapter writing and ordering a moderate amount, and mechanical steps (summaries, translation, file filtering) the least; shipped profiles stop at `high` except `max`. The effective per-node plan is printed at startup (`Thinking Plan:`).
    - `--thinking-override` - Per-node overrides, e.g. `--thinking-override write_chapters=high identify_abstractions=xhigh`. Nodes: `filter_files`, `map_abstractions`, `reduce_abstractions`, `identify_abstractions`, `analyze_relationships`, `order_chapters`, `write_chapters`, `chapter_summary`, `group_modules`, `translate_strings`.
    - `--max-tokens` - Maximum number of tokens for the context window (default: fetched dynamically).
    - `--mode` - Documentation style (tutorial, advanced, api-reference, sdk). (default: tutorial).
    - `--advanced` - Legacy flag: equivalent to --mode advanced.
    - `--mkdocs` - Format output for MkDocs Material (adds YAML frontmatter & nav snippet).
      - Interactive pan/zoom on Mermaid diagrams (`mkdocs-panzoom-plugin`).
      - Custom Mermaid rendering with pan & zoom support.
      - LLM-assisted sidebar grouping for `api-reference` mode (6+ modules auto-clustered into semantic sections).
      - Section index landing page (`api/index.md`) with grouped module table.
      - Run `cd output/<ProjectName> && mkdocs serve` to preview locally (requires `pip install mkdocs-material mkdocs-panzoom-plugin`).
    - `--incremental` - Enable MD5 incremental caching to skip unchanged modules (Only supported in --mode api-reference).
    - `--force-rebuild` - Clear incremental cache and regenerate all chapters from scratch (use with --incremental).
    - `--batch` - Maximum files per batch when using map-reduce mode (default: 50).
    - `--force-batch` - Force map-reduce mode regardless of context size.
    - `--debug` - Enable verbose debug output.
    - `--cleanup` - Clean up logs and cache files. Can be used standalone or after a run.

The application will crawl the repository, analyze the codebase structure, generate tutorial content in the specified language, and save the output in the specified directory (default: ./output). This includes individual chapter files, an `index.md` (with a link to the full content), and a compiled `full_content.md` — all inside a project-named subdirectory.

### Documentation Modes

| Mode | Audience | Description |
|---|---|---|
| `tutorial` | Beginners | Step-by-step walkthrough of key concepts with gentle explanations and analogies |
| `advanced` | Senior devs / PMs | Architectural deep-dive with implementation details, data structures, and design patterns |
| `api-reference` | Developers | Exhaustive per-file API documentation with public/internal separation (1:1 file mapping) |
| `sdk` | Integration devs | SDK-oriented docs focused on public API, configuration, and usage patterns |

### Usage Examples

```bash
# API Reference with MkDocs site + incremental caching
python main.py --dir /path/to/project --mode api-reference --mkdocs --incremental

# SDK documentation in Vietnamese
python main.py --dir /path/to/project --mode sdk --language Vietnamese

# Advanced mode for architecture review
python main.py --repo https://github.com/user/repo --mode advanced --thinking-level high

# Tutorial from GitHub repo with file filters
python main.py --repo https://github.com/user/repo --include "*.py" --exclude "tests/*"

# Claude Opus 5.5 (LLM_PROVIDER=ANTHROPIC): best-quality API reference, extra effort on every reference page
python main.py --dir /path/to/project --mode api-reference --mkdocs --thinking-profile quality --thinking-override write_chapters=xhigh

# Claude Opus 5.5: architecture deep-dive with maximum effort on abstraction discovery
python main.py --dir /path/to/project --mode advanced --thinking-override identify_abstractions=max

# Claude Opus 5.5 on a budget: economy profile, but keep chapter writing at medium
python main.py --dir /path/to/project --mode tutorial --thinking-profile economy --thinking-override write_chapters=medium
```


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

2. Cài đặt các thư viện phụ thuộc (chúng tôi đặc biệt khuyến nghị sử dụng môi trường ảo như `venv`, `conda`, `uv`, hoặc `pyenv` để tránh xung đột với hệ thống):
   ```bash
   pip install -r requirements.txt
   ```

   > **Ghi chú:** Ngôn ngữ hiển thị trên terminal khớp với cờ `--language`. Bản dịch chuỗi được lưu trong `utils/strings.csv` và tự động dịch qua LLM cho các ngôn ngữ chưa có.

3. Thiết lập LLM bằng cách sao chép `.env.sample` thành `.env` và cung cấp thông tin xác thực. Theo mặc định, bạn có thể sử dụng khóa API AI Studio cho Gemini bằng cách cài đặt biến môi trường `GEMINI_API_KEY` (hoặc `GEMINI_PROJECT_ID` cho Vertex AI). Nếu bạn muốn sử dụng LLM khác, bạn có thể thiết lập biến `LLM_PROVIDER` (ví dụ: `OPENROUTER`), và sau đó thiết lập model, url và khóa API (ví dụ: `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`,`OPENROUTER_API_KEY`). Nếu dùng Ollama, thiết lập `LLM_PROVIDER=OLLAMA` và base url (ví dụ: `OLLAMA_BASE_URL=http://localhost:11434`) — có thể bỏ qua API key.
   Để dùng Claude trực tiếp, thiết lập `LLM_PROVIDER=ANTHROPIC` (bắt buộc — Claude không bao giờ được tự chọn chỉ từ `ANTHROPIC_API_KEY`) và `ANTHROPIC_API_KEY` (model mặc định là `claude-opus-5-5`; đổi bằng `ANTHROPIC_MODEL`). Claude chạy với adaptive thinking, kế hoạch nỗ lực theo từng node (mặc định `--thinking-profile balanced`), streaming, tự động fallback khi bị từ chối (`ANTHROPIC_FALLBACKS`), và in tổng kết token/chi phí khi kết thúc. Xem `.env.sample` để biết các thiết lập `ANTHROPIC_*` tùy chọn.

   **Dùng Claude không cần API key (`ant auth login`):** thay cho `ANTHROPIC_API_KEY`, bạn có thể đăng nhập bằng CLI `ant` của Anthropic. Chi phí được tính vào tổ chức và workspace API bạn chọn khi đăng nhập (không phải gói Claude.ai Pro/Max; không dùng lại được `/login` của Claude Code).
   1. Cài `ant`:
      - Windows: `winget install Anthropic.Ant`, rồi mở terminal mới (dự phòng: tải `ant_<version>_windows_amd64.zip` từ [trang releases](https://github.com/anthropics/anthropic-cli/releases) và đặt `ant.exe` trong `PATH`)
      - macOS: `brew install anthropics/tap/ant`
      - Linux: gói `.tar.gz` / `.deb` / `.rpm` cho kiến trúc máy của bạn từ [trang releases](https://github.com/anthropics/anthropic-cli/releases)
      - Mọi hệ điều hành có Go 1.25+: `go install github.com/anthropics/anthropic-cli/cmd/ant@latest`
   2. Đăng nhập một lần (trình duyệt sẽ mở; chọn tổ chức và workspace), rồi kiểm tra phiên đăng nhập:
      ```bash
      ant auth login
      ```
      ```bash
      ant auth status
      ```
   3. Trong `.env`, đặt `LLM_PROVIDER=ANTHROPIC` và để trống `ANTHROPIC_API_KEY` — mọi key khác rỗng sẽ ghi đè phiên đăng nhập.

   **Suy nghĩ trên mọi nhà cung cấp:** `--thinking-profile` (mặc định `auto` = `balanced` với Anthropic, Gemini và OpenRouter) được ánh xạ theo từng model:
   - **Gemini 3.1+** (gốc): `thinking_level` với các mức mà từng model chấp nhận (ví dụ 3.7/3.8 Flash và 3.1 Pro không có `minimal`); Gemini 2.5 dùng thinking budget. Đầu ra (`max_output_tokens`, gồm cả suy nghĩ) được định cỡ theo mức, yêu cầu được stream, và phát hiện bị cắt hoặc bị chặn (safety/recitation; chặn phụ thuộc lần lấy mẫu sẽ được thử lại, chặn theo chính sách thì không). Vertex AI mặc định `GEMINI_LOCATION=global`; dùng được bí danh `gemini-flash-latest` / `gemini-pro-latest`. Cần `google-genai` >= 1.56.
   - **OpenRouter** (mọi model): `reasoning.effort` giới hạn theo `supported_efforts` trong danh mục model (hoặc `reasoning.max_tokens` với model chỉ nhận budget), `max_tokens` theo giới hạn trong danh mục, streaming, và chỉ gửi temperature khi model chấp nhận — ví dụ `anthropic/claude-opus-4.6`, `anthropic/claude-sonnet-4.6`, `google/gemini-3.1-pro-preview`, `qwen/qwen3.8-flash`.
   - **Claude 4.6+** (gốc): adaptive thinking + effort (`xhigh` → `high` với dòng 4.6); Haiku 4.5 dùng thinking budget.
   Mỗi lần chạy kết thúc bằng tổng kết token/chi phí (chi phí ước tính theo bảng giá với Claude và Gemini, do OpenRouter trả về, không rõ với Ollama và endpoint khác), và `main.py` / `utils/call_llm.py` kiểm tra SDK và thông tin đăng nhập của nhà cung cấp trước mọi lệnh gọi LLM.

   Khi `LLM_PROVIDER=ANTHROPIC` và không có API key, cả `python main.py` lẫn `python utils/call_llm.py` đều kiểm tra thông tin đăng nhập trước mọi lệnh gọi LLM (chạy `ant auth status`) và hướng dẫn cần cài hoặc chạy gì nếu thiếu gói `anthropic`, CLI `ant`, hoặc phiên đăng nhập.
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

    - `--repo` hoặc `--dir` - Chỉ định URL kho lưu trữ GitHub hoặc đường dẫn thư mục cục bộ (bắt buộc, chọn một trong hai).
    - `-n, --name` - Tên dự án (tùy chọn, được trích xuất từ URL/thư mục nếu để trống).
    - `-t, --token` - Token GitHub (hoặc thiết lập biến môi trường GITHUB_TOKEN).
    - `-o, --output` - Thư mục đầu ra (mặc định: ./output).
    - `-i, --include` - Các tệp cần bao gồm (ví dụ: `*.py` `*.js`). Mặc định: `*` (tất cả các tệp).
    - `-e, --exclude` - Các tệp cần loại trừ. Các mẫu (patterns) tùy chỉnh được tự động gộp với danh sách loại trừ toàn cầu (chứa các thư mục build cache, node_modules, binaries, media, biến môi trường AI) VÀ các quy tắc `.gitignore` gốc của dự án.
    - `-s, --max-size` - Kích thước tệp tối đa tính bằng byte (mặc định: 200000, khoảng 200KB).
    - `--language` - Ngôn ngữ cho bản hướng dẫn được tạo ra (mặc định: english).
    - `--max-abstractions` - Số lượng các khái niệm trừu tượng tối đa để xác định (mặc định: 10).
    - `--no-cache` - Vô hiệu hóa bộ nhớ cache cho phản hồi LLM (mặc định: cache được bật).
    - `--thinking-level` - Mức nỗ lực suy luận chung cho mọi lệnh gọi LLM: `minimal`, `low`, `medium`, `high`, `xhigh`, `max` (`default` = mặc định của model). Ghi đè `--thinking-profile`. Được ánh xạ theo từng nhà cung cấp (effort của Anthropic — thinking budget với Haiku 4.5; `thinking_level` của Gemini 3.x, thinking budget với 2.5; reasoning effort hoặc budget của OpenRouter; reasoning effort của Ollama — tự giới hạn theo khả năng của model).
    - `--thinking-profile` - Hồ sơ nỗ lực theo từng node: `auto` (mặc định: `balanced` với `ANTHROPIC`, `GEMINI` và `OPENROUTER`, mặc định của model với nhà cung cấp khác), `off`, `economy`, `balanced`, `quality`, `max`. Bước tìm abstraction được nhiều nỗ lực nhất, viết chương và sắp xếp ở mức vừa, các bước cơ học (tóm tắt, dịch, lọc tệp) ít nhất; các hồ sơ mặc định dừng ở `high` (trừ `max`). Kế hoạch theo từng node được in khi khởi động (`Thinking Plan:`).
    - `--thinking-override` - Ghi đè theo từng node, ví dụ `--thinking-override write_chapters=high identify_abstractions=xhigh`.
    - `--max-tokens` - Số lượng token tối đa cho context window (mặc định: tự động lấy từ thông tin của model).
    - `--mode` - Phong cách tài liệu cần tạo (`tutorial`, `advanced`, `api-reference`, `sdk`). Mặc định là `tutorial`.
    - `--advanced` - Cờ cũ (legacy flag). Tương đương với việc dùng `--mode advanced`.
    - `--mkdocs` - Định dạng đầu ra cho MkDocs Material (thêm YAML frontmatter & nav snippet).
      - Thu phóng và kéo thả tương tác trên biểu đồ Mermaid (`mkdocs-panzoom-plugin`).
      - Hiển thị Mermaid tùy chỉnh với hỗ trợ kéo & thu phóng.
      - Nhóm sidebar tự động bằng LLM cho chế độ `api-reference` (từ 6 module trở lên tự phân nhóm theo ngữ nghĩa).
      - Trang chỉ mục nhóm module (`api/index.md`) với bảng phân loại.
      - Chạy `cd output/<TênDựÁn> && mkdocs serve` để xem trước cục bộ (yêu cầu `pip install mkdocs-material mkdocs-panzoom-plugin`).
    - `--incremental` - Kích hoạt bộ nhớ đệm MD5 gia tăng để tiết kiệm tối đa token trong các lần chạy lặp lại bằng cách bỏ qua các tệp không thay đổi (Chỉ hỗ trợ khi dùng `--mode api-reference`).
    - `--force-rebuild` - Xóa bộ nhớ đệm gia tăng và tạo lại toàn bộ các chương từ đầu (dùng kèm với `--incremental`).
    - `--batch` - Số lượng tệp tối đa mỗi lô khi sử dụng chế độ map-reduce (mặc định: 50).
    - `--force-batch` - Bắt buộc sử dụng chế độ map-reduce bất kể giới hạn context.
    - `--debug` - Bật chế độ debug chi tiết.
    - `--cleanup` - Dọn dẹp logs và các tệp cache. Có thể chạy độc lập hoặc sau khi tạo tài liệu.

Ứng dụng sẽ thu thập dữ liệu từ kho lưu trữ, phân tích cấu trúc mã nguồn, tạo nội dung hướng dẫn bằng ngôn ngữ được chỉ định và lưu kết quả vào thư mục đầu ra (mặc định: ./output). Thư mục này bao gồm các tệp chương riêng lẻ, tệp `index.md` (có liên kết đến nội dung đầy đủ), và tệp `full_content.md` — tất cả nằm trong thư mục con mang tên dự án.

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
