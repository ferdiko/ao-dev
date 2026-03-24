import re
import os
from sovara.common.config import Config


# default home directory for configs and temporary/cached files
default_home: str = os.path.join(os.path.expanduser("~"), ".sovara")
SOVARA_HOME: str = os.path.expandvars(
    os.path.expanduser(os.getenv("SOVARA_HOME", default_home))
)
os.makedirs(SOVARA_HOME, exist_ok=True)

# User identity file
USER_ID_PATH = os.path.join(SOVARA_HOME, ".user_id")

# Project config directory and file
PROJECT_CONFIG_DIR = ".sovara"
PROJECT_ID_FILE = ".project_id"

# Path to config.yaml.
default_config_path = os.path.join(SOVARA_HOME, "config.yaml")
SOVARA_CONFIG = os.path.expandvars(
    os.path.expanduser(
        os.getenv(
            "SOVARA_CONFIG",
            default_config_path,
        )
    )
)

# Ensure config.yaml exists. Init with defaults if not present.
os.makedirs(os.path.dirname(SOVARA_CONFIG), exist_ok=True)
if not os.path.exists(SOVARA_CONFIG):
    default_config = Config()
    default_config.to_yaml_file(SOVARA_CONFIG)

# Load values from config file.
config = Config.from_yaml_file(SOVARA_CONFIG)

# server-related constants
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PYTHON_PORT", 5959))
SERVER_START_TIMEOUT = 2
PROCESS_TERMINATE_TIMEOUT = 5
MESSAGE_POLL_INTERVAL = 0.1
SERVER_INACTIVITY_TIMEOUT = 1200  # Shutdown server after 20 min of inactivity
SESSION_ORPHAN_TIMEOUT = 5  # Seconds before a session without SSE is considered dead
SHUTDOWN_WAIT = 2

# Experiment meta data.
DEFAULT_NOTE = "Take notes."
DEFAULT_LOG = "No entries"
DEFAULT_SUCCESS = ""
SUCCESS_STRING = {True: "Satisfactory", False: "Failed", None: ""}


# Node label constants
NO_LABEL = "No Label"

CERTAINTY_UNKNOWN = "#000000"
CERTAINTY_GREEN = "#7fc17b"  # Matches restart/rerun button
CERTAINTY_YELLOW = "#d4a825"  # Matches tag icon; currently unused
CERTAINTY_RED = "#e05252"  # Matches erase button
SUCCESS_COLORS = {
    "Satisfactory": CERTAINTY_GREEN,
    "": CERTAINTY_UNKNOWN,
    "Failed": CERTAINTY_RED,
}

# Anything cache-related should be stored here
default_cache_path = os.path.join(os.path.expanduser("~"), ".cache")
SOVARA_CACHE = os.path.expandvars(
    os.path.expanduser(
        os.getenv(
            "SOVARA_CACHE",
            os.path.join(os.getenv("XDG_CACHE_HOME", default_cache_path), ".sovara"),
        )
    )
)
os.makedirs(SOVARA_CACHE, exist_ok=True)

# Git repository for code versioning (separate from user's git)
default_git_path = os.path.join(SOVARA_HOME, "git")
SOVARA_GIT_DIR = os.path.expandvars(
    os.path.expanduser(
        os.getenv(
            "SOVARA_GIT_DIR",
            default_git_path,
        )
    )
)
# Note: Don't create the directory here - let GitVersioner handle initialization


# the path to the folder where the experiments database is stored
default_db_cache_path = os.path.join(SOVARA_HOME, "db")
SOVARA_DB_PATH = os.path.expandvars(
    os.path.expanduser(
        os.getenv(
            "SOVARA_DB_PATH",
            default_db_cache_path,
        )
    )
)
os.makedirs(SOVARA_DB_PATH, exist_ok=True)

# the path to the folder where the logs are stored
default_log_path = os.path.join(SOVARA_HOME, "logs")
SOVARA_LOG_DIR = os.path.expandvars(
    os.path.expanduser(
        os.getenv(
            "SOVARA_LOG_DIR",
            default_log_path,
        )
    )
)
os.makedirs(SOVARA_LOG_DIR, exist_ok=True)
MAIN_SERVER_LOG = os.path.join(SOVARA_LOG_DIR, "main_server.log")


default_attachment_cache = os.path.join(SOVARA_CACHE, "attachments")
ATTACHMENT_CACHE = os.path.expandvars(
    os.path.expanduser(
        os.getenv(
            "ATTACHMENT_CACHE",
            default_attachment_cache,
        )
    )
)
os.makedirs(ATTACHMENT_CACHE, exist_ok=True)

