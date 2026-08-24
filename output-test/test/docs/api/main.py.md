---
title: main.py
sidebar_position: 10
---

# main.py

> **Source:** `main.py`

Tệp `main.py` đóng vai trò là điểm nhập điều phối trung tâm (command-line entry point và root orchestrator) của toàn bộ hệ thống tạo tài liệu `test`. Thành phần này chịu trách nhiệm phân tích cú pháp các cờ lệnh từ CLI, khởi tạo môi trường thực thi, thiết lập hệ thống ghi nhật ký (logging) và bản địa hóa đa ngôn ngữ (i18n), tự động nhận diện cấu hình nhà cung cấp LLM, khởi tạo kho lưu trữ ngữ cảnh chia sẻ (`shared_store`), và kích hoạt quy trình thực thi đồ thị DAG được định nghĩa bởi luồng [flow.py](flow.py.md).

Trong chương trước ([flow.py](flow.py.md)), chúng ta đã tìm hiểu cách đồ thị có hướng không chu trình (DAG) liên kết 10 nút xử lý và quản lý luồng rẽ nhánh điều kiện. Tệp `main.py` chính là thành phần nạp dữ liệu đầu vào thực tế từ môi trường dòng lệnh để cấp phát cho đối tượng `PocketFlow` vận hành, đồng thời xử lý các tác vụ dọn dẹp tài nguyên và quản lý vòng đời ứng dụng từ đầu đến cuối.

---

## Kiến trúc Luồng Thực thi Hệ thống

Sơ đồ dưới đây mô tả chi tiết toàn bộ chu trình khởi tạo, phân giải cấu hình, kiểm tra điều kiện biên và kích hoạt luồng xử lý chính trong `main.py`:

```mermaid
flowchart TD
    subgraph CLI_Initialization["Khoi tao CLI va Cau hinh"]
        cliStart["main() bat dau"]
        parseArgs["parse_arguments()"]
        initOut["init_output()"]
        checkCleanup{"Chi chay --cleanup?"}
        runCleanEarly["_run_cleanup() va ket thuc"]
        validateSource{"Kiem tra --dir hoac --repo?"}
        raiseErr["Bao loi argparse.error()"]
    end

    subgraph Config_Resolution["Phan giai Thong so va Kho Luu tru"]
        resolveProj["resolve_mode_and_project()"]
        handleInc{"Kiem tra che do Incremental va Rebuild"}
        delManifest["Xoa manifest cache cu"]
        buildStore["build_shared_store()"]
        detectLLM["detect_llm_config()"]
        cfgLog["configure_logging()"]
        dispCfg["display_config()"]
    end

    subgraph Flow_Execution["Dieu phoi va Thuc thi Luong"]
        createFlow["create_tutorial_flow()"]
        runDAG["tutorial_flow.run(shared)"]
        checkPostCleanup{"Kiem tra co --cleanup sau chay?"}
        runCleanPost["_run_cleanup()"]
        appEnd["Ket thuc phien lam viec"]
    end

    cliStart --> parseArgs
    parseArgs --> initOut
    initOut --> checkCleanup
    checkCleanup -- Dung --> runCleanEarly
    checkCleanup -- Sai --> validateSource
    validateSource -- Thieu ca hai --> raiseErr
    validateSource -- Hop le --> resolveProj

    resolveProj --> handleInc
    handleInc -- Co --force-rebuild --> delManifest
    handleInc -- Binh thuong --> buildStore
    delManifest --> buildStore
    buildStore --> detectLLM
    detectLLM --> cfgLog
    cfgLog --> dispCfg

    dispCfg --> createFlow
    createFlow --> runDAG
    runDAG --> checkPostCleanup
    checkPostCleanup -- Co --> runCleanPost
    checkPostCleanup -- Khong --> appEnd
    runCleanPost --> appEnd

    classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;
    class cliStart,resolveProj,createFlow entryNode
```

---

## Hằng số Cấp Mô-đun (Module-Level Constants)

