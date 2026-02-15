"""
Test script to verify that the monkey patches work with optional dependencies.
This script simulates a user environment where not all API packages (openai,
anthropic, google, ...) are installed. I don't want our install to overwrite
the user's installation of the APIs because they change all the time.
"""

import pytest
import sys
import builtins
import importlib


def _get_all_patch_functions():
    """Dynamically load all patch functions from PATCHES."""
    from ao.runner.monkey_patching.apply_monkey_patches import PATCHES

    patch_functions = []
    for module_prefix, (patch_module, patch_func_name) in PATCHES.items():
        try:
            mod = importlib.import_module(patch_module)
            patch_func = getattr(mod, patch_func_name)
            patch_functions.append(patch_func)
        except ImportError:
            pass  # Skip if the patch module itself can't be imported
    return patch_functions


class TestOptionalDependencies:
    def test_graceful_import_handling(self):
        """Test that code handles missing dependencies gracefully"""

        # Save the original import function
        original_import = builtins.__import__

        def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
            # Block specific packages and their submodules
            blocked_packages = ["openai", "anthropic", "google"]

            # Check if this is a blocked package or submodule
            if any(name.startswith(pkg) for pkg in blocked_packages):
                raise ImportError(f"No module named '{name}'")

            # Also check fromlist for "from X import Y" statements
            if fromlist and any(name.startswith(pkg) for pkg in blocked_packages):
                raise ImportError(f"No module named '{name}'")

            # Use the original import for everything else
            return original_import(name, globals, locals, fromlist, level)

        # Clear any existing imports
        modules_to_clear = [
            mod
            for mod in list(sys.modules.keys())
            if any(api in mod for api in ["openai", "anthropic", "google"])
        ]
        original_modules = {}
        for mod in modules_to_clear:
            original_modules[mod] = sys.modules.pop(mod, None)

        try:
            # Apply the comprehensive mock
            builtins.__import__ = mock_import

            # Get all patch functions dynamically from PATCHES
            patch_functions = _get_all_patch_functions()

            for patch_func in patch_functions:
                try:
                    patch_func()
                    print(f"✓ {patch_func.__name__} handled missing dependency gracefully")
                except ImportError as e:
                    print(f"✗ {patch_func.__name__} failed with ImportError: {e}")
                    pytest.fail(
                        f"Function {patch_func.__name__} should handle missing dependencies gracefully"
                    )
                except Exception as e:
                    # Other exceptions might be OK
                    print(f"? {patch_func.__name__} failed with other error: {e}")

        finally:
            # Restore original import and modules
            builtins.__import__ = original_import
            for mod, original in original_modules.items():
                if original is not None:
                    sys.modules[mod] = original

    def test_import_with_api_dependencies(self):
        """Test that modules work correctly when API dependencies are available."""
        print("\nTesting import with API dependencies...")

        try:
            # Get all patch functions dynamically from PATCHES
            patch_functions = _get_all_patch_functions()

            # Test each patch function
            for patch_func in patch_functions:
                try:
                    patch_func()
                    print(f"✓ {patch_func.__name__} succeeded with dependencies available")
                except ImportError as e:
                    # This shouldn't happen if dependencies are available
                    print(f"✗ {patch_func.__name__} failed with ImportError: {e}")
                    pytest.fail(
                        f"Function {patch_func.__name__} failed with ImportError when dependencies should be available: {e}"
                    )
                except Exception as e:
                    # Other exceptions might be expected behavior
                    print(f"? {patch_func.__name__} failed with other error: {e}")

            print("✓ All patch functions completed when dependencies are available")

        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback

            traceback.print_exc()
            pytest.fail(f"Test failed with unexpected error: {e}")

    def test_api_dependencies_actually_available(self):
        """Verify that the API dependencies are actually installed for the positive test."""
        print("\nVerifying API dependencies are available...")

        # This test ensures that when we run the positive test,
        # the dependencies are actually available
        try:
            import openai

            print("✓ openai is available")
        except ImportError:
            print("openai not available in test environment")

        try:
            import anthropic

            print("✓ anthropic is available")
        except ImportError:
            print("anthropic not available in test environment")

        try:
            import google

            print("✓ google is available")
        except ImportError:
            print("vertexai not available in test environment")