# Path to the sovara package directory
# Computed from this file's location: sovara/common/constants.py -> sovara/
# Works for both editable installs (src/sovara/) and pip installs (site-packages/sovara/)
SOVARA_INSTALL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Whitelist patterns as (url_regex, path_regex) tuples.
# A request matches if BOTH regexes match (use ".*" for "any").
# Note: path may include query params (e.g., /search?q=...), so don't use $ anchor.
WHITELIST_ENDPOINT_PATTERNS = [
    # LLM APIs (any URL, match by path)
    (r".*", r"/v1/messages"),  # Anthropic
    (r".*", r"/v1/responses"),  # OpenAI
    (r".*", r"/v1/chat/completions"),  # OpenAI
    (r".*", r"models/[^/]+:generateContent"),  # Google GenAI
    (r".*", r"models/[^/]+:streamGenerateContent"),  # Google GenAI
    (r".*", r"/api/chat"),  # Ollama
    (r".*", r"/api/generate"),  # Ollama
    (r".*", r"/api/embed"),  # Ollama embeddings (single)
    (r".*", r"/api/embeddings"),  # Ollama embeddings (batch)
    # CrewAI Tool APIs
    (r"serper\.dev", r".*"),  # All Serper tools (search, scrape, etc.)
    (r".*api\.search\.brave\.com", r"/res/v1/web/search"),  # BraveSearchTool
    (r".*r\.jina\.ai", r".*"),  # JinaScrapeWebsiteTool (any path, URL contains target)
    (r".*api\.brightdata\.com", r"/request"),  # BrightDataSerpTool, BrightDataUnlockerTool
    (r".*api\.patronus\.ai", r"/v1/evaluate"),  # PatronusEvalTool
    (r".*api\.contextual\.ai", r"/v1/datastores/"),  # ContextualAI query
    (r".*api\.contextual\.ai", r"/v1/parse"),  # ContextualAI parse
    (r".*api\.contextual\.ai", r"/v1/rerank"),  # ContextualAI rerank
    (r".*api\.parallel\.ai", r"/v1beta/search"),  # ParallelSearchTool
]
COMPILED_ENDPOINT_PATTERNS = [
    (re.compile(url_pat), re.compile(path_pat)) for url_pat, path_pat in WHITELIST_ENDPOINT_PATTERNS
]

# List of regexes that exclude patterns from being displayed in edit IO
EDIT_IO_EXCLUDE_PATTERNS = [
    r"^_.*",
    # Top-level fields
    r"^max_tokens$",
    r"^stream$",
    r"^temperature$",
    # content.* fields (metadata, usage, system info)
    r"^content\.id$",
    r"^content\.type$",
    r"^content\.object$",
    r"^content\.created(_at)?$",
    r"^content\.completed_at$",
    r"^content\.model$",
    r"^content\.status$",
    r"^content\.background$",
    r"^content\.metadata",
    r"^content\.usage",
    r"^content\.service_tier$",
    r"^content\.system_fingerprint$",
    r"^content\.stop_sequence$",
    r"^content\.billing",
    r"^content\.error$",
    r"^content\.incomplete_details$",
    r"^content\.max_output_tokens$",
    r"^content\.max_tool_calls$",
    r"^content\.parallel_tool_calls$",
    r"^content\.previous_response_id$",
    r"^content\.prompt_cache",
    r"^content\.reasoning\.(effort|summary)$",
    r"^content\.safety_identifier$",
    r"^content\.signature$",
    r"^content\.store$",
    r"^content\.temperature$",
    r"^content\.text\.(format\.type|verbosity)$",
    r"^content\.tool_choice$",
    r"^content\.top_(logprobs|p)$",
    r"^content\.truncation$",
    r"^content\.user$",
    r"^content\.responseId$",
    # content.content.* fields (array elements)
    r"^content\.content\.\d+\.(type|id|signature)$",
    r"^content\.content\.\d+\.content\.\d+\.type$",
    # content.choices.* fields
    r"^content\.choices\.\d+\.index$",
    r"^content\.choices\.\d+\.message\.(refusal|annotations|reasoning)$",
    r"^content\.choices\.\d+\.(logprobs|seed)$",
    # content.output.* fields
    r"^content\.output\.\d+\.(id|type|status)$",
    r"^content\.output\.\d+\.content\.\d+\.(type|annotations|logprobs)$",
    # content.candidates.* fields (Google Gemini)
    r"^content\.candidates\.\d+\.(finishReason|index)$",
    r"^content\.usageMetadata",
    # tools.* fields
    r"^tools\.\d+\.parameters\.(additionalProperties|properties|required|type)$",
    r"^tools\.\d+\.strict$",
    # Ollama response fields (timing/stats)
    r"^content\.done$",
    r"^content\.done_reason$",
    r"^content\.eval_count$",
    r"^content\.eval_duration$",
    r"^content\.load_duration$",
    r"^content\.prompt_eval_count$",
    r"^content\.prompt_eval_duration$",
    r"^content\.total_duration$",
]

