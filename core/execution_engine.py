# =============================================================================
# POLYMARKET BEOBACHTER - EXECUTION ENGINE
# =============================================================================
#
# CRITICAL SAFETY SYSTEM
#
# This module controls ALL order execution for the trading system.
# It implements multiple layers of safety to prevent unintended trading.
#
# NON-NEGOTIABLE SAFETY RULES:
# 1. DEFAULT STATE ON STARTUP: DISABLED
# 2. No order can be sent unless explicitly ARMED via CLI
# 3. ARMED requires 2-step confirmation
# 4. LIVE mode requires BOTH:
#    - ENV var: POLYMARKET_LIVE=1
#    - Valid API keys present
# 5. In ANY error → immediate transition to DISABLED
#
# EXECUTION MODES (most restrictive to least):
# DISABLED → SHADOW → PAPER → ARMED → LIVE
#
# =============================================================================

import hashlib
import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from enum import Enum
import uuid

from shared.enums import (
    ExecutionMode,
    OrderSide,
    OrderType,
    OrderStatus,
    OrderRejectionReason,
)

# API Client - imported lazily to avoid loading in non-LIVE modes
# DO NOT import at module level - this prevents accidental instantiation
_api_client_module = None

logger = logging.getLogger(__name__)


# =============================================================================
# SAFETY CONSTANTS
# =============================================================================
#
# These constants are HARDCODED and cannot be changed at runtime.
# Any attempt to bypass these is a CRITICAL SECURITY VIOLATION.
#
# =============================================================================

# Environment variable required for LIVE mode
LIVE_MODE_ENV_VAR: str = "POLYMARKET_LIVE"
LIVE_MODE_ENV_VALUE: str = "1"

# API key environment variables
API_KEY_ENV_VAR: str = "POLYMARKET_API_KEY"
API_SECRET_ENV_VAR: str = "POLYMARKET_API_SECRET"
API_PASSPHRASE_ENV_VAR: str = "POLYMARKET_API_PASSPHRASE"
PRIVATE_KEY_ENV_VAR: str = "POLYMARKET_PRIVATE_KEY"

# Arm confirmation timeout (seconds)
ARM_CONFIRMATION_TIMEOUT: int = 60

# State file for persistence
STATE_FILE_PATH: Path = Path(__file__).parent.parent / "data" / "execution_state.json"

# Maximum orders per minute (rate limit)
MAX_ORDERS_PER_MINUTE: int = 10

