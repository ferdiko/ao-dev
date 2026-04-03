import re


# Whitelist patterns as (url_regex, path_regex) tuples.
# A request matches if both regexes match.
COMPILED_ENDPOINT_PATTERNS = [
    # LLM APIs
    (re.compile(r".*"), re.compile(r"/v1/messages")),  # Anthropic
    (re.compile(r".*"), re.compile(r"/v1/responses")),  # OpenAI
    (re.compile(r".*"), re.compile(r"/v1/chat/completions")),  # OpenAI
    (re.compile(r".*"), re.compile(r"models/[^/]+:generateContent")),  # Google GenAI
    (re.compile(r".*"), re.compile(r"models/[^/]+:streamGenerateContent")),  # Google GenAI
    (re.compile(r".*"), re.compile(r"/api/chat")),  # Ollama
    (re.compile(r".*"), re.compile(r"/api/generate")),  # Ollama
    (re.compile(r".*"), re.compile(r"/api/embed")),  # Ollama embeddings (single)
    (re.compile(r".*"), re.compile(r"/api/embeddings")),  # Ollama embeddings (batch)
    # CrewAI tool APIs
    (re.compile(r"serper\.dev"), re.compile(r".*")),  # All Serper tools
    (re.compile(r".*api\.search\.brave\.com"), re.compile(r"/res/v1/web/search")),  # BraveSearchTool
    (re.compile(r".*r\.jina\.ai"), re.compile(r".*")),  # JinaScrapeWebsiteTool
    (re.compile(r".*api\.brightdata\.com"), re.compile(r"/request")),  # BrightData
    (re.compile(r".*api\.patronus\.ai"), re.compile(r"/v1/evaluate")),  # PatronusEvalTool
    (re.compile(r".*api\.contextual\.ai"), re.compile(r"/v1/datastores/")),  # ContextualAI query
    (re.compile(r".*api\.contextual\.ai"), re.compile(r"/v1/parse")),  # ContextualAI parse
    (re.compile(r".*api\.contextual\.ai"), re.compile(r"/v1/rerank")),  # ContextualAI rerank
    (re.compile(r".*api\.parallel\.ai"), re.compile(r"/v1beta/search")),  # ParallelSearchTool
]
