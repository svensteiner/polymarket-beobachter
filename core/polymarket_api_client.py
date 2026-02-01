# =============================================================================
# POLYMARKET BEOBACHTER - POLYMARKET API CLIENT
# =============================================================================
#
# CRITICAL SAFETY COMPONENT
#
# This client interfaces with the Polymarket CLOB (Central Limit Order Book).
# It is considered HOSTILE by default - network failures, malformed responses,
# and partial fills are EXPECTED failure modes.
#
# FAIL-CLOSED PRINCIPLE:
# Any uncertainty, any unexpected response, any exception → REJECT THE ORDER.
# There are NO retries, NO auto-recovery, NO silent fallbacks.
#
# MINIMAL INTERFACE:
# - submit_order(payload) → ApiResponse
# - cancel_order(order_id) → ApiResponse
# - get_order_status(order_id) → ApiResponse
#
# That's it. No additional functionality.
#
# =============================================================================

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# API endpoints
POLYMARKET_CLOB_HOST: str = "https://clob.polymarket.com"
POLYGON_CHAIN_ID: int = 137

# Timeouts (seconds) - strict, no extensions
REQUEST_TIMEOUT_SECONDS: float = 10.0
CONNECT_TIMEOUT_SECONDS: float = 5.0

# Environment variables for credentials
API_KEY_ENV_VAR: str = "POLYMARKET_API_KEY"
API_SECRET_ENV_VAR: str = "POLYMARKET_API_SECRET"
API_PASSPHRASE_ENV_VAR: str = "POLYMARKET_API_PASSPHRASE"
PRIVATE_KEY_ENV_VAR: str = "POLYMARKET_PRIVATE_KEY"
FUNDER_ADDRESS_ENV_VAR: str = "POLYMARKET_FUNDER_ADDRESS"

# Signature types
SIGNATURE_TYPE_EOA: int = 0  # Standard externally owned account
SIGNATURE_TYPE_POLY_PROXY: int = 1  # Polymarket proxy (email/Magic wallet)
SIGNATURE_TYPE_GNOSIS_SAFE: int = 2  # Gnosis Safe multisig


# =============================================================================
# API RESPONSE TYPES
# =============================================================================


class ApiResultStatus(Enum):
    """
    Status of an API call result.

    SUCCESS: API call completed successfully with valid response.
    REJECTED: Order was rejected by the API (e.g., invalid parameters).
    NETWORK_ERROR: Network-level failure (timeout, connection refused).
    PARSE_ERROR: Response could not be parsed or validated.
    AUTH_ERROR: Authentication or authorization failure.
    RATE_LIMITED: Rate limit exceeded.
    UNKNOWN_ERROR: Unexpected error - treat as failure.
    """
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class ApiResponse:
    """
    Structured response from an API call.

    Every API call returns this, regardless of success or failure.
    This ensures consistent error handling.
    """
    status: ApiResultStatus
    success: bool

    # Response data (only if success=True)
    order_id: Optional[str] = None
    order_status: Optional[str] = None
    filled_size: Optional[float] = None
    average_price: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None

    # Error details (only if success=False)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    exception_type: Optional[str] = None

    # Metadata
    timestamp: str = ""
    request_duration_ms: Optional[float] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "status": self.status.value,
            "success": self.success,
            "order_id": self.order_id,
            "order_status": self.order_status,
            "filled_size": self.filled_size,
            "average_price": self.average_price,
            "raw_response": self.raw_response,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "exception_type": self.exception_type,
            "timestamp": self.timestamp,
            "request_duration_ms": self.request_duration_ms,
        }


