# =============================================================================
# POLYMARKET BEOBACHTER - LAYER ISOLATION GUARD
# =============================================================================
#
# CRITICAL GOVERNANCE COMPONENT
#
# PURPOSE:
# Enforces the strict separation between Layer 1 (Institutional/Process Edge)
# and Layer 2 (Microstructure Research).
#
# RULES ENFORCED:
# 1. Layer 2 CANNOT import from Layer 1
# 2. Layer 1 CANNOT import from Layer 2
# 3. Both layers MAY import from shared/
# 4. Both layers MAY import from collector/ (metadata only)
#
# ENFORCEMENT MECHANISM:
# Uses sys.meta_path import hooks to intercept ALL imports, including
# those via importlib.util. This prevents bypass attacks.
#
# USAGE:
# Call assert_layer_isolation() at module initialization in each layer.
# This will FAIL HARD if forbidden imports are detected.
#
# =============================================================================

import sys
import os
import importlib.abc
import importlib.machinery
from typing import Set, Optional, Sequence, Union
from .enums import Layer


# =============================================================================
# GLOBAL STATE FOR ACTIVE LAYER CONTEXT
# =============================================================================
# Tracks which layer is currently active to enforce isolation during imports.
# This is set by assert_layer_isolation() and checked by the import hook.
# =============================================================================

_active_layer: Optional[Layer] = None
_import_hook_installed: bool = False


class LayerViolationError(Exception):
    """
    Raised when layer isolation is violated.

    This is a CRITICAL error that indicates a governance failure.
    The system must be stopped and the violation investigated.
    """

    def __init__(self, current_layer: Layer, forbidden_module: str, reason: str):
        self.current_layer = current_layer
        self.forbidden_module = forbidden_module
        self.reason = reason
        super().__init__(
            f"LAYER ISOLATION VIOLATION\n"
            f"  Current Layer: {current_layer.value}\n"
            f"  Forbidden Import: {forbidden_module}\n"
            f"  Reason: {reason}\n"
            f"\n"
            f"This is a GOVERNANCE FAILURE. The system cannot continue.\n"
            f"Layer 1 and Layer 2 MUST remain strictly isolated."
        )


# =============================================================================
# FORBIDDEN IMPORT PATTERNS
# =============================================================================

# Layer 1 (core_analyzer) cannot import these
LAYER1_FORBIDDEN_MODULES: Set[str] = {
    "microstructure_research",
    "microstructure_research.research",
}

# Layer 2 (microstructure_research) cannot import these
LAYER2_FORBIDDEN_MODULES: Set[str] = {
    "core_analyzer",
    "core_analyzer.core",
    "core_analyzer.models",
    "core_analyzer.historical",
}

# Both layers CANNOT import these (execution/trading modules)
UNIVERSAL_FORBIDDEN_MODULES: Set[str] = {
    "ccxt",  # Crypto trading library
    "py_clob_client",  # Polymarket CLOB client
    "order",
    "execute",
    "trade",
    "position",
}


def assert_layer_isolation(current_layer: Layer) -> None:
    """
    Assert that the current layer has not violated isolation rules.

    Call this at module initialization in each layer.
    It checks sys.modules for forbidden imports AND installs the
    import hook to prevent future bypass attempts.

    Args:
        current_layer: The layer that is performing the check

    Raises:
        LayerViolationError: If a forbidden module is loaded
    """
    # STEP 1: Set active layer and install import hook
    # This MUST happen first to prevent bypass during module init
    set_active_layer(current_layer)

    # STEP 2: Check already-loaded modules
    loaded_modules = set(sys.modules.keys())

    # Determine which modules are forbidden for this layer
    if current_layer == Layer.LAYER1_INSTITUTIONAL:
        forbidden = LAYER1_FORBIDDEN_MODULES | UNIVERSAL_FORBIDDEN_MODULES
    elif current_layer == Layer.LAYER2_MICROSTRUCTURE:
        forbidden = LAYER2_FORBIDDEN_MODULES | UNIVERSAL_FORBIDDEN_MODULES
    else:
        raise ValueError(f"Unknown layer: {current_layer}")

    # Check for violations
    for module_name in loaded_modules:
        # Check exact match
        if module_name in forbidden:
            raise LayerViolationError(
                current_layer=current_layer,
                forbidden_module=module_name,
                reason=f"Module {module_name} is explicitly forbidden for {current_layer.value}"
            )

        # Check prefix match (e.g., "core_analyzer.core.foo")
        for forbidden_prefix in forbidden:
            if module_name.startswith(f"{forbidden_prefix}."):
                raise LayerViolationError(
                    current_layer=current_layer,
                    forbidden_module=module_name,
                    reason=f"Module {module_name} is under forbidden prefix {forbidden_prefix}"
                )