### `DEFAULT_INCLUDE_PATTERNS`
* **Kiểu dữ liệu**: `set[str]`
* **Giá trị**: `{"*"}`
* **Mô tả**: Tập hợp các mẫu Unix glob mặc định đại diện cho các tệp tin sẽ được đưa vào phạm vi quét của hệ thống. Giá trị mặc định khớp với mọi tệp tin (`*`), trừ khi người dùng ghi đè danh sách này bằng tùy chọn dòng lệnh `-i` hoặc `--include`.

---

## Các Hàm Cấp Mô-đun (Module-Level Functions)

### `parse_arguments()`
**Visibility**: Public  
**Signature**: `def parse_arguments() -> tuple[argparse.ArgumentParser, argparse.Namespace]:`

**Description**:  
Khởi tạo đối tượng `argparse.ArgumentParser` với các nhóm tham số toàn diện định nghĩa toàn bộ hành vi của ứng dụng. Hàm cấu hình các nhóm loại trừ lẫn nhau (mutually exclusive group) cho nguồn mã nguồn (`--repo` hoặc `--dir`), các thiết lập đầu ra, lọc tệp tin, bản địa hóa ngôn ngữ, cơ chế cache LLM, ngân sách suy luận (reasoning effort), chế độ sinh tài liệu (`tutorial`, `advanced`, `api-reference`, `sdk`), và các cờ tối ưu hóa lô (`--batch`, `--force-batch`).

**Parameters**:  
* Không có tham số đầu vào trực tiếp (sử dụng `sys.argv` ngầm định).

**Returns**:  
* `tuple[argparse.ArgumentParser, argparse.Namespace]`: Một tuple chứa thể hiện parser cấu hình và đối tượng `Namespace` chứa các giá trị tham số đã được phân tích cú pháp.

**Raises**:  
* `SystemExit`: Tự động kích hoạt bởi `argparse` khi người dùng truyền tham số không hợp lệ hoặc gọi cờ trợ giúp `-h`/`--help`.

**Example**:
```python
def parse_arguments():
    """Parse and return command-line arguments."""
    parser = argparse.ArgumentParser(description="Generate a tutorial for a GitHub codebase or local directory.")

    # Source: --repo or --dir (mutually exclusive but not required if --cleanup is used)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--repo", help="URL of the public GitHub repository.")
    source_group.add_argument("--dir", help="Path to local directory.")
    parser.add_argument("--cleanup", action="store_true", help="Clean up logs and cache files. Can be used standalone or after a run.")

    parser.add_argument("-n", "--name", help="Project name (optional, derived from repo/directory if omitted).")
    parser.add_argument("-t", "--token", help="GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided).")
    parser.add_argument("-o", "--output", default="output", help="Base directory for output (default: ./output).")
    parser.add_argument("-i", "--include", nargs="+", help="Files to include (e.g., '*.py' '*.js'). Defaults to '*' (all files).")
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        help="Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native .gitignore rules.",
    )
    parser.add_argument("-s", "--max-size", type=int, default=200000, help="Maximum file size in bytes (default: 200000, about 200KB).")
    # Add language parameter for multi-language support
    parser.add_argument("--language", default="english", help="Language for the generated tutorial (default: english).")
    # Add use_cache parameter to control LLM caching
    parser.add_argument("--no-cache", action="store_true", help="Disable LLM response caching (default: caching enabled).")
    # Add max_abstraction_num parameter to control the number of abstractions
    parser.add_argument("--max-abstractions", type=int, default=10, help="Maximum number of abstractions to identify (default: 10).")
    # Add thinking_level parameter for LLM reasoning capabilities
    parser.add_argument(
        "--thinking-level",
        default=None,
        help="Thinking effort level for native Gemini, OpenRouter, and Ollama reasoning models (e.g., low, medium, high). Leave empty to use model defaults.",
    )
    # Add max_tokens parameter
    parser.add_argument(
        "--max-tokens", type=int, default=None, help="Maximum number of tokens for the context window (default: fetched dynamically)."
    )

    # --- Documentation Mode & Generation Styles ---
    parser.add_argument(
        "--mode",
        choices=["tutorial", "advanced", "api-reference", "sdk"],
        default="tutorial",
        help="Documentation style (tutorial, advanced, api-reference, sdk). (default: tutorial).",
    )
    parser.add_argument("--advanced", action="store_true", help="Legacy flag: equivalent to --mode advanced.")
    parser.add_argument("--mkdocs", action="store_true", help="Format output for MkDocs Material (adds YAML frontmatter & nav snippet).")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Enable MD5 incremental caching to skip unchanged modules (Only supported in --mode api-reference).",
    )
    parser.add_argument(
        "--force-rebuild", action="store_true", help="Clear incremental cache and regenerate all chapters from scratch (use with --incremental)."
    )

    # Add batching parameters
    parser.add_argument("--batch", type=int, default=50, help="Maximum files per batch when using map-reduce mode (default: 50).")
    parser.add_argument("--force-batch", action="store_true", help="Force map-reduce mode regardless of context size.")
    # Debug mode
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output.")

    return parser, parser.parse_args()
```