# Execution log path
EXECUTION_LOG_PATH: Path = Path(__file__).parent.parent / "logs" / "execution"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class OrderRequest:
    """
    Request to submit an order.

    This is the input to the execution engine.
    """
    # Required fields
    market_id: str
    token_id: str
    side: OrderSide
    price: float  # 0.0 to 1.0
    size: float  # Number of shares

    # Optional fields
    order_type: OrderType = OrderType.GTC
    tick_size: float = 0.01
    neg_risk: bool = False

    # Metadata
    source: str = "panic_engine"  # Origin of the order
    reason: str = ""  # Why this order is being placed

    # Generated
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validate order request."""
        if not 0.0 < self.price < 1.0:
            raise ValueError(f"Price must be between 0 and 1, got {self.price}")
        if self.size <= 0:
            raise ValueError(f"Size must be positive, got {self.size}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "request_id": self.request_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "side": self.side.value,
            "price": self.price,
            "size": self.size,
            "order_type": self.order_type.value,
            "tick_size": self.tick_size,
            "neg_risk": self.neg_risk,
            "source": self.source,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class OrderResult:
    """
    Result of an order submission attempt.

    This is the output from the execution engine.
    """
    # Request reference
    request_id: str
    request: OrderRequest

    # Result
    status: OrderStatus
    order_id: Optional[str] = None  # Exchange order ID (if submitted)

    # Rejection details (if rejected)
    rejection_reason: Optional[OrderRejectionReason] = None
    rejection_message: Optional[str] = None

    # Execution details (if filled)
    filled_size: float = 0.0
    filled_price: Optional[float] = None
    fill_timestamp: Optional[datetime] = None

    # Mode at time of execution
    execution_mode: ExecutionMode = ExecutionMode.DISABLED

    # Timestamps
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "request_id": self.request_id,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "order_id": self.order_id,
            "rejection_reason": (
                self.rejection_reason.value if self.rejection_reason else None
            ),
            "rejection_message": self.rejection_message,
            "filled_size": self.filled_size,
            "filled_price": self.filled_price,
            "fill_timestamp": (
                self.fill_timestamp.isoformat() if self.fill_timestamp else None
            ),
            "execution_mode": self.execution_mode.value,
            "submitted_at": (
                self.submitted_at.isoformat() if self.submitted_at else None
            ),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
        }


@dataclass
class ExecutionState:
    """
    Persistent state of the execution engine.

    Saved to disk to survive restarts.
    """
    mode: ExecutionMode = ExecutionMode.DISABLED
    last_mode_change: Optional[datetime] = None
    mode_change_reason: str = "startup_default"

    # Arm confirmation state
    arm_pending: bool = False
    arm_challenge: Optional[str] = None
    arm_challenge_expires: Optional[datetime] = None

    # Statistics
    total_orders_submitted: int = 0
    total_orders_filled: int = 0
    total_orders_rejected: int = 0

    # Safety flags
    emergency_disabled: bool = False
    emergency_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "mode": self.mode.value,
            "last_mode_change": (
                self.last_mode_change.isoformat() if self.last_mode_change else None
            ),
            "mode_change_reason": self.mode_change_reason,
            "arm_pending": self.arm_pending,
            "arm_challenge": self.arm_challenge,
            "arm_challenge_expires": (
                self.arm_challenge_expires.isoformat()
                if self.arm_challenge_expires else None
            ),
            "total_orders_submitted": self.total_orders_submitted,
            "total_orders_filled": self.total_orders_filled,
            "total_orders_rejected": self.total_orders_rejected,
            "emergency_disabled": self.emergency_disabled,
            "emergency_reason": self.emergency_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionState":
        """Reconstruct from JSON dict."""
        state = cls()
        state.mode = ExecutionMode(data.get("mode", "DISABLED"))
        if data.get("last_mode_change"):
            state.last_mode_change = datetime.fromisoformat(data["last_mode_change"])
        state.mode_change_reason = data.get("mode_change_reason", "loaded_from_disk")
        state.arm_pending = data.get("arm_pending", False)
        state.arm_challenge = data.get("arm_challenge")
        if data.get("arm_challenge_expires"):
            state.arm_challenge_expires = datetime.fromisoformat(
                data["arm_challenge_expires"]
            )
        state.total_orders_submitted = data.get("total_orders_submitted", 0)
        state.total_orders_filled = data.get("total_orders_filled", 0)
        state.total_orders_rejected = data.get("total_orders_rejected", 0)
        state.emergency_disabled = data.get("emergency_disabled", False)
        state.emergency_reason = data.get("emergency_reason")
        return state


# =============================================================================
# EXECUTION ENGINE
# =============================================================================


class ExecutionEngine:
    """
    Execution Engine - Central order management with multi-layer safety.

    SAFETY HIERARCHY:
    1. Mode check (DISABLED blocks all)
    2. Governance check (NO-GO blocks all)
    3. Kill switch check
    4. API key validation (for LIVE)
    5. Rate limiting
    6. Order validation

    All errors trigger immediate DISABLED transition.
    """

    def __init__(
        self,
        state_file: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ):
        """
        Initialize the Execution Engine.

        IMPORTANT: Always starts in DISABLED mode regardless of saved state.
        """
        self._lock = threading.Lock()
        self._state_file = state_file or STATE_FILE_PATH
        self._log_dir = log_dir or EXECUTION_LOG_PATH

        # Ensure directories exist
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # CRITICAL: Always start DISABLED regardless of any saved state
        self._state = ExecutionState()
        self._state.mode = ExecutionMode.DISABLED
        self._state.last_mode_change = datetime.utcnow()
        self._state.mode_change_reason = "startup_default_disabled"

        # Rate limiting
        self._order_timestamps: List[datetime] = []

        # Order tracking
        self._orders: Dict[str, OrderResult] = {}

        # Paper positions (for PAPER mode)
        self._paper_positions: Dict[str, float] = {}

        # API client (LIVE mode only - lazy initialization)
        # CRITICAL: This is NEVER instantiated unless in LIVE mode
        self._api_client = None

        # Log initialization
        logger.info(
            "ExecutionEngine initialized | "
            f"mode=DISABLED (forced on startup) | "
            f"state_file={self._state_file}"
        )

        # Save initial state
        self._save_state()

    # -------------------------------------------------------------------------
    # STATE MANAGEMENT
    # -------------------------------------------------------------------------

    def _save_state(self):
        """Save state to disk."""
        try:
            with open(self._state_file, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save execution state: {e}")

    def get_mode(self) -> ExecutionMode:
        """Get current execution mode."""
        with self._lock:
            return self._state.mode

    def get_state(self) -> Dict[str, Any]:
        """Get full execution state."""
        with self._lock:
            return self._state.to_dict()

    def _transition_mode(
        self,
        new_mode: ExecutionMode,
        reason: str,
    ) -> bool:
        """
        Transition to a new mode.

        Returns True if transition was successful.
        """
        with self._lock:
            old_mode = self._state.mode

            # Always allow transition to DISABLED
            if new_mode == ExecutionMode.DISABLED:
                self._state.mode = new_mode
                self._state.last_mode_change = datetime.utcnow()
                self._state.mode_change_reason = reason
                self._state.arm_pending = False
                self._state.arm_challenge = None
                self._save_state()
                logger.warning(f"Mode transition: {old_mode.value} → DISABLED | {reason}")
                return True

            # Cannot transition from DISABLED to ARMED/LIVE directly without arm
            # EXCEPTION: "arm_confirmed" reason is allowed (result of 2-step process)
            if old_mode == ExecutionMode.DISABLED:
                if new_mode in [ExecutionMode.ARMED, ExecutionMode.LIVE]:
                    if reason != "arm_confirmed":
                        logger.error(
                            f"Cannot transition directly from DISABLED to {new_mode.value}. "
                            "Must use 2-step arm process."
                        )
                        return False

            # LIVE requires ARMED first
            if new_mode == ExecutionMode.LIVE and old_mode != ExecutionMode.ARMED:
                logger.error(
                    f"Cannot transition to LIVE from {old_mode.value}. "
                    "Must be ARMED first."
                )
                return False

            # LIVE requires env var and API keys
            if new_mode == ExecutionMode.LIVE:
                if not self._check_live_requirements():
                    logger.error("LIVE mode requirements not met.")
                    return False

            self._state.mode = new_mode
            self._state.last_mode_change = datetime.utcnow()
            self._state.mode_change_reason = reason
            self._save_state()

            logger.info(f"Mode transition: {old_mode.value} → {new_mode.value} | {reason}")
            return True

    def _check_live_requirements(self) -> bool:
        """
        Check if LIVE mode requirements are met.

        Requirements:
        1. POLYMARKET_LIVE=1 environment variable
        2. Valid API credentials
        """
        # Check env var
        live_env = os.environ.get(LIVE_MODE_ENV_VAR, "")
        if live_env != LIVE_MODE_ENV_VALUE:
            logger.error(
                f"LIVE mode requires {LIVE_MODE_ENV_VAR}={LIVE_MODE_ENV_VALUE}. "
                f"Current value: '{live_env}'"
            )
            return False

        # Check API keys
        api_key = os.environ.get(API_KEY_ENV_VAR, "")
        api_secret = os.environ.get(API_SECRET_ENV_VAR, "")
        private_key = os.environ.get(PRIVATE_KEY_ENV_VAR, "")

        if not api_key or not api_secret:
            logger.error(
                f"LIVE mode requires {API_KEY_ENV_VAR} and {API_SECRET_ENV_VAR}"
            )
            return False

        if not private_key:
            logger.error(f"LIVE mode requires {PRIVATE_KEY_ENV_VAR}")
            return False

        logger.info("LIVE mode requirements verified")
        return True

    # -------------------------------------------------------------------------
    # MODE CONTROL COMMANDS
    # -------------------------------------------------------------------------

    def disable(self, reason: str = "manual_disable") -> bool:
        """
        Disable the execution engine.

        Always succeeds. This is the safest state.
        """
        return self._transition_mode(ExecutionMode.DISABLED, reason)

    def set_shadow(self) -> bool:
        """
        Set to SHADOW mode.

        Orders are logged but never sent.
        """
        return self._transition_mode(ExecutionMode.SHADOW, "manual_shadow")

    def set_paper(self) -> bool:
        """
        Set to PAPER mode.

        Orders create paper positions but never sent.
        """
        return self._transition_mode(ExecutionMode.PAPER, "manual_paper")

    def initiate_arm(self) -> Optional[str]:
        """
        Initiate the 2-step ARM process.

        Returns a challenge code that must be confirmed within timeout.
        """
        with self._lock:
            # Generate challenge
            challenge = secrets.token_hex(4).upper()
            expires = datetime.utcnow() + timedelta(seconds=ARM_CONFIRMATION_TIMEOUT)

            self._state.arm_pending = True
            self._state.arm_challenge = challenge
            self._state.arm_challenge_expires = expires
            self._save_state()

            logger.warning(
                f"ARM initiated | challenge={challenge} | "
                f"expires_in={ARM_CONFIRMATION_TIMEOUT}s"
            )

            return challenge

    def confirm_arm(self, challenge: str) -> bool:
        """
        Confirm the ARM process with challenge code.

        Returns True if ARM was successful.
        """
        with self._lock:
            # Check if arm is pending
            if not self._state.arm_pending:
                logger.error("No ARM pending. Initiate ARM first.")
                return False

            # Check expiration
            if datetime.utcnow() > self._state.arm_challenge_expires:
                self._state.arm_pending = False
                self._state.arm_challenge = None
                self._save_state()
                logger.error("ARM challenge expired. Initiate again.")
                return False

            # Verify challenge
            if challenge.upper() != self._state.arm_challenge:
                logger.error(
                    f"ARM challenge mismatch. "
                    f"Expected: {self._state.arm_challenge}, Got: {challenge.upper()}"
                )
                return False

            # Clear arm state
            self._state.arm_pending = False
            self._state.arm_challenge = None
            self._state.arm_challenge_expires = None

        # Transition to ARMED
        return self._transition_mode(ExecutionMode.ARMED, "arm_confirmed")

    def go_live(self) -> bool:
        """
        Transition from ARMED to LIVE.

        Requires:
        - Current mode is ARMED
        - POLYMARKET_LIVE=1
        - Valid API credentials
        """
        with self._lock:
            if self._state.mode != ExecutionMode.ARMED:
                logger.error(
                    f"Cannot go LIVE from {self._state.mode.value}. "
                    "Must be ARMED first."
                )
                return False

        return self._transition_mode(ExecutionMode.LIVE, "go_live")

    # -------------------------------------------------------------------------
    # ORDER SUBMISSION
    # -------------------------------------------------------------------------

    def submit_order(self, request: OrderRequest) -> OrderResult:
        """
        Submit an order for execution.

        Behavior depends on current mode:
        - DISABLED: Reject immediately
        - SHADOW: Log only, no execution
        - PAPER: Create paper position
        - ARMED: Validate only, no execution
        - LIVE: Execute via API
        """
        now = datetime.utcnow()

        with self._lock:
            mode = self._state.mode

        # Create result object
        result = OrderResult(
            request_id=request.request_id,
            request=request,
            status=OrderStatus.PENDING,
            execution_mode=mode,
        )

        try:
            # Mode-specific handling
            if mode == ExecutionMode.DISABLED:
                result = self._reject_order(
                    result,
                    OrderRejectionReason.MODE_DISABLED,
                    "Execution engine is DISABLED. No orders accepted."
                )

            elif mode == ExecutionMode.SHADOW:
                result = self._handle_shadow_order(request, result)

            elif mode == ExecutionMode.PAPER:
                result = self._handle_paper_order(request, result)

            elif mode == ExecutionMode.ARMED:
                result = self._handle_armed_order(request, result)

            elif mode == ExecutionMode.LIVE:
                result = self._handle_live_order(request, result)

            else:
                result = self._reject_order(
                    result,
                    OrderRejectionReason.INTERNAL_ERROR,
                    f"Unknown mode: {mode}"
                )

        except Exception as e:
            logger.error(f"Order submission error: {e}")
            result = self._reject_order(
                result,
                OrderRejectionReason.INTERNAL_ERROR,
                str(e)
            )
            # Emergency disable on any error
            self._emergency_disable(f"Order submission error: {e}")

        # Update statistics
        with self._lock:
            self._state.total_orders_submitted += 1
            if result.status == OrderStatus.REJECTED:
                self._state.total_orders_rejected += 1
            elif result.status == OrderStatus.FILLED:
                self._state.total_orders_filled += 1
            self._save_state()

        # Log order
        self._log_order(result)

        # Store order
        self._orders[request.request_id] = result

        return result

    def _reject_order(
        self,
        result: OrderResult,
        reason: OrderRejectionReason,
        message: str,
    ) -> OrderResult:
        """Reject an order with reason."""
        result.status = OrderStatus.REJECTED
        result.rejection_reason = reason
        result.rejection_message = message
        result.completed_at = datetime.utcnow()

        logger.warning(
            f"Order REJECTED | request_id={result.request_id} | "
            f"reason={reason.value} | {message}"
        )

        return result

    def _handle_shadow_order(
        self,
        request: OrderRequest,
        result: OrderResult,
    ) -> OrderResult:
        """Handle order in SHADOW mode - log only."""
        result.status = OrderStatus.SIMULATED
        result.order_id = f"SHADOW_{request.request_id[:8]}"
        result.submitted_at = datetime.utcnow()
        result.completed_at = datetime.utcnow()

        logger.info(
            f"SHADOW order logged | request_id={request.request_id} | "
            f"market={request.market_id} | {request.side.value} {request.size}@{request.price}"
        )

        return result

    def _handle_paper_order(
        self,
        request: OrderRequest,
        result: OrderResult,
    ) -> OrderResult:
        """Handle order in PAPER mode - create paper position."""
        result.status = OrderStatus.FILLED
        result.order_id = f"PAPER_{request.request_id[:8]}"
        result.submitted_at = datetime.utcnow()
        result.completed_at = datetime.utcnow()
        result.filled_size = request.size
        result.filled_price = request.price
        result.fill_timestamp = datetime.utcnow()

        # Update paper position
        position_key = f"{request.market_id}_{request.token_id}"
        with self._lock:
            current_position = self._paper_positions.get(position_key, 0.0)
            if request.side == OrderSide.BUY:
                self._paper_positions[position_key] = current_position + request.size
            else:
                self._paper_positions[position_key] = current_position - request.size

        logger.info(
            f"PAPER order filled | request_id={request.request_id} | "
            f"market={request.market_id} | {request.side.value} {request.size}@{request.price}"
        )

        return result

    def _handle_armed_order(
        self,
        request: OrderRequest,
        result: OrderResult,
    ) -> OrderResult:
        """Handle order in ARMED mode - validate only."""
        # Validate order would be accepted
        validation_errors = self._validate_order(request)

        if validation_errors:
            return self._reject_order(
                result,
                OrderRejectionReason.INVALID_PARAMETERS,
                "; ".join(validation_errors)
            )

        result.status = OrderStatus.SIMULATED
        result.order_id = f"ARMED_{request.request_id[:8]}"
        result.submitted_at = datetime.utcnow()
        result.completed_at = datetime.utcnow()

        logger.info(
            f"ARMED order validated | request_id={request.request_id} | "
            f"market={request.market_id} | {request.side.value} {request.size}@{request.price} | "
            "Would be submitted in LIVE mode"
        )

        return result

    def _handle_live_order(
        self,
        request: OrderRequest,
        result: OrderResult,
    ) -> OrderResult:
        """Handle order in LIVE mode - execute via API."""
        # Rate limiting
        if not self._check_rate_limit():
            return self._reject_order(
                result,
                OrderRejectionReason.RATE_LIMITED,
                f"Rate limit exceeded. Max {MAX_ORDERS_PER_MINUTE} orders/minute."
            )

        # Validate order
        validation_errors = self._validate_order(request)
        if validation_errors:
            return self._reject_order(
                result,
                OrderRejectionReason.INVALID_PARAMETERS,
                "; ".join(validation_errors)
            )

        # Submit to API
        try:
            result = self._submit_to_api(request, result)
        except Exception as e:
            logger.error(f"API submission failed: {e}")
            result = self._reject_order(
                result,
                OrderRejectionReason.API_ERROR,
                str(e)
            )
            # Emergency disable on API error
            self._emergency_disable(f"API error: {e}")

        return result

    def _get_api_client(self):
        """
        Get or create the API client.

        CRITICAL: This is ONLY called in LIVE mode.
        The client is lazily initialized to prevent any API interaction
        in DISABLED, SHADOW, PAPER, or ARMED modes.

        Raises:
            ValueError: If credentials are missing.
            Exception: If client initialization fails.
        """
        if self._api_client is not None:
            return self._api_client

        # Verify we're in LIVE mode (defensive check)
        with self._lock:
            if self._state.mode != ExecutionMode.LIVE:
                raise RuntimeError(
                    f"API client requested in {self._state.mode.value} mode. "
                    "This should NEVER happen."
                )

        # Import API client module lazily
        global _api_client_module
        if _api_client_module is None:
            try:
                from core import polymarket_api_client
                _api_client_module = polymarket_api_client
            except ImportError as e:
                raise RuntimeError(f"Failed to import polymarket_api_client: {e}")

        # Create client - this validates credentials
        logger.info("Initializing Polymarket API client for LIVE trading")
        self._api_client = _api_client_module.create_api_client()
        logger.warning("Polymarket API client initialized - LIVE TRADING ENABLED")

        return self._api_client

    def _submit_to_api(
        self,
        request: OrderRequest,
        result: OrderResult,
    ) -> OrderResult:
        """
        Submit order to Polymarket API.

        LIVE MODE ONLY.

        FAIL-CLOSED: Any error results in rejection and emergency disable.
        NO RETRIES: If it fails, it fails.
        """
        # Defensive mode check - should never fail but defense in depth
        with self._lock:
            if self._state.mode != ExecutionMode.LIVE:
                logger.critical(
                    f"_submit_to_api called in {self._state.mode.value} mode! "
                    "This is a critical bug."
                )
                return self._reject_order(
                    result,
                    OrderRejectionReason.MODE_NOT_LIVE,
                    f"API submission blocked - not in LIVE mode"
                )

        try:
            # Get API client (lazy initialization)
            client = self._get_api_client()

            # Import API client types
            from core.polymarket_api_client import OrderPayload, ApiResultStatus

            # Create order payload
            payload = OrderPayload(
                token_id=request.token_id,
                price=request.price,
                size=request.size,
                side=request.side.value,
                order_type=request.order_type.value,
                tick_size=request.tick_size,
                neg_risk=request.neg_risk,
            )

            logger.critical(
                f"LIVE order submission | request_id={request.request_id} | "
                f"market={request.market_id} | {request.side.value} {request.size}@{request.price}"
            )

            # Submit to API
            api_response = client.submit_order(payload)

            result.submitted_at = datetime.utcnow()

            # Map API response to OrderResult
            if api_response.success:
                result.status = OrderStatus.SUBMITTED
                result.order_id = api_response.order_id
                result.completed_at = datetime.utcnow()

                # Check if we got fill info
                if api_response.filled_size is not None:
                    result.filled_size = api_response.filled_size
                if api_response.average_price is not None:
                    result.filled_price = api_response.average_price

                logger.info(
                    f"LIVE order submitted | order_id={result.order_id} | "
                    f"request_id={request.request_id}"
                )

                return result

            else:
                # API rejected the order
                error_msg = api_response.error_message or "Unknown API error"
                error_code = api_response.error_code or "UNKNOWN"

                logger.error(
                    f"LIVE order rejected by API | request_id={request.request_id} | "
                    f"error={error_code}: {error_msg}"
                )

                # Map API status to rejection reason
                if api_response.status == ApiResultStatus.AUTH_ERROR:
                    reason = OrderRejectionReason.MISSING_API_KEYS
                elif api_response.status == ApiResultStatus.RATE_LIMITED:
                    reason = OrderRejectionReason.RATE_LIMITED
                elif api_response.status == ApiResultStatus.REJECTED:
                    reason = OrderRejectionReason.INVALID_PARAMETERS
                else:
                    reason = OrderRejectionReason.API_ERROR

                return self._reject_order(result, reason, f"{error_code}: {error_msg}")

        except ValueError as e:
            # Validation error in payload creation
            logger.error(f"Order payload validation failed: {e}")
            return self._reject_order(
                result,
                OrderRejectionReason.INVALID_PARAMETERS,
                f"Payload validation: {e}"
            )

        except RuntimeError as e:
            # Client initialization or mode error
            logger.critical(f"API client error: {e}")
            self._emergency_disable(f"API client error: {e}")
            return self._reject_order(
                result,
                OrderRejectionReason.API_ERROR,
                str(e)
            )

        except Exception as e:
            # Any unexpected error - emergency disable
            logger.critical(f"Unexpected error during API submission: {e}")
            self._emergency_disable(f"Unexpected API error: {e}")
            return self._reject_order(
                result,
                OrderRejectionReason.INTERNAL_ERROR,
                f"Unexpected error: {e}"
            )

    def _validate_order(self, request: OrderRequest) -> List[str]:
        """Validate order parameters. Returns list of errors."""
        errors = []

        if not request.market_id:
            errors.append("market_id is required")

        if not request.token_id:
            errors.append("token_id is required")

        if request.price <= 0 or request.price >= 1:
            errors.append(f"price must be between 0 and 1, got {request.price}")

        if request.size <= 0:
            errors.append(f"size must be positive, got {request.size}")

        return errors

    def _check_rate_limit(self) -> bool:
        """Check if order is within rate limit."""
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=1)

        with self._lock:
            # Clean old timestamps
            self._order_timestamps = [
                ts for ts in self._order_timestamps if ts > cutoff
            ]

            # Check limit
            if len(self._order_timestamps) >= MAX_ORDERS_PER_MINUTE:
                return False

            # Add current timestamp
            self._order_timestamps.append(now)
            return True

    def _emergency_disable(self, reason: str):
        """Emergency disable on error."""
        with self._lock:
            self._state.mode = ExecutionMode.DISABLED
            self._state.emergency_disabled = True
            self._state.emergency_reason = reason
            self._state.last_mode_change = datetime.utcnow()
            self._state.mode_change_reason = f"emergency_disable: {reason}"
            self._save_state()

        logger.critical(f"EMERGENCY DISABLE | {reason}")

    # -------------------------------------------------------------------------
    # ORDER MANAGEMENT
    # -------------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.

        Returns True if cancellation was successful.
        """
        # Find order by order_id
        result = None
        for r in self._orders.values():
            if r.order_id == order_id:
                result = r
                break

        if not result:
            logger.warning(f"Order not found for cancellation: {order_id}")
            return False

        # Can only cancel open orders
        if result.status not in [OrderStatus.OPEN, OrderStatus.PENDING, OrderStatus.SUBMITTED]:
            logger.warning(f"Cannot cancel order in status {result.status.value}")
            return False

        # In LIVE mode, call API to cancel
        mode = self.get_mode()
        if mode == ExecutionMode.LIVE:
            try:
                client = self._get_api_client()
                api_response = client.cancel_order(order_id)

                if not api_response.success:
                    logger.error(
                        f"LIVE cancel failed | order_id={order_id} | "
                        f"error={api_response.error_message}"
                    )
                    # Don't emergency disable for cancel failures
                    return False

                logger.info(f"LIVE order cancelled via API | order_id={order_id}")

            except Exception as e:
                logger.error(f"Cancel API error: {e}")
                # Emergency disable on any API error
                self._emergency_disable(f"Cancel API error: {e}")
                return False

        result.status = OrderStatus.CANCELLED
        result.completed_at = datetime.utcnow()

        logger.info(f"Order cancelled | order_id={order_id}")
        return True

    def get_order_status(self, request_id: str) -> Optional[OrderResult]:
        """Get status of an order by request ID."""
        return self._orders.get(request_id)

    def get_open_orders(self) -> List[OrderResult]:
        """Get all open orders."""
        return [
            r for r in self._orders.values()
            if r.status in [OrderStatus.OPEN, OrderStatus.PENDING, OrderStatus.SUBMITTED]
        ]

    def get_paper_positions(self) -> Dict[str, float]:
        """Get paper positions (PAPER mode only)."""
        with self._lock:
            return dict(self._paper_positions)

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def _log_order(self, result: OrderResult):
        """Log order to execution log."""
        try:
            log_file = self._log_dir / f"orders_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to log order: {e}")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

# Global execution engine instance
_engine_instance: Optional[ExecutionEngine] = None
_engine_lock = threading.Lock()


def get_execution_engine() -> ExecutionEngine:
    """
    Get the global execution engine instance.

    Creates if not exists. Always returns same instance.
    """
    global _engine_instance

    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = ExecutionEngine()
        return _engine_instance


def reset_execution_engine():
    """
    Reset the global execution engine.

    For testing only. Creates a new DISABLED instance.
    """
    global _engine_instance

    with _engine_lock:
        _engine_instance = ExecutionEngine()
        logger.warning("Execution engine reset to DISABLED")