STRING_MATCH_EXCLUDE_PATTERNS = [
    # Identifiers & timestamps
    r".*id$",
    r".*object$",
    r".*created_at$",
    r".*completed_at$",
    r".*responseId$",
    r".*previous_response_id$",
    r".*prompt_cache_key$",
    r".*safety_identifier$",
    r".*signature$",
    # Model & config
    r".*model$",
    r".*modelVersion$",
    r".*role$",
    r".*type$",
    r".*status$",
    r".*background$",
    r".*temperature$",
    r".*top_p$",
    r".*top_k$",
    r".*top_logprobs$",
    r".*frequency_penalty$",
    r".*presence_penalty$",
    r".*max_output_tokens$",
    r".*max_tokens$",
    r".*max_tool_calls$",
    r".*service_tier$",
    r".*store$",
    r".*truncation$",
    # Tool-related
    r".*tool_choice$",
    r".*tools$",
    r".*parallel_tool_calls$",
    # Stop conditions
    r".*stop_reason$",
    r".*stop_sequence$",
    r".*stop$",
    r".*finish_reason$",
    r".*finishReason$",
    # Usage/billing (entire subtrees)
    r".*usage$",
    r".*usageMetadata$",
    r".*billing$",
    # Other metadata
    r".*error$",
    r".*incomplete_details$",
    # r".*instructions$",  # May contain legitimate content
    # r".*reasoning$",  # May contain chain-of-thought content
    r".*metadata$",
    r".*user$",
    r".*index$",
    r".*logprobs$",
    r".*annotations$",
    r".*payer$",
    r".*verbosity$",
    r".*format$",
    r".*effort$",
    # r".*summary$",  # May contain legitimate summary content
    # Cache-related
    r".*prompt_cache_retention$",
    r".*cache_creation$",
    r".*cache_creation_input_tokens$",
    r".*cache_read_input_tokens$",
    # Additional patterns
    r".*reasoning_effort$",
    r".*native_finish_reason$",
    r".*provider$",
]
COMPILED_STRING_MATCH_EXCLUDE_PATTERNS = [re.compile(p) for p in STRING_MATCH_EXCLUDE_PATTERNS]

# Regex patterns to look up display names for nodes in the graph
# Each key is a regex pattern that matches URLs, value is the display name
URL_PATTERN_TO_NODE_NAME = [
    # Serper tools (different subdomains for different tools)
    (r"google\.serper\.dev", "Serper Search"),
    (r"scrape\.serper\.dev", "Serper Scrape"),
    # Brave Search
    (r"api\.search\.brave\.com/res/v1/web/search", "Brave Search"),
    # Jina (URL contains target site in path)
    (r"r\.jina\.ai/", "Jina Scrape"),
    # BrightData
    (r"api\.brightdata\.com/request", "BrightData"),
    # Patronus
    (r"api\.patronus\.ai/v1/evaluate", "Patronus Eval"),
    # ContextualAI
    (r"api\.contextual\.ai/v1/parse", "Contextual Parse"),
    (r"api\.contextual\.ai/v1/rerank", "Contextual Rerank"),
    # Parallel AI
    (r"api\.parallel\.ai/v1beta/search", "Parallel Search"),
]
COMPILED_URL_PATTERN_TO_NODE_NAME = [
    (re.compile(pattern), name) for pattern, name in URL_PATTERN_TO_NODE_NAME
]