Hàm `parse_arguments()` thiết lập giao diện dòng lệnh linh hoạt cho toàn bộ công cụ. Nhóm nguồn đầu vào sử dụng `add_mutually_exclusive_group()` để đảm bảo người dùng chỉ cung cấp `--repo` hoặc `--dir` trong một phiên thực thi, nhưng không bắt buộc ràng buộc này ở cấp độ parser nhằm hỗ trợ cờ độc lập `--cleanup`. Các tham số quan trọng như `--thinking-level`, `--incremental`, và `--mode` được cung cấp với các giá trị mặc định an toàn, đồng thời hỗ trợ tương thích ngược cho cờ cũ `--advanced` (tương đương `--mode advanced`). Cấu hình phân tích này cho phép toàn bộ hệ thống downstream trích xuất chính xác cấu hình runtime mà không gây xung đột định dạng dữ liệu.

---

### `resolve_mode_and_project()`
**Visibility**: Public  
**Signature**: `def resolve_mode_and_project(args: argparse.Namespace) -> tuple[str, str]:`

**Description**:  
Xử lý logic ưu tiên chế độ tài liệu (giải quyết trường hợp sử dụng cờ kế thừa `--advanced`) và suy luận tên dự án chuẩn hóa từ đường dẫn thư mục cục bộ hoặc URL kho lưu trữ từ xa khi người dùng không truyền tham số `-n`/`--name`.

**Parameters**:  
* `args` (`argparse.Namespace`): Đối tượng chứa các tham số dòng lệnh đã được phân tích cú pháp từ `parse_arguments()`.

**Returns**:  
* `tuple[str, str]`: Tuple chứa `(mode, project_name)` trong đó `mode` là chuỗi định danh chế độ tài liệu và `project_name` là tên chuẩn hóa của dự án.

**Raises**:  
* Không phát sinh ngoại lệ trực tiếp.

**Example**:
```python
def resolve_mode_and_project(args):
    """Resolve documentation mode (handling --advanced legacy flag) and derive project name.

    Returns:
        tuple[str, str]: (mode, project_name)
    """
    mode = "advanced" if args.advanced else args.mode
    project_name = args.name
    if not project_name:
        if args.dir:
            project_name = os.path.basename(os.path.abspath(args.dir))
        elif args.repo:
            project_name = args.repo.rstrip("/").split("/")[-1]
        else:
            project_name = "project"
    return mode, project_name
```

