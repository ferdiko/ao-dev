import re


# Flattened keys matching any of these patterns are hidden from edit IO.
COMPILED_EDIT_IO_EXCLUDE_PATTERNS = [
    re.compile(r"^_.*"),
    # Top-level fields
    re.compile(r"^max_tokens$"),
    re.compile(r"^stream$"),
    re.compile(r"^temperature$"),
    # content.* fields
    re.compile(r"^content\.id$"),
    re.compile(r"^content\.type$"),
    re.compile(r"^content\.object$"),
    re.compile(r"^content\.created(_at)?$"),
    re.compile(r"^content\.completed_at$"),
    re.compile(r"^content\.model$"),
    re.compile(r"^content\.status$"),
    re.compile(r"^content\.background$"),
    re.compile(r"^content\.metadata"),
    re.compile(r"^content\.usage"),
    re.compile(r"^content\.service_tier$"),
    re.compile(r"^content\.system_fingerprint$"),
    re.compile(r"^content\.stop_sequence$"),
    re.compile(r"^content\.billing"),
    re.compile(r"^content\.error$"),
    re.compile(r"^content\.incomplete_details$"),
    re.compile(r"^content\.max_output_tokens$"),
    re.compile(r"^content\.max_tool_calls$"),
    re.compile(r"^content\.parallel_tool_calls$"),
    re.compile(r"^content\.previous_response_id$"),
    re.compile(r"^content\.prompt_cache"),
    re.compile(r"^content\.reasoning\.(effort|summary)$"),
    re.compile(r"^content\.safety_identifier$"),
    re.compile(r"^content\.signature$"),
    re.compile(r"^content\.store$"),
    re.compile(r"^content\.temperature$"),
    re.compile(r"^content\.text\.(format\.type|verbosity)$"),
    re.compile(r"^content\.tool_choice$"),
    re.compile(r"^content\.top_(logprobs|p)$"),
    re.compile(r"^content\.truncation$"),
    re.compile(r"^content\.user$"),
    re.compile(r"^content\.responseId$"),
    # content.content.* fields
    re.compile(r"^content\.content\.\d+\.(type|id|signature)$"),
    re.compile(r"^content\.content\.\d+\.content\.\d+\.type$"),
    # content.choices.* fields
    re.compile(r"^content\.choices\.\d+\.index$"),
    re.compile(r"^content\.choices\.\d+\.message\.(refusal|annotations|reasoning)$"),
    re.compile(r"^content\.choices\.\d+\.(logprobs|seed)$"),
    # content.output.* fields
    re.compile(r"^content\.output\.\d+\.(id|type|status)$"),
    re.compile(r"^content\.output\.\d+\.content\.\d+\.(type|annotations|logprobs)$"),
    # content.candidates.* fields
    re.compile(r"^content\.candidates\.\d+\.(finishReason|index)$"),
    re.compile(r"^content\.usageMetadata"),
    # tools.* fields
    re.compile(r"^tools\.\d+\.parameters\.(additionalProperties|properties|required|type)$"),
    re.compile(r"^tools\.\d+\.strict$"),
    # Ollama response fields
    re.compile(r"^content\.done$"),
    re.compile(r"^content\.done_reason$"),
    re.compile(r"^content\.eval_count$"),
    re.compile(r"^content\.eval_duration$"),
    re.compile(r"^content\.load_duration$"),
    re.compile(r"^content\.prompt_eval_count$"),
    re.compile(r"^content\.prompt_eval_duration$"),
    re.compile(r"^content\.total_duration$"),
]