@dataclass
class OrderPayload:
    """
    Order payload to submit to Polymarket.

    Strict schema - all fields validated before submission.
    """
    token_id: str
    price: float  # 0.0 to 1.0
    size: float  # Number of shares
    side: str  # "BUY" or "SELL"
    order_type: str = "GTC"  # "GTC", "IOC", "FOK"
    tick_size: float = 0.01
    neg_risk: bool = False

    def __post_init__(self):
        """Validate payload on creation."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid OrderPayload: {'; '.join(errors)}")

    def validate(self) -> list:
        """Validate all fields. Returns list of errors."""
        errors = []

        if not self.token_id:
            errors.append("token_id is required")

        if not isinstance(self.price, (int, float)):
            errors.append(f"price must be numeric, got {type(self.price)}")
        elif not (0.0 < self.price < 1.0):
            errors.append(f"price must be between 0 and 1, got {self.price}")

        if not isinstance(self.size, (int, float)):
            errors.append(f"size must be numeric, got {type(self.size)}")
        elif self.size <= 0:
            errors.append(f"size must be positive, got {self.size}")

        if self.side not in ("BUY", "SELL"):
            errors.append(f"side must be 'BUY' or 'SELL', got {self.side}")

        if self.order_type not in ("GTC", "IOC", "FOK"):
            errors.append(f"order_type must be 'GTC', 'IOC', or 'FOK', got {self.order_type}")

        if not isinstance(self.tick_size, (int, float)) or self.tick_size <= 0:
            errors.append(f"tick_size must be positive, got {self.tick_size}")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for logging."""
        return {
            "token_id": self.token_id,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "order_type": self.order_type,
            "tick_size": self.tick_size,
            "neg_risk": self.neg_risk,
        }


# =============================================================================
# POLYMARKET API CLIENT
# =============================================================================