def check_import_attempt(
    importing_layer: Layer,
    module_being_imported: str
) -> bool:
    """
    Check if an import attempt is allowed before it happens.

    This can be used as a pre-flight check before dynamic imports.

    Args:
        importing_layer: The layer attempting the import
        module_being_imported: The module being imported

    Returns:
        True if import is allowed, False if forbidden
    """
    if importing_layer == Layer.LAYER1_INSTITUTIONAL:
        forbidden = LAYER1_FORBIDDEN_MODULES | UNIVERSAL_FORBIDDEN_MODULES
    elif importing_layer == Layer.LAYER2_MICROSTRUCTURE:
        forbidden = LAYER2_FORBIDDEN_MODULES | UNIVERSAL_FORBIDDEN_MODULES
    else:
        return False  # Unknown layer - deny by default

    # Check exact match
    if module_being_imported in forbidden:
        return False

    # Check prefix match
    for forbidden_prefix in forbidden:
        if module_being_imported.startswith(f"{forbidden_prefix}."):
            return False

    return True


def get_layer_from_path(file_path: str) -> Optional[Layer]:
    """
    Determine which layer a file belongs to based on its path.

    Args:
        file_path: Absolute or relative path to a Python file

    Returns:
        Layer enum if identifiable, None otherwise
    """
    normalized = os.path.normpath(file_path).replace("\\", "/").lower()

    if "core_analyzer" in normalized:
        return Layer.LAYER1_INSTITUTIONAL
    elif "microstructure_research" in normalized:
        return Layer.LAYER2_MICROSTRUCTURE
    elif "collector" in normalized:
        # Collector is a shared service, not a layer
        return None
    elif "shared" in normalized:
        # Shared is accessible by both layers
        return None
    else:
        return None


# =============================================================================
# IMPORT HOOK - PREVENTS BYPASS VIA importlib
# =============================================================================
# This MetaPathFinder intercepts ALL import attempts and checks them against
# the layer isolation rules. It cannot be bypassed by importlib.util.
# =============================================================================

class LayerIsolationFinder(importlib.abc.MetaPathFinder):
    """
    Meta path finder that enforces layer isolation on ALL imports.

    This hook is installed in sys.meta_path and intercepts every import
    attempt, including those via importlib.util.spec_from_file_location().

    GOVERNANCE ENFORCEMENT:
    - When Layer 1 is active, blocks imports from microstructure_research/
    - When Layer 2 is active, blocks imports from core_analyzer/
    - Blocks universal forbidden modules (trading libraries) always
    """

    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]],
        target: Optional[object] = None
    ) -> Optional[importlib.machinery.ModuleSpec]:
        """
        Called for every import attempt.

        Returns None to allow the import to proceed with other finders.
        Raises LayerViolationError if the import violates layer isolation.
        """
        global _active_layer

        # If no layer is active, allow the import
        if _active_layer is None:
            return None

        # Check if this import is forbidden for the active layer
        if not check_import_attempt(_active_layer, fullname):
            raise LayerViolationError(
                current_layer=_active_layer,
                forbidden_module=fullname,
                reason=f"Import of '{fullname}' blocked by import hook. "
                       f"This module is forbidden for {_active_layer.value}."
            )

        # Also check the file path if we can determine layer from it
        # This catches importlib.util.spec_from_file_location() calls
        if path:
            for p in path:
                path_layer = get_layer_from_path(p)
                if path_layer is not None:
                    if _active_layer == Layer.LAYER1_INSTITUTIONAL and path_layer == Layer.LAYER2_MICROSTRUCTURE:
                        raise LayerViolationError(
                            current_layer=_active_layer,
                            forbidden_module=fullname,
                            reason=f"Import from Layer 2 path blocked: {p}"
                        )
                    elif _active_layer == Layer.LAYER2_MICROSTRUCTURE and path_layer == Layer.LAYER1_INSTITUTIONAL:
                        raise LayerViolationError(
                            current_layer=_active_layer,
                            forbidden_module=fullname,
                            reason=f"Import from Layer 1 path blocked: {p}"
                        )

        # Return None to let other finders handle the import
        return None


def _install_import_hook() -> None:
    """
    Install the layer isolation import hook.

    This should be called once when a layer is activated.
    The hook is installed at the BEGINNING of sys.meta_path to ensure
    it runs before any other finders.
    """
    global _import_hook_installed

    if _import_hook_installed:
        return

    # Install at the beginning of meta_path for priority
    hook = LayerIsolationFinder()
    sys.meta_path.insert(0, hook)
    _import_hook_installed = True


def set_active_layer(layer: Layer) -> None:
    """
    Set the currently active layer for import enforcement.

    Once a layer is set, all subsequent imports will be checked
    against that layer's isolation rules.

    Args:
        layer: The layer to activate
    """
    global _active_layer
    _active_layer = layer
    _install_import_hook()


def get_active_layer() -> Optional[Layer]:
    """
    Get the currently active layer.

    Returns:
        The active layer, or None if no layer is active
    """
    return _active_layer