Hàm `resolve_mode_and_project()` áp dụng chuỗi logic dự phòng (fallback cascade) phân tầng nhằm đảm bảo tên dự án luôn được xác định hợp lệ. Nếu `--name` không được chỉ định, hàm sẽ chuẩn hóa đường dẫn tuyệt đối của `args.dir` và lấy tên thư mục cơ sở thông qua `os.path.basename(os.path.abspath(args.dir))`. Trong trường hợp sử dụng kho lưu trữ GitHub từ xa, hàm thực hiện cắt bỏ dấu gạch chéo ở cuối chuỗi URL (`rstrip("/")`) và trích xuất phân đoạn đường dẫn cuối cùng (`split("/")[-1]`). Nếu cả hai điều kiện trên đều không áp dụng được (ví dụ khi chỉ thực thi dọn dẹp), giá trị mặc định `"project"` sẽ được gán để tránh các lỗi `NoneType` trong các mô-đun ghi nhật ký hoặc tạo đường dẫn lưu trữ.

---

### `build_shared_store()`
**Visibility**: Public  
**Signature**: `def build_shared_store(args: argparse.Namespace, github_token: str | None, mode: str) -> dict:`

**Description**:  
Khởi tạo cấu trúc dữ liệu từ điển chia sẻ trung tâm (`shared_storage`) được sử dụng xuyên suốt vòng đời của đồ thị `PocketFlow`. Cấu trúc này chứa toàn bộ các tham số cấu hình tĩnh, tập hợp mẫu lọc bao gồm/loại trừ tệp đã được hợp nhất với [DEFAULT_EXCLUDE_PATTERNS](utils/exclude_patterns.py.md), và các khóa rỗng sẵn sàng cho các nút xử lý trong [nodes.py](nodes.py.md) cập nhật dữ liệu.

**Parameters**:  
* `args` (`argparse.Namespace`): Đối tượng tham số dòng lệnh.
* `github_token` (`str | None`): Token xác thực GitHub cá nhân nếu làm việc với kho lưu trữ từ xa.
* `mode` (`str`): Chế độ sinh tài liệu đã được phân giải từ `resolve_mode_and_project()`.

**Returns**:  
* `dict`: Bộ nhớ lưu trữ trạng thái tập trung chứa cấu hình khởi tạo và các khe dữ liệu trống (`files`, `abstractions`, `relationships`, `chapter_order`, `chapters`, `final_output_dir`).

**Raises**:  
* Không phát sinh ngoại lệ trực tiếp.

**Example**:
```python
def build_shared_store(args, github_token, mode):
    """Construct the shared store dictionary passed between PocketFlow nodes.

    Returns:
        dict: The shared store with all CLI args, patterns, and empty output slots.
    """
    return {
        "repo_url": args.repo,
        "local_dir": args.dir,
        "project_name": args.name,  # Can be None, FetchRepo will derive it
        "github_token": github_token,
        "output_dir": args.output,  # Base directory for CombineTutorial output
        # Include/exclude patterns and max file size
        "include_patterns": set(args.include) if args.include else DEFAULT_INCLUDE_PATTERNS,
        "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS.union(set(args.exclude)) if args.exclude else DEFAULT_EXCLUDE_PATTERNS,
        "max_file_size": args.max_size,
        # Language for multi-language support
        "language": args.language,
        # Cache flag (inverse of no-cache)
        "use_cache": not args.no_cache,
        # Max abstractions
        "max_abstraction_num": args.max_abstractions,
        # LLM reasoning capabilities
        "thinking_level": args.thinking_level,
        # Max tokens override
        "max_tokens": args.max_tokens,
        # Mode, mkdocs, and incremental
        "mode": mode,
        "mkdocs": args.mkdocs,
        "incremental": args.incremental,
        "advanced_mode": mode == "advanced",
        # Batching settings
        "batch_size": args.batch,
        "force_batch": args.force_batch,
        # Debug mode
        "debug": args.debug,
        # Outputs populated by downstream nodes
        "files": [],
        "abstractions": [],
        "relationships": {},
        "chapter_order": [],
        "chapters": [],
        "final_output_dir": None,
    }
```