# Exact match patterns for known models -> clean display names
# These are matched against the raw model name before cleanup rules are applied
# Order matters: more specific patterns should come before general ones
MODEL_NAME_PATTERNS = [
    # OpenAI - GPT-5 series
    (r"^(openai/)?gpt-5-mini", "GPT-5 Mini"),
    (r"^(openai/)?gpt-5-nano", "GPT-5 Nano"),
    (r"^(openai/)?gpt-5", "GPT-5"),
    # OpenAI - GPT-4.1 series
    (r"^(openai/)?gpt-4\.1-mini", "GPT-4.1 Mini"),
    (r"^(openai/)?gpt-4\.1-nano", "GPT-4.1 Nano"),
    (r"^(openai/)?gpt-4\.1", "GPT-4.1"),
    # OpenAI - GPT-4o series
    (r"^gpt-4o-mini-audio", "GPT-4o Mini Audio"),
    (r"^gpt-4o-mini-search", "GPT-4o Mini Search"),
    (r"^gpt-4o-mini-tts", "GPT-4o Mini TTS"),
    (r"^gpt-4o-mini", "GPT-4o Mini"),
    (r"^gpt-4o-audio", "GPT-4o Audio"),
    (r"^gpt-4o-search", "GPT-4o Search"),
    (r"^(chatgpt-)?gpt-4o", "GPT-4o"),
    # OpenAI - GPT-4 series
    (r"^gpt-4-turbo", "GPT-4 Turbo"),
    (r"^gpt-4", "GPT-4"),
    # OpenAI - GPT-3.5 series
    (r"^gpt-3\.5-turbo", "GPT-3.5 Turbo"),
    # OpenAI - O-series reasoning models
    (r"^(openai/)?o4-mini", "o4 Mini"),
    (r"^(openai/)?o3-pro", "o3 Pro"),
    (r"^(openai/)?o3-mini", "o3 Mini"),
    (r"^(openai/)?o3", "o3"),
    (r"^o1-pro", "o1 Pro"),
    (r"^o1-preview", "o1 Preview"),
    (r"^o1-mini", "o1 Mini"),
    (r"^o1", "o1"),
    # Anthropic - Claude 4.5 series
    (r"^claude-opus-4-5", "Claude Opus 4.5"),
    (r"^claude-sonnet-4-5", "Claude Sonnet 4.5"),
    (r"^claude-haiku-4-5", "Claude Haiku 4.5"),
    # Anthropic - Claude 4.1 series
    (r"^claude-opus-4-1", "Claude Opus 4.1"),
    # Anthropic - Claude 4 series
    (r"^claude-opus-4", "Claude Opus 4"),
    (r"^claude-sonnet-4", "Claude Sonnet 4"),
    # Anthropic - Claude 3.7 series
    (r"^claude-3-7-sonnet", "Claude 3.7 Sonnet"),
    # Anthropic - Claude 3.5 series
    (r"^claude-3-5-sonnet", "Claude 3.5 Sonnet"),
    (r"^claude-3-5-haiku", "Claude 3.5 Haiku"),
    # Anthropic - Claude 3 series
    (r"^claude-3-opus", "Claude 3 Opus"),
    (r"^claude-3-sonnet", "Claude 3 Sonnet"),
    (r"^claude-3-haiku", "Claude 3 Haiku"),
    # Google - Gemini 3 series
    (r"^gemini-3-pro-image", "Gemini 3 Pro Image"),
    (r"^gemini-3-pro", "Gemini 3 Pro"),
    (r"^gemini-3-flash", "Gemini 3 Flash"),
    # Google - Gemini 2.5 series
    (r"^gemini-2\.5-pro", "Gemini 2.5 Pro"),
    (r"^gemini-2\.5-flash-lite", "Gemini 2.5 Flash Lite"),
    (r"^gemini-2\.5-flash", "Gemini 2.5 Flash"),
    # Google - Gemini 2.0 series
    (r"^gemini-2\.0-flash-lite", "Gemini 2.0 Flash Lite"),
    (r"^gemini-2\.0-flash", "Gemini 2.0 Flash"),
    # Google - Gemini 1.5 series
    (r"^gemini-1\.5-pro", "Gemini 1.5 Pro"),
    (r"^gemini-1\.5-flash", "Gemini 1.5 Flash"),
]
COMPILED_MODEL_NAME_PATTERNS = [
    (re.compile(pattern), name) for pattern, name in MODEL_NAME_PATTERNS
]

INVALID_LABEL_CHARS = set("{[<>%$#@")

# Playbook server constants (config-aware, env vars override)
_playbook_mode = getattr(config, "playbook_mode", None) or "cloud"

if _playbook_mode == "local":
    PLAYBOOK_SERVER_URL = os.environ.get("PLAYBOOK_SERVER_URL", "http://127.0.0.1:5960")
    PLAYBOOK_API_KEY = os.environ.get("SOVARA_API_KEY", "")
else:
    PLAYBOOK_SERVER_URL = os.environ.get(
        "PLAYBOOK_SERVER_URL",
        "https://ao-playbook-732575904722.us-central1.run.app",
    )
    PLAYBOOK_API_KEY = (
        os.environ.get("SOVARA_API_KEY", "")
        or getattr(config, "playbook_api_key", "")
        or ""
    )

PLAYBOOK_SERVER_TIMEOUT = 30  # Seconds to wait for server startup

# Testing constants
TEST_USER_ID = "test-user"
TEST_PROJECT_ID = "test-project"

# Welcome banner
WELCOME_ART = """\033[32m
  ____
 / ___|  _____   ____ _ _ __ __ _
 \\___ \\ / _ \\ \\ / / _` | '__/ _` |
  ___) | (_) \\ V / (_| | | | (_| |
 |____/ \\___/ \\_/ \\__,_|_|  \\__,_|
\033[0m"""
