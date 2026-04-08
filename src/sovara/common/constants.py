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
RUN_ORPHAN_TIMEOUT = 5  # Seconds before a run without SSE is considered dead
SHUTDOWN_WAIT = 2

# Trace chat
SCATTER_BUDGET = 20.0
SCATTER_SUMMARY_BUDGET = 3 * SCATTER_BUDGET
# seconds

# Run meta data.
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


# the path to the folder where the runs database is stored
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
INFERENCE_SERVER_LOG = os.path.join(SOVARA_LOG_DIR, "inference_server.log")

# Inference sub-server port (5959=main, 5960=priors, 5961=inference)
INFERENCE_PORT = PORT + 2


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

# Shared helpers for graph node display names.
MODEL_TOKEN_OVERRIDES = {
    "aya": "Aya",
    "awq": "AWQ",
    "bf16": "BF16",
    "chatglm": "ChatGLM",
    "claude": "Claude",
    "codestral": "Codestral",
    "deepseek": "DeepSeek",
    "devstral": "Devstral",
    "exp": "Exp",
    "fp8": "FP8",
    "gemini": "Gemini",
    "gemma": "Gemma",
    "gguf": "GGUF",
    "glm": "GLM",
    "gpt": "GPT",
    "grok": "Grok",
    "it": "IT",
    "kimi": "Kimi",
    "llama": "Llama",
    "magistral": "Magistral",
    "medgemma": "MedGemma",
    "mistral": "Mistral",
    "mixtral": "Mixtral",
    "ministral": "Ministral",
    "moonlight": "Moonlight",
    "ocr": "OCR",
    "omni": "Omni",
    "onnx": "ONNX",
    "open": "Open",
    "opus": "Opus",
    "oss": "OSS",
    "phi": "Phi",
    "pixtral": "Pixtral",
    "pt": "PT",
    "qwen": "Qwen",
    "qwq": "QwQ",
    "sonnet": "Sonnet",
    "tts": "TTS",
    "vl": "VL",
    "vlm": "VLM",
    "voxtral": "Voxtral",
}


def _format_model_token(token: str) -> str:
    if not token:
        return token

    lower = token.lower()
    if lower in MODEL_TOKEN_OVERRIDES:
        return MODEL_TOKEN_OVERRIDES[lower]

    if re.fullmatch(r"\d+(?:\.\d+)?[a-z]+", lower):
        return token.upper()
    if re.fullmatch(r"[a-z]\d+(?:\.\d+)?[a-z]*", lower):
        return token.upper()
    if re.fullmatch(r"\d+x\d+[a-z]+", lower):
        return token.upper()
    if re.fullmatch(r"q\d+_[a-z0-9]+", lower):
        return token.upper()
    if token.isupper():
        return token

    return token[0].upper() + token[1:]


def _format_joined_tokens(*tokens: str) -> str:
    return " ".join(_format_model_token(token) for token in tokens if token)


def _format_optional_variant(variant: str | None) -> str:
    return f" {_format_model_token(variant)}" if variant else ""


def _format_optional_minor(major: str, minor: str | None) -> str:
    return f"{major}.{minor}" if minor else major


def _format_tail(tail: str | None, *, strip_gemini_preview_date: bool = False) -> str:
    if not tail:
        return ""

    cleaned_tail = tail
    if strip_gemini_preview_date:
        cleaned_tail = re.sub(r"-(preview|exp)-\d{2}-\d{4}$", r"-\1", cleaned_tail)

    return f" {_format_joined_tokens(*cleaned_tail.split('-'))}"


def _format_openai_gpt(match: re.Match[str]) -> str:
    version, tail = match.groups()
    return f"GPT-{version}{_format_tail(tail)}"


def _format_openai_gpt_oss(match: re.Match[str]) -> str:
    (size,) = match.groups()
    return f"GPT-OSS {size.upper()}"


def _format_openai_gpt_4o(match: re.Match[str]) -> str:
    mini, tail = match.groups()
    mini_suffix = " Mini" if mini else ""
    return f"GPT-4o{mini_suffix}{_format_tail(tail)}"


def _format_openai_o_series(match: re.Match[str]) -> str:
    major, variant = match.groups()
    return f"o{major}{_format_optional_variant(variant)}"


def _format_claude_modern(match: re.Match[str]) -> str:
    family, major, minor = match.groups()
    version = _format_optional_minor(major, minor)
    return f"Claude {_format_model_token(family)} {version}"


def _format_claude_legacy(match: re.Match[str]) -> str:
    major, minor, family = match.groups()
    version = _format_optional_minor(major, minor)
    return f"Claude {version} {_format_model_token(family)}"


def _format_gemini(match: re.Match[str]) -> str:
    version, tail = match.groups()
    return f"Gemini {version}{_format_tail(tail, strip_gemini_preview_date=True)}"


def _format_prefixed_family(match: re.Match[str], display_family: str) -> str:
    tail = match.group(1)
    return f"{display_family}{_format_tail(tail)}"


def _format_captured_family(match: re.Match[str]) -> str:
    prefix, tail = match.groups()
    return f"{_format_model_token(prefix)}{_format_tail(tail)}"