Hàm `build_shared_store()` thiết lập hợp đồng dữ liệu (data contract) nền tảng cho khung làm việc `PocketFlow`. Bằng cách hợp nhất danh sách mẫu loại trừ từ cờ dòng lệnh `-e`/`--exclude` trực tiếp với `DEFAULT_EXCLUDE_PATTERNS` qua phép toán tập hợp `union()`, hàm đảm bảo các quy tắc lọc mặc định (như thư mục ảo, tệp nhị phân, node_modules) luôn được áp dụng nghiêm ngặt mà không bị ghi đè hoàn toàn. Việc khởi tạo trước các mảng và từ điển rỗng cho các khóa downstream như `files`, `abstractions`, `relationships` và `chapters` giúp ngăn chặn các ngoại lệ `KeyError` tiềm ẩn khi các nút trong luồng DAG truy xuất hoặc ghi đè dữ liệu theo từng giai đoạn tuần tự.

---

### `detect_llm_config()`
**Visibility**: Public  
**Signature**: `def detect_llm_config(args: argparse.Namespace) -> tuple[str, str, str, str, int]:`

**Description**:  
Kiểm tra biến môi trường để xác định nhà cung cấp LLM (`LLM_PROVIDER`), mô hình suy luận, điểm cuối API và khóa xác thực. Hàm thực hiện cơ chế dự phòng tự động sang Google Gemini nếu không có cấu hình nhà cung cấp tường minh, đồng thời phân giải kích thước cửa sổ ngữ cảnh tối đa bằng cách ưu tiên tham số `--max-tokens` hoặc gọi hàm [get_model_context_length](utils/call_llm.py.md).

**Parameters**:  
* `args` (`argparse.Namespace`): Đối tượng tham số dòng lệnh chứa cờ ghi đè `--max-tokens`.

**Returns**:  
* `tuple`: Một bộ 5 phần tử gồm `(provider, model_name, endpoint_url, api_key, context_length)`.

**Raises**:  
* Không phát sinh ngoại lệ; các biến thiếu sẽ được gán chuỗi `"unknown"` hoặc `""`.

**Example**:
```python
def detect_llm_config(args):
    """Detect LLM provider, model, endpoint, and context length from environment.

    Returns:
        tuple: (provider, model_name, endpoint_url, api_key, context_length)
    """
    from utils.call_llm import get_model_context_length

    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        model_name = os.environ.get(f"{provider}_MODEL", "unknown")
        endpoint_url = os.environ.get(f"{provider}_BASE_URL", "unknown")
        api_key = os.environ.get(f"{provider}_API_KEY", "")
    else:
        # Fallback to Gemini if neither provider is explicitly set but it's used
        if os.environ.get("GEMINI_PROJECT_ID") or os.environ.get("GEMINI_API_KEY"):
            provider = "GEMINI"
            model_name = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
            endpoint_url = "generativelanguage.googleapis.com"
            api_key = os.environ.get("GEMINI_API_KEY", "")
        else:
            provider = "UNKNOWN"
            model_name = "unknown"
            endpoint_url = "unknown"
            api_key = ""

    context_length = args.max_tokens or get_model_context_length(endpoint_url, model_name, api_key)
    return provider, model_name, endpoint_url, api_key, context_length
```

Hàm `detect_llm_config()` cung cấp khả năng tự động thích ứng với cấu hình môi trường của hệ thống. Đầu tiên, hàm kiểm tra biến `LLM_PROVIDER` để suy luận các biến tiền tố tương ứng như `{provider}_MODEL`, `{provider}_BASE_URL` và `{provider}_API_KEY` (hỗ trợ OpenAI, Anthropic, OpenRouter, Ollama). Nếu không phát hiện nhà cung cấp tường minh, hàm kiểm tra các biến đặc thù của Google Gemini (`GEMINI_PROJECT_ID` hoặc `GEMINI_API_KEY`) để thiết lập cấu hình mặc định là `gemini-3.7-flash`. Cuối cùng, hàm áp dụng kỹ thuật nhập khẩu trễ (lazy import) đối với `get_model_context_length` từ [utils.call_llm](utils/call_llm.py.md) nhằm truy vấn giới hạn token thời gian thực từ API nhà cung cấp nếu người dùng không ghi đè bằng cờ `--max-tokens`.

