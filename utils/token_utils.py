import tiktoken

def log_token_estimation(node_name: str, prompt_content: str, max_tokens: int) -> None:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        token_count = len(encoding.encode(prompt_content))
    except Exception:
        # Fallback approximation
        token_count = len(prompt_content) // 4
        
    percentage = (token_count / max_tokens) * 100 if max_tokens else 0
    
    # Beautifully formatted CLI log using yellow (\033[93m)
    print(f"\033[93m[Token Analytics] {node_name}: {token_count:,} / {max_tokens:,} tokens ({percentage:.1f}% capacity)\033[0m")