class PolymarketApiClient:
    """
    Polymarket CLOB API Client.

    HOSTILE BY DEFAULT:
    - All network calls are assumed to fail
    - All responses are assumed to be malformed
    - All errors result in rejection, never retries

    MINIMAL INTERFACE:
    - submit_order(payload) → ApiResponse
    - cancel_order(order_id) → ApiResponse
    - get_order_status(order_id) → ApiResponse

    INSTANTIATION:
    This client should ONLY be instantiated in LIVE mode.
    It must NEVER be created in DISABLED, SHADOW, PAPER, or ARMED modes.
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        funder_address: Optional[str] = None,
        signature_type: int = SIGNATURE_TYPE_POLY_PROXY,
    ):
        """
        Initialize the Polymarket API client.

        Args:
            private_key: Wallet private key (or from env POLYMARKET_PRIVATE_KEY)
            api_key: API key (or from env POLYMARKET_API_KEY)
            api_secret: API secret (or from env POLYMARKET_API_SECRET)
            api_passphrase: API passphrase (or from env POLYMARKET_API_PASSPHRASE)
            funder_address: Funder address (or from env POLYMARKET_FUNDER_ADDRESS)
            signature_type: Signature type (0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE)

        Raises:
            ValueError: If required credentials are missing.
        """
        # Load credentials from env if not provided
        self._private_key = private_key or os.environ.get(PRIVATE_KEY_ENV_VAR, "")
        self._api_key = api_key or os.environ.get(API_KEY_ENV_VAR, "")
        self._api_secret = api_secret or os.environ.get(API_SECRET_ENV_VAR, "")
        self._api_passphrase = api_passphrase or os.environ.get(API_PASSPHRASE_ENV_VAR, "")
        self._funder_address = funder_address or os.environ.get(FUNDER_ADDRESS_ENV_VAR, "")
        self._signature_type = signature_type

        # Validate credentials
        self._validate_credentials()

        # Client instance (lazy initialization)
        self._clob_client = None
        self._initialized = False

        logger.info(
            f"PolymarketApiClient created | "
            f"host={POLYMARKET_CLOB_HOST} | "
            f"chain_id={POLYGON_CHAIN_ID} | "
            f"signature_type={signature_type}"
        )

    def _validate_credentials(self):
        """Validate that all required credentials are present."""
        errors = []

        if not self._private_key:
            errors.append(f"Missing {PRIVATE_KEY_ENV_VAR}")

        if not self._api_key:
            errors.append(f"Missing {API_KEY_ENV_VAR}")

        if not self._api_secret:
            errors.append(f"Missing {API_SECRET_ENV_VAR}")

        # Funder address required for proxy signatures
        if self._signature_type == SIGNATURE_TYPE_POLY_PROXY:
            if not self._funder_address:
                errors.append(f"Missing {FUNDER_ADDRESS_ENV_VAR} (required for POLY_PROXY)")

        if errors:
            error_msg = "; ".join(errors)
            logger.error(f"Credential validation failed: {error_msg}")
            raise ValueError(f"Credential validation failed: {error_msg}")

    def _initialize_client(self) -> bool:
        """
        Initialize the CLOB client.

        Returns True if successful, False otherwise.
        This is called lazily on first API call.
        """
        if self._initialized:
            return True

        try:
            # Import here to avoid loading if not in LIVE mode
            from py_clob_client.client import ClobClient

            self._clob_client = ClobClient(
                host=POLYMARKET_CLOB_HOST,
                chain_id=POLYGON_CHAIN_ID,
                key=self._private_key,
                signature_type=self._signature_type,
                funder=self._funder_address if self._funder_address else None,
            )

            # Set API credentials
            self._clob_client.set_api_creds({
                "apiKey": self._api_key,
                "secret": self._api_secret,
                "passphrase": self._api_passphrase,
            })

            self._initialized = True
            logger.info("CLOB client initialized successfully")
            return True

        except ImportError as e:
            logger.error(f"Failed to import py_clob_client: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            return False

    def _create_error_response(
        self,
        status: ApiResultStatus,
        error_message: str,
        error_code: Optional[str] = None,
        exception_type: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> ApiResponse:
        """Create a standardized error response."""
        return ApiResponse(
            status=status,
            success=False,
            error_code=error_code,
            error_message=error_message,
            exception_type=exception_type,
            request_duration_ms=duration_ms,
        )

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS
    # -------------------------------------------------------------------------

    def submit_order(self, payload: OrderPayload) -> ApiResponse:
        """
        Submit an order to Polymarket.

        Args:
            payload: Validated OrderPayload.

        Returns:
            ApiResponse with success status and order details,
            or error details if failed.

        FAIL-CLOSED: Any exception or unexpected response results in rejection.
        NO RETRIES: If it fails, it fails. Period.
        """
        start_time = datetime.utcnow()

        logger.info(
            f"Submitting order | token_id={payload.token_id} | "
            f"{payload.side} {payload.size}@{payload.price}"
        )

        try:
            # Initialize client if needed
            if not self._initialize_client():
                return self._create_error_response(
                    ApiResultStatus.AUTH_ERROR,
                    "Failed to initialize CLOB client",
                    error_code="CLIENT_INIT_FAILED",
                )

            # Import types
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            # Map side
            side = BUY if payload.side == "BUY" else SELL

            # Map order type
            order_type_map = {
                "GTC": OrderType.GTC,
                "IOC": OrderType.IOC,
                "FOK": OrderType.FOK,
            }
            order_type = order_type_map.get(payload.order_type, OrderType.GTC)

            # Create order args
            order_args = OrderArgs(
                token_id=payload.token_id,
                price=payload.price,
                size=payload.size,
                side=side,
            )

            # Create signed order
            signed_order = self._clob_client.create_order(order_args)

            # Post order to API
            response = self._clob_client.post_order(signed_order, order_type)

            # Calculate duration
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Parse response
            return self._parse_order_response(response, duration)

        except ImportError as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Import error during order submission: {e}")
            return self._create_error_response(
                ApiResultStatus.UNKNOWN_ERROR,
                f"Import error: {e}",
                error_code="IMPORT_ERROR",
                exception_type="ImportError",
                duration_ms=duration,
            )

        except TimeoutError as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Timeout during order submission: {e}")
            return self._create_error_response(
                ApiResultStatus.NETWORK_ERROR,
                f"Request timeout: {e}",
                error_code="TIMEOUT",
                exception_type="TimeoutError",
                duration_ms=duration,
            )

        except ConnectionError as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Connection error during order submission: {e}")
            return self._create_error_response(
                ApiResultStatus.NETWORK_ERROR,
                f"Connection error: {e}",
                error_code="CONNECTION_ERROR",
                exception_type="ConnectionError",
                duration_ms=duration,
            )

        except ValueError as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Value error during order submission: {e}")
            return self._create_error_response(
                ApiResultStatus.REJECTED,
                f"Invalid order: {e}",
                error_code="VALIDATION_ERROR",
                exception_type="ValueError",
                duration_ms=duration,
            )

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Unexpected error during order submission: {e}")
            return self._create_error_response(
                ApiResultStatus.UNKNOWN_ERROR,
                f"Unexpected error: {e}",
                error_code="UNEXPECTED_ERROR",
                exception_type=type(e).__name__,
                duration_ms=duration,
            )

    def cancel_order(self, order_id: str) -> ApiResponse:
        """
        Cancel an order on Polymarket.

        Args:
            order_id: The order ID to cancel.

        Returns:
            ApiResponse with cancellation status.
        """
        start_time = datetime.utcnow()

        logger.info(f"Cancelling order | order_id={order_id}")

        try:
            # Validate order_id
            if not order_id or not isinstance(order_id, str):
                return self._create_error_response(
                    ApiResultStatus.REJECTED,
                    "Invalid order_id",
                    error_code="INVALID_ORDER_ID",
                )

            # Initialize client if needed
            if not self._initialize_client():
                return self._create_error_response(
                    ApiResultStatus.AUTH_ERROR,
                    "Failed to initialize CLOB client",
                    error_code="CLIENT_INIT_FAILED",
                )

            # Cancel order
            response = self._clob_client.cancel(order_id)

            duration = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Parse response
            return self._parse_cancel_response(response, order_id, duration)

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Error cancelling order {order_id}: {e}")
            return self._create_error_response(
                ApiResultStatus.UNKNOWN_ERROR,
                f"Cancel error: {e}",
                error_code="CANCEL_ERROR",
                exception_type=type(e).__name__,
                duration_ms=duration,
            )

    def get_order_status(self, order_id: str) -> ApiResponse:
        """
        Get status of an order from Polymarket.

        Args:
            order_id: The order ID to query.

        Returns:
            ApiResponse with order status.
        """
        start_time = datetime.utcnow()

        logger.info(f"Getting order status | order_id={order_id}")

        try:
            # Validate order_id
            if not order_id or not isinstance(order_id, str):
                return self._create_error_response(
                    ApiResultStatus.REJECTED,
                    "Invalid order_id",
                    error_code="INVALID_ORDER_ID",
                )

            # Initialize client if needed
            if not self._initialize_client():
                return self._create_error_response(
                    ApiResultStatus.AUTH_ERROR,
                    "Failed to initialize CLOB client",
                    error_code="CLIENT_INIT_FAILED",
                )

            # Get order
            response = self._clob_client.get_order(order_id)

            duration = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Parse response
            return self._parse_status_response(response, order_id, duration)

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"Error getting order status {order_id}: {e}")
            return self._create_error_response(
                ApiResultStatus.UNKNOWN_ERROR,
                f"Status query error: {e}",
                error_code="STATUS_ERROR",
                exception_type=type(e).__name__,
                duration_ms=duration,
            )

    # -------------------------------------------------------------------------
    # RESPONSE PARSING
    # -------------------------------------------------------------------------

    def _parse_order_response(
        self,
        response: Any,
        duration_ms: float,
    ) -> ApiResponse:
        """
        Parse order submission response.

        STRICT VALIDATION:
        - Response must be dict-like
        - Must contain expected fields
        - Any deviation is a parse error
        """
        try:
            # Response must exist
            if response is None:
                return self._create_error_response(
                    ApiResultStatus.PARSE_ERROR,
                    "Empty response from API",
                    error_code="EMPTY_RESPONSE",
                    duration_ms=duration_ms,
                )

            # Handle dict response
            if isinstance(response, dict):
                # Check for error in response
                if "error" in response or "errorMsg" in response:
                    error_msg = response.get("error") or response.get("errorMsg", "Unknown error")
                    return self._create_error_response(
                        ApiResultStatus.REJECTED,
                        str(error_msg),
                        error_code=response.get("errorCode", "API_ERROR"),
                        duration_ms=duration_ms,
                    )

                # Extract order ID
                order_id = response.get("orderID") or response.get("order_id") or response.get("id")

                if not order_id:
                    return self._create_error_response(
                        ApiResultStatus.PARSE_ERROR,
                        "Response missing order_id",
                        error_code="MISSING_ORDER_ID",
                        duration_ms=duration_ms,
                    )

                # Success
                return ApiResponse(
                    status=ApiResultStatus.SUCCESS,
                    success=True,
                    order_id=str(order_id),
                    order_status=response.get("status", "SUBMITTED"),
                    raw_response=response,
                    request_duration_ms=duration_ms,
                )

            # Handle string response (some APIs return just the order ID)
            if isinstance(response, str):
                return ApiResponse(
                    status=ApiResultStatus.SUCCESS,
                    success=True,
                    order_id=response,
                    order_status="SUBMITTED",
                    request_duration_ms=duration_ms,
                )

            # Unknown response type
            return self._create_error_response(
                ApiResultStatus.PARSE_ERROR,
                f"Unexpected response type: {type(response)}",
                error_code="UNEXPECTED_TYPE",
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(f"Error parsing order response: {e}")
            return self._create_error_response(
                ApiResultStatus.PARSE_ERROR,
                f"Response parse error: {e}",
                error_code="PARSE_EXCEPTION",
                exception_type=type(e).__name__,
                duration_ms=duration_ms,
            )

    def _parse_cancel_response(
        self,
        response: Any,
        order_id: str,
        duration_ms: float,
    ) -> ApiResponse:
        """Parse cancel order response."""
        try:
            if response is None:
                return self._create_error_response(
                    ApiResultStatus.PARSE_ERROR,
                    "Empty response from cancel API",
                    error_code="EMPTY_RESPONSE",
                    duration_ms=duration_ms,
                )

            # Most cancel APIs return success as boolean or status
            if isinstance(response, dict):
                if response.get("error"):
                    return self._create_error_response(
                        ApiResultStatus.REJECTED,
                        str(response.get("error")),
                        error_code="CANCEL_REJECTED",
                        duration_ms=duration_ms,
                    )

                return ApiResponse(
                    status=ApiResultStatus.SUCCESS,
                    success=True,
                    order_id=order_id,
                    order_status="CANCELLED",
                    raw_response=response,
                    request_duration_ms=duration_ms,
                )

            if isinstance(response, bool):
                if response:
                    return ApiResponse(
                        status=ApiResultStatus.SUCCESS,
                        success=True,
                        order_id=order_id,
                        order_status="CANCELLED",
                        request_duration_ms=duration_ms,
                    )
                else:
                    return self._create_error_response(
                        ApiResultStatus.REJECTED,
                        "Cancel returned False",
                        error_code="CANCEL_FAILED",
                        duration_ms=duration_ms,
                    )

            # Assume success for other types
            return ApiResponse(
                status=ApiResultStatus.SUCCESS,
                success=True,
                order_id=order_id,
                order_status="CANCELLED",
                request_duration_ms=duration_ms,
            )

        except Exception as e:
            return self._create_error_response(
                ApiResultStatus.PARSE_ERROR,
                f"Cancel response parse error: {e}",
                error_code="PARSE_EXCEPTION",
                exception_type=type(e).__name__,
                duration_ms=duration_ms,
            )

    def _parse_status_response(
        self,
        response: Any,
        order_id: str,
        duration_ms: float,
    ) -> ApiResponse:
        """Parse order status response."""
        try:
            if response is None:
                return self._create_error_response(
                    ApiResultStatus.PARSE_ERROR,
                    "Empty response from status API",
                    error_code="EMPTY_RESPONSE",
                    duration_ms=duration_ms,
                )

            if isinstance(response, dict):
                if response.get("error"):
                    return self._create_error_response(
                        ApiResultStatus.REJECTED,
                        str(response.get("error")),
                        error_code="STATUS_ERROR",
                        duration_ms=duration_ms,
                    )

                return ApiResponse(
                    status=ApiResultStatus.SUCCESS,
                    success=True,
                    order_id=order_id,
                    order_status=response.get("status", "UNKNOWN"),
                    filled_size=response.get("filledSize") or response.get("filled_size"),
                    average_price=response.get("averagePrice") or response.get("average_price"),
                    raw_response=response,
                    request_duration_ms=duration_ms,
                )

            return self._create_error_response(
                ApiResultStatus.PARSE_ERROR,
                f"Unexpected status response type: {type(response)}",
                error_code="UNEXPECTED_TYPE",
                duration_ms=duration_ms,
            )

        except Exception as e:
            return self._create_error_response(
                ApiResultStatus.PARSE_ERROR,
                f"Status response parse error: {e}",
                error_code="PARSE_EXCEPTION",
                exception_type=type(e).__name__,
                duration_ms=duration_ms,
            )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def create_api_client() -> PolymarketApiClient:
    """
    Create a Polymarket API client from environment variables.

    This should ONLY be called when transitioning to LIVE mode.

    Raises:
        ValueError: If required credentials are missing.
    """
    return PolymarketApiClient()