---

### `display_config()`
**Visibility**: Public  
**Signature**: `def display_config(args: argparse.Namespace, mode: str, provider: str, model_name: str, endpoint_url: str, context_length: int, log_file: str) -> None:`

**Description**:  
Định dạng và hiển thị toàn bộ bảng tóm tắt cấu hình thực thi ra console trước khi kích hoạt quy trình sinh tài liệu. Hàm sử dụng hệ thống bản địa hóa thông qua các hàm [emit](utils/output.py.md) và [get](utils/output.py.md) để hỗ trợ hiển thị giao diện đa ngôn ngữ nhất quán.

**Parameters**:  
* `args` (`argparse.Namespace`): Đối tượng tham số dòng lệnh.
* `mode` (`str`): Chế độ sinh tài liệu hiện tại.
* `provider` (`str`): Tên định danh nhà cung cấp LLM.
* `model_name` (`str`): Tên mô hình AI đang được sử dụng.
* `endpoint_url` (`str`): URL của API endpoint.
* `context_length` (`int`): Kích thước cửa sổ ngữ cảnh tối đa đã được tính toán.
* `log_file` (`str`): Đường dẫn tệp nhật ký của phiên làm việc.

**Returns**:  
* `None`

**Raises**:  
* Không phát sinh ngoại lệ trực tiếp.

**Example**:
```python
def display_config(args, mode, provider, model_name, endpoint_url, context_length, log_file):
    """Emit all configuration values to the console."""
    emit("START_GENERATION", source=args.repo or args.dir, language=args.language.capitalize())
    emit("CFG_HEADER")
    emit("CFG_AI_PROVIDER", value=provider)
    emit("CFG_AI_ENDPOINT", value=endpoint_url)
    emit("CFG_AI_MODEL", value=model_name)
    emit("CFG_CONTEXT_LENGTH", value=f"{context_length:,}")
    emit("CFG_THINKING_LEVEL", value=args.thinking_level or "None")
    emit("CFG_BATCH_SIZE", value=f"{args.batch}")
    _enabled = get("CFG_VALUE_ENABLED")
    _disabled = get("CFG_VALUE_DISABLED")
    emit("CFG_FORCE_BATCH", value=_enabled if args.force_batch else _disabled)
    emit("CFG_OUTPUT_MODE", value=mode)
    emit("CFG_MKDOCS", value=_enabled if args.mkdocs else _disabled)
    emit("CFG_INCREMENTAL", value=_enabled if args.incremental else _disabled)
    if args.incremental:
        emit("CFG_FORCE_REBUILD", value=_enabled if args.force_rebuild else _disabled)
    if mode == "api-reference":
        emit("CFG_MAX_ABSTRACTIONS", value=get("CFG_VALUE_API_REF_MAX"))
    else:
        emit("CFG_MAX_ABSTRACTIONS", value=str(args.max_abstractions))
    emit("CFG_LLM_CACHING", value=_disabled if args.no_cache else _enabled)
    if args.debug:
        emit("CFG_DEBUG_MODE")
    emit("CFG_LOG_FILE", value=log_file)
    print()  # Blank line after config block
```

Hàm `display_config()` đảm bảo trải nghiệm người dùng minh bạch bằng cách thông báo đầy đủ các thông số trước khi hệ thống tiêu tốn tài nguyên mạng hoặc token API. Hàm sử dụng mẫu phát tín hiệu sự kiện thông qua các khóa tài nguyên như `START_GENERATION`, `CFG_HEADER`, `CFG_AI_PROVIDER`... được định nghĩa tại [utils.output](utils/output.py.md). Các cờ boolean (`force_batch`, `mkdocs`, `incremental`, `use_cache`) được dịch động sang văn bản hiển thị theo ngôn ngữ mục tiêu (`Enabled`/`Disabled` hoặc các chuỗi bản địa hóa tương đương) thông qua hàm `get()`. Ngoài ra, nếu chế độ là `api-reference`, hàm sẽ tự động hiển thị nhãn tối đa hóa trừu tượng hóa chuyên biệt thay vì con số nguyên thông thường.