def _format_slug_family(match: re.Match[str]) -> str:
    prefix, tail = match.groups()
    family = _format_joined_tokens(*prefix.split("-"))
    return f"{family}{_format_tail(tail)}"


# Exact match patterns for known models -> clean display names
# These are matched against the raw model name before cleanup rules are applied
# Order matters: more specific patterns should come before general ones.
# Keep this list for truly irregular aliases that cannot be derived from family formatters.
MODEL_NAME_PATTERNS: list[tuple[str, str]] = [
    # Mistral - recent marketing aliases where the API slug does not match the display name
    (r"^mistral-small-2603$", "Mistral Small 4"),
    (r"^mistral-moderation-2603$", "Mistral Moderation 2"),
    (r"^voxtral-mini-tts-2603$", "Voxtral Mini TTS"),
    (r"^voxtral-tts-2603$", "Voxtral TTS"),
    (r"^voxtral-mini-2602$", "Voxtral Mini Transcribe 2"),
    (r"^voxtral-mini-transcribe-realtime-2602$", "Voxtral Mini Transcribe Realtime"),
    (r"^labs-leanstral-2603$", "Leanstral"),
    (r"^mistral-large-2512$", "Mistral Large 3"),
    (r"^ministral-14b-2512$", "Ministral 3 14B"),
    (r"^ministral-8b-2512$", "Ministral 3 8B"),
    (r"^ministral-3b-2512$", "Ministral 3 3B"),
    (r"^devstral-2512$", "Devstral 2"),
    (r"^labs-devstral-small-2512$", "Devstral Small 2"),
    (r"^magistral-medium-2509$", "Magistral Medium 1.2"),
    (r"^magistral-small-2509$", "Magistral Small 1.2"),
    (r"^mistral-medium-2508$", "Mistral Medium 3.1"),
]
COMPILED_MODEL_NAME_PATTERNS = [
    (re.compile(pattern), name) for pattern, name in MODEL_NAME_PATTERNS
]

# Regex formatters for model families with stable naming conventions.
# These run after exact overrides and before generic fallback formatting.
MODEL_NAME_FORMATTERS = [
    # OpenAI
    (r"^(?:chatgpt-)?gpt-4o(?:-(mini))?(?:-([a-z0-9]+(?:-[a-z0-9]+)*))?$", _format_openai_gpt_4o),
    (r"^(?:openai/)?gpt-(\d+(?:\.\d+)?)(?:-([a-z0-9]+(?:-[a-z0-9]+)*))?$", _format_openai_gpt),
    (r"^(?:openai/)?gpt-oss-(\d+[a-z])$", _format_openai_gpt_oss),
    (r"^(?:openai/)?o(\d+)(?:-(mini|pro|preview))?$", _format_openai_o_series),
    # Anthropic
    (
        r"^claude-(opus|sonnet|haiku)-(\d+)(?:-(\d{1,2}))?(?:-(?:\d{8}|latest))?$",
        _format_claude_modern,
    ),
    (
        r"^claude-(\d+)(?:-(\d{1,2}))?-(opus|sonnet|haiku)(?:-(?:\d{8}|latest|v\d))?$",
        _format_claude_legacy,
    ),
    # Google
    (r"^gemini-(\d+(?:\.\d+)?)(?:-([a-z0-9]+(?:-[a-z0-9]+)*))?$", _format_gemini),
    # Hugging Face / open-weight families
    (r"^(qwen[\w.]*|qwq)(?:-(.+))?$", _format_captured_family),
    (r"^llama(?:-(.+))?$", lambda m: _format_prefixed_family(m, "Llama")),
    (r"^(glm[\w.]*|chatglm[\w.]*)(?:-(.+))?$", _format_captured_family),
    (r"^(kimi[\w.]*|moonlight[\w.]*)(?:-(.+))?$", _format_captured_family),
    (r"^deepseek(?:-(.+))?$", lambda m: _format_prefixed_family(m, "DeepSeek")),
    (r"^(gemma[\w.]*|medgemma[\w.]*|t5gemma[\w.]*)(?:-(.+))?$", _format_captured_family),
    (r"^phi(?:-(.+))?$", lambda m: _format_prefixed_family(m, "Phi")),
    (r"^(command|aya|tiny-aya)(?:-(.+))?$", _format_slug_family),
    (r"^granite(?:-(.+))?$", lambda m: _format_prefixed_family(m, "Granite")),
    (
        r"^(?:labs-)?(open-mistral|open-mixtral|mistral|mixtral|ministral|magistral|devstral|codestral|pixtral|voxtral|leanstral)(?:-(.+))?$",
        _format_slug_family,
    ),
]
COMPILED_MODEL_NAME_FORMATTERS = [
    (re.compile(pattern, re.IGNORECASE), formatter)
    for pattern, formatter in MODEL_NAME_FORMATTERS
]

INVALID_LABEL_CHARS = set("{[<>%$#@")

# Priors server constants
DEFAULT_PRIORS_SERVER_URL = "http://127.0.0.1:5960"
PRIORS_SERVER_URL = os.environ.get("PRIORS_SERVER_URL", DEFAULT_PRIORS_SERVER_URL).rstrip("/")

PRIORS_SERVER_TIMEOUT = 30  # Seconds to wait for server startup

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
