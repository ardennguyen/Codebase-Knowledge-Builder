import tiktoken
import logging

# Get the shared logger from call_llm module
logger = logging.getLogger("llm_logger")

def log_token_estimation(node_name: str, prompt_content: str, max_tokens: int) -> None:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        token_count = len(encoding.encode(prompt_content))
    except Exception:
        # Fallback approximation
        token_count = len(prompt_content) // 4
        
    percentage = (token_count / max_tokens) * 100 if max_tokens else 0
    
    # Console output (yellow)
    print(f"\033[93m[Token Analytics] {node_name}: {token_count:,} / {max_tokens:,} tokens ({percentage:.1f}% capacity)\033[0m")
    
    # File log with node context
    logger.info(f"NODE EXEC | node={node_name} | estimated_tokens={token_count:,} / {max_tokens:,} ({percentage:.1f}% capacity)")