---

### `_run_cleanup()`
**Visibility**: Private / Internal  
**Signature**: `def _run_cleanup() -> None:`

**Description**:  
Thực hiện dọn dẹp các tệp đệm và thư mục nhật ký được tạo ra trong quá trình chạy ứng dụng. Hàm xóa tệp bộ nhớ đệm phản hồi LLM (`llm_cache.json`) và xóa toàn bộ thư mục chứa log (mặc định lấy từ biến môi trường `LOG_DIR` hoặc thư mục `logs`).

**Parameters**:  
* Không có tham số đầu vào.

**Returns**:  
* `None`

**Raises**:  
* Không phát sinh ngoại lệ ra ngoài; toàn bộ lỗi xóa tệp hoặc thư mục đều được bắt qua khối `try...except` và thông báo qua `emit("CLEANUP_FAILED")`.

**Example**:
```python
def _run_cleanup():
    """Clean up cache files and log directory."""
    import shutil

    emit("CLEANUP_START")

    for cache_path in ["llm_cache.json"]:
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                emit("CLEANUP_REMOVED", path=cache_path)
            except Exception as e:
                emit("CLEANUP_FAILED", path=cache_path, error=e)

    log_dir = os.environ.get("LOG_DIR", "logs")
    if os.path.exists(log_dir) and os.path.isdir(log_dir):
        try:
            shutil.rmtree(log_dir)
            emit("CLEANUP_REMOVED_DIR", path=log_dir)
        except Exception as e:
            emit("CLEANUP_FAILED", path=log_dir, error=e)
```

Hàm `_run_cleanup()` đảm bảo việc bảo trì hệ thống và giải phóng dung lượng đĩa diễn ra an toàn. Bằng cách nhập khẩu cục bộ `shutil` và duyệt qua danh sách các tệp cache đã biết, hàm kiểm tra sự tồn tại của từng đối tượng trước khi thực hiện xóa. Nếu gặp xung đột phân quyền I/O hoặc tệp đang bị khóa bởi tiến trình khác, ngoại lệ được bắt giữ và phát tín hiệu `CLEANUP_FAILED` kèm thông điệp lỗi cụ thể tới console thông qua [output.emit](utils/output.py.md) mà không làm sập luồng điều khiển của ứng dụng.

---

### `main()`
**Visibility**: Public  
**Signature**: `def main() -> None:`

**Description**:  
Điểm nhập thực thi chính (main entry point) của ứng dụng CLI. Hàm điều phối toàn bộ chuỗi quy trình: phân tích tham số dòng lệnh, khởi tạo tầng hiển thị bản địa hóa, kiểm tra ràng buộc đầu vào, xử lý token GitHub, phân giải manifest cho chế độ incremental/rebuild, xây dựng shared store, thiết lập logging, hiển thị cấu hình, khởi tạo đối tượng `Flow` từ `create_tutorial_flow()`, kích hoạt luồng DAG và thực thi dọn dẹp sau khi chạy nếu được yêu cầu.

**Parameters**:  
* Không có tham số đầu vào.

**Returns**:  
* `None`

**Raises**:  
* `SystemExit`: Kích hoạt khi thiếu các tham số nguồn bắt buộc (`--repo` hoặc `--dir`) mà không có cờ `--cleanup`.

