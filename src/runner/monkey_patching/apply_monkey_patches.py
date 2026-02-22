import builtins
import sys

from ao.runner.monkey_patching.patches.randomness_patch import random_seed_patch

# Lazy patches - these are only applied when the user imports the relevant module
# Maps module name prefix -> (patch_function_module, patch_function_name)
PATCHES = {
    "mcp": ("ao.runner.monkey_patching.patches.mcp_patches", "mcp_patch"),
    "requests": ("ao.runner.monkey_patching.patches.requests_patch", "requests_patch"),
    "google.genai": ("ao.runner.monkey_patching.patches.genai_patch", "genai_patch"),
    "numpy": ("ao.runner.monkey_patching.patches.randomness_patch", "numpy_seed_patch"),
    "torch": ("ao.runner.monkey_patching.patches.randomness_patch", "torch_seed_patch"),
    "uuid": ("ao.runner.monkey_patching.patches.randomness_patch", "uuid_patch"),
    "httpx": ("ao.runner.monkey_patching.patches.httpx_patch", "httpx_patch"),
    "claude_agent_sdk": ("ao.runner.monkey_patching.patches.claude_sdk_patch", "claude_sdk_patch"),
}

# Track which patches have been applied
_applied_patches = set()

# Store original __import__
_original_import = builtins.__import__


def _patching_import(name, globals=None, locals=None, fromlist=(), level=0):
    """
    Wrapper around __import__ that applies patches lazily when relevant modules are imported.
    Patches are applied BEFORE the user's import, ensuring we do a clean import first.
    """
    # Check if any lazy patches should be triggered BEFORE the import
    for module_prefix, (patch_module, patch_func_name) in list(PATCHES.items()):
        if module_prefix in _applied_patches:
            continue

        # Check if this import matches the prefix
        if name == module_prefix or name.startswith(module_prefix + "."):
            _applied_patches.add(module_prefix)

            # Import and apply the patch FIRST (clean import)
            patch_mod = _original_import(patch_module, fromlist=[patch_func_name])
            patch_func = getattr(patch_mod, patch_func_name)
            patch_func()

    # Now do the user's import (module is already loaded and patched)
    return _original_import(name, globals, locals, fromlist, level)


def apply_all_monkey_patches():
    """
    Apply immediate patches and install lazy import hook for heavy patches.
    """
    # Only seed stdlib random immediately (fast, always needed)
    random_seed_patch()

    # Install the lazy import hook for everything else
    builtins.__import__ = _patching_import