**Example**:
```python
def main():
    parser, args = parse_arguments()
    init_output(
        language=args.language,
        use_cache=not args.no_cache,
        thinking_level=args.thinking_level,
    )

    # Handle standalone --cleanup (no --dir or --repo)
    if args.cleanup and not args.dir and not args.repo:
        _run_cleanup()
        return

    # Require --dir or --repo for generation
    if not args.dir and not args.repo:
        parser.error("one of the arguments --repo --dir --cleanup is required")

    # Get GitHub token from argument or environment variable if using repo
    github_token = None
    if args.repo:
        github_token = args.token or os.environ.get("GITHUB_TOKEN")
        if not github_token:
            emit("WARN_NO_GITHUB_TOKEN")

    mode, project_name = resolve_mode_and_project(args)

    # Enforce incremental cache constraints
    if args.incremental and mode != "api-reference":
        emit("WARN_INCREMENTAL_API_ONLY")
        args.incremental = False

    # Handle --force-rebuild: delete the cache manifest to force fresh generation
    if args.force_rebuild and args.incremental:
        output_base = args.output or "output"
        manifest_path = os.path.join(output_base, project_name, ".doc_cache_manifest.json")
        if os.path.exists(manifest_path):
            os.remove(manifest_path)
            emit("FORCE_REBUILD_DELETED", path=manifest_path)
        else:
            emit("FORCE_REBUILD_NO_MANIFEST", path=manifest_path)
    elif args.force_rebuild and not args.incremental:
        emit("WARN_FORCE_REBUILD_NO_INCREMENTAL")

    shared = build_shared_store(args, github_token, mode)
    provider, model_name, endpoint_url, _, context_length = detect_llm_config(args)
    log_file = configure_logging(project_name=project_name, mode=mode)
    display_config(args, mode, provider, model_name, endpoint_url, context_length, log_file)

    # Create and run the flow
    tutorial_flow = create_tutorial_flow()
    tutorial_flow.run(shared)

    # Cleanup after run if requested
    if args.cleanup:
        _run_cleanup()


if __name__ == "__main__":
    main()
```

Hàm `main()` là trung tâm điều hướng của toàn bộ hệ thống. Logic bắt đầu bằng việc gọi `init_output()` từ [utils.output](utils/output.py.md) nhằm thiết lập từ điển bản địa hóa và trạng thái cache console trước khi bất kỳ thông báo nào được phát ra. Nếu cờ `--cleanup` được gọi đơn lẻ (không đi kèm `--dir` hay `--repo`), hàm lập tức dọn dẹp và thoát mà không yêu cầu thêm dữ liệu. Đối với quy trình sinh tài liệu, hàm kiểm tra nghiêm ngặt tính hợp lệ của cờ `--incremental` (chỉ cho phép hoạt động trong chế độ `api-reference`). Nếu cờ `--force-rebuild` được bật, hàm chủ động tìm và xóa tệp `.doc_cache_manifest.json` trong thư mục đầu ra của dự án nhằm buộc hệ thống tái tạo toàn bộ tài liệu từ đầu. Cuối cùng, hàm kết nối với [flow.create_tutorial_flow()](flow.py.md) để chuyển giao quyền điều khiển cho đồ thị DAG thực thi với kho lưu trữ `shared`.

---

## Xem Thêm (See Also)

* [flow.py](flow.py.md) — Định nghĩa cấu trúc đồ thị luồng xử lý DAG và chính sách tự phục hồi (retry policy) được khởi tạo bởi `create_tutorial_flow()`.
* [nodes.py](nodes.py.md) — Triển khai chi tiết các nút nghiệp vụ tiêu thụ và cập nhật dữ liệu vào `shared_store`.
* [utils/output.py](utils/output.py.md) — Hệ thống quản lý hiển thị CLI, bản địa hóa thông báo đa ngôn ngữ và cấu hình ghi nhật ký phiên làm việc.
* [utils/exclude_patterns.py](utils/exclude_patterns.py.md) — Cung cấp tập hợp mẫu loại trừ tĩnh mặc định `DEFAULT_EXCLUDE_PATTERNS`.
* [utils/call_llm.py](utils/call_llm.py.md) — Cung cấp hàm `get_model_context_length` để xác định động giới hạn cửa sổ ngữ cảnh của các mô hình AI.

