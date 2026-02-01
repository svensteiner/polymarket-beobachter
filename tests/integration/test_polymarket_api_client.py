# =============================================================================
# POLYMARKET BEOBACHTER - API CLIENT UNIT TESTS
# =============================================================================
#
# Tests for the Polymarket API client with strict fail-closed behavior.
#
# Test categories:
# 1. OrderPayload validation
# 2. ApiResponse creation
# 3. Credential validation
# 4. Error handling (mocked API calls)
#
# =============================================================================

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.polymarket_api_client import (
    OrderPayload,
    ApiResponse,
    ApiResultStatus,
    PolymarketApiClient,
    create_api_client,
    API_KEY_ENV_VAR,
    API_SECRET_ENV_VAR,
    API_PASSPHRASE_ENV_VAR,
    PRIVATE_KEY_ENV_VAR,
    FUNDER_ADDRESS_ENV_VAR,
    SIGNATURE_TYPE_POLY_PROXY,
    SIGNATURE_TYPE_EOA,
)


# =============================================================================
# ORDER PAYLOAD VALIDATION TESTS
# =============================================================================


class TestOrderPayloadValidation:
    """Test OrderPayload validation - strict fail-closed."""

    def test_valid_payload_creation(self):
        """Valid payload should be created without errors."""
        payload = OrderPayload(
            token_id="12345678901234567890123456789012345678901234567890123456789012345678",
            price=0.5,
            size=100.0,
            side="BUY",
        )

        assert payload.token_id is not None
        assert payload.price == 0.5
        assert payload.size == 100.0
        assert payload.side == "BUY"
        assert payload.order_type == "GTC"

    def test_valid_sell_order(self):
        """SELL side should be valid."""
        payload = OrderPayload(
            token_id="test_token",
            price=0.75,
            size=50.0,
            side="SELL",
        )

        assert payload.side == "SELL"

    def test_valid_order_types(self):
        """All order types should be valid."""
        for order_type in ["GTC", "IOC", "FOK"]:
            payload = OrderPayload(
                token_id="test_token",
                price=0.5,
                size=100.0,
                side="BUY",
                order_type=order_type,
            )
            assert payload.order_type == order_type

    def test_invalid_price_zero(self):
        """Price of 0 should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=0.0,
                size=100.0,
                side="BUY",
            )
        assert "price must be between 0 and 1" in str(exc_info.value)

    def test_invalid_price_one(self):
        """Price of 1 should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=1.0,
                size=100.0,
                side="BUY",
            )
        assert "price must be between 0 and 1" in str(exc_info.value)

    def test_invalid_price_negative(self):
        """Negative price should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=-0.5,
                size=100.0,
                side="BUY",
            )
        assert "price must be between 0 and 1" in str(exc_info.value)

    def test_invalid_price_above_one(self):
        """Price above 1 should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=1.5,
                size=100.0,
                side="BUY",
            )
        assert "price must be between 0 and 1" in str(exc_info.value)

    def test_invalid_size_zero(self):
        """Size of 0 should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=0.5,
                size=0.0,
                side="BUY",
            )
        assert "size must be positive" in str(exc_info.value)

    def test_invalid_size_negative(self):
        """Negative size should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=0.5,
                size=-100.0,
                side="BUY",
            )
        assert "size must be positive" in str(exc_info.value)

    def test_invalid_side(self):
        """Invalid side should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=0.5,
                size=100.0,
                side="INVALID",
            )
        assert "side must be 'BUY' or 'SELL'" in str(exc_info.value)

    def test_invalid_order_type(self):
        """Invalid order type should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="test_token",
                price=0.5,
                size=100.0,
                side="BUY",
                order_type="INVALID",
            )
        assert "order_type must be" in str(exc_info.value)

    def test_empty_token_id(self):
        """Empty token_id should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OrderPayload(
                token_id="",
                price=0.5,
                size=100.0,
                side="BUY",
            )
        assert "token_id is required" in str(exc_info.value)

    def test_payload_to_dict(self):
        """to_dict should return all fields."""
        payload = OrderPayload(
            token_id="test_token",
            price=0.5,
            size=100.0,
            side="BUY",
            order_type="IOC",
            tick_size=0.001,
            neg_risk=True,
        )

        d = payload.to_dict()
        assert d["token_id"] == "test_token"
        assert d["price"] == 0.5
        assert d["size"] == 100.0
        assert d["side"] == "BUY"
        assert d["order_type"] == "IOC"
        assert d["tick_size"] == 0.001
        assert d["neg_risk"] is True


# =============================================================================
# API RESPONSE TESTS
# =============================================================================


class TestApiResponse:
    """Test ApiResponse data class."""

    def test_success_response(self):
        """Success response should have correct fields."""
        response = ApiResponse(
            status=ApiResultStatus.SUCCESS,
            success=True,
            order_id="order123",
            order_status="SUBMITTED",
        )

        assert response.success is True
        assert response.status == ApiResultStatus.SUCCESS
        assert response.order_id == "order123"
        assert response.timestamp is not None

    def test_error_response(self):
        """Error response should have error fields."""
        response = ApiResponse(
            status=ApiResultStatus.NETWORK_ERROR,
            success=False,
            error_code="TIMEOUT",
            error_message="Connection timed out",
        )

        assert response.success is False
        assert response.status == ApiResultStatus.NETWORK_ERROR
        assert response.error_code == "TIMEOUT"
        assert response.error_message == "Connection timed out"

    def test_response_to_dict(self):
        """to_dict should serialize all fields."""
        response = ApiResponse(
            status=ApiResultStatus.SUCCESS,
            success=True,
            order_id="order123",
            filled_size=50.0,
            average_price=0.55,
            request_duration_ms=150.5,
        )

        d = response.to_dict()
        assert d["status"] == "SUCCESS"
        assert d["success"] is True
        assert d["order_id"] == "order123"
        assert d["filled_size"] == 50.0
        assert d["average_price"] == 0.55
        assert d["request_duration_ms"] == 150.5


# =============================================================================
# CREDENTIAL VALIDATION TESTS
# =============================================================================


class TestCredentialValidation:
    """Test API client credential validation."""

    def test_missing_private_key_raises(self):
        """Missing private key should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PolymarketApiClient(
                private_key="",
                api_key="test_key",
                api_secret="test_secret",
                signature_type=SIGNATURE_TYPE_EOA,
            )
        assert PRIVATE_KEY_ENV_VAR in str(exc_info.value)

    def test_missing_api_key_raises(self):
        """Missing API key should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PolymarketApiClient(
                private_key="test_pk",
                api_key="",
                api_secret="test_secret",
                signature_type=SIGNATURE_TYPE_EOA,
            )
        assert API_KEY_ENV_VAR in str(exc_info.value)

    def test_missing_api_secret_raises(self):
        """Missing API secret should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PolymarketApiClient(
                private_key="test_pk",
                api_key="test_key",
                api_secret="",
                signature_type=SIGNATURE_TYPE_EOA,
            )
        assert API_SECRET_ENV_VAR in str(exc_info.value)

    def test_poly_proxy_requires_funder(self):
        """POLY_PROXY signature type requires funder address."""
        with pytest.raises(ValueError) as exc_info:
            PolymarketApiClient(
                private_key="test_pk",
                api_key="test_key",
                api_secret="test_secret",
                funder_address="",
                signature_type=SIGNATURE_TYPE_POLY_PROXY,
            )
        assert FUNDER_ADDRESS_ENV_VAR in str(exc_info.value)

    def test_eoa_does_not_require_funder(self):
        """EOA signature type does not require funder address."""
        # Should not raise
        client = PolymarketApiClient(
            private_key="test_pk",
            api_key="test_key",
            api_secret="test_secret",
            funder_address="",
            signature_type=SIGNATURE_TYPE_EOA,
        )
        assert client is not None

    def test_valid_credentials_from_params(self):
        """Valid credentials passed as params should work."""
        client = PolymarketApiClient(
            private_key="0x1234567890abcdef",
            api_key="test_api_key",
            api_secret="test_api_secret",
            api_passphrase="test_passphrase",
            funder_address="0xfunder",
            signature_type=SIGNATURE_TYPE_POLY_PROXY,
        )
        assert client is not None

    @patch.dict(os.environ, {
        PRIVATE_KEY_ENV_VAR: "env_private_key",
        API_KEY_ENV_VAR: "env_api_key",
        API_SECRET_ENV_VAR: "env_api_secret",
        API_PASSPHRASE_ENV_VAR: "env_passphrase",
        FUNDER_ADDRESS_ENV_VAR: "env_funder",
    })
    def test_credentials_from_env(self):
        """Credentials should be read from environment variables."""
        client = PolymarketApiClient()
        assert client is not None


# =============================================================================
# API CLIENT ERROR HANDLING TESTS
# =============================================================================


class TestApiClientErrorHandling:
    """Test API client error handling - fail-closed behavior."""

    @pytest.fixture
    def client(self):
        """Create a client with test credentials."""
        return PolymarketApiClient(
            private_key="test_pk",
            api_key="test_key",
            api_secret="test_secret",
            funder_address="test_funder",
            signature_type=SIGNATURE_TYPE_POLY_PROXY,
        )

    @pytest.fixture
    def valid_payload(self):
        """Create a valid order payload."""
        return OrderPayload(
            token_id="test_token_id",
            price=0.5,
            size=100.0,
            side="BUY",
        )

    def test_submit_order_import_error(self, client, valid_payload):
        """Import error should return UNKNOWN_ERROR."""
        # Client not initialized, _initialize_client will fail on import
        response = client.submit_order(valid_payload)

        # Should fail because py_clob_client is not installed
        assert response.success is False
        # Either AUTH_ERROR (init failed) or UNKNOWN_ERROR (import)
        assert response.status in [ApiResultStatus.AUTH_ERROR, ApiResultStatus.UNKNOWN_ERROR]

    @patch("core.polymarket_api_client.PolymarketApiClient._initialize_client")
    def test_submit_order_client_init_failure(self, mock_init, client, valid_payload):
        """Client init failure should return AUTH_ERROR."""
        mock_init.return_value = False

        response = client.submit_order(valid_payload)

        assert response.success is False
        assert response.status == ApiResultStatus.AUTH_ERROR
        assert "CLIENT_INIT_FAILED" in (response.error_code or "")

    def test_cancel_order_invalid_id(self, client):
        """Cancel with invalid order_id should return REJECTED."""
        response = client.cancel_order("")

        assert response.success is False
        assert response.status == ApiResultStatus.REJECTED
        assert "INVALID_ORDER_ID" in (response.error_code or "")

    def test_cancel_order_none_id(self, client):
        """Cancel with None order_id should return REJECTED."""
        response = client.cancel_order(None)

        assert response.success is False
        assert response.status == ApiResultStatus.REJECTED

    def test_get_status_invalid_id(self, client):
        """Get status with invalid order_id should return REJECTED."""
        response = client.get_order_status("")

        assert response.success is False
        assert response.status == ApiResultStatus.REJECTED
        assert "INVALID_ORDER_ID" in (response.error_code or "")


# =============================================================================
# RESPONSE PARSING TESTS
# =============================================================================


class TestResponseParsing:
    """Test API response parsing - strict validation."""

    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        return PolymarketApiClient(
            private_key="test_pk",
            api_key="test_key",
            api_secret="test_secret",
            funder_address="test_funder",
            signature_type=SIGNATURE_TYPE_POLY_PROXY,
        )

    def test_parse_order_response_success_dict(self, client):
        """Successful dict response should parse correctly."""
        response = {"orderID": "order123", "status": "SUBMITTED"}
        result = client._parse_order_response(response, 100.0)

        assert result.success is True
        assert result.order_id == "order123"
        assert result.order_status == "SUBMITTED"
        assert result.request_duration_ms == 100.0

    def test_parse_order_response_success_string(self, client):
        """String response (just order ID) should parse correctly."""
        result = client._parse_order_response("order456", 50.0)

        assert result.success is True
        assert result.order_id == "order456"
        assert result.order_status == "SUBMITTED"

    def test_parse_order_response_error_in_response(self, client):
        """Response with error field should return REJECTED."""
        response = {"error": "Insufficient balance", "errorCode": "BALANCE_ERROR"}
        result = client._parse_order_response(response, 75.0)

        assert result.success is False
        assert result.status == ApiResultStatus.REJECTED
        assert "Insufficient balance" in result.error_message

    def test_parse_order_response_missing_order_id(self, client):
        """Response without order_id should return PARSE_ERROR."""
        response = {"status": "OK"}
        result = client._parse_order_response(response, 60.0)

        assert result.success is False
        assert result.status == ApiResultStatus.PARSE_ERROR
        assert "MISSING_ORDER_ID" in (result.error_code or "")

    def test_parse_order_response_none(self, client):
        """None response should return PARSE_ERROR."""
        result = client._parse_order_response(None, 30.0)

        assert result.success is False
        assert result.status == ApiResultStatus.PARSE_ERROR
        assert "EMPTY_RESPONSE" in (result.error_code or "")

    def test_parse_cancel_response_success_dict(self, client):
        """Successful cancel dict response should parse correctly."""
        response = {"success": True}
        result = client._parse_cancel_response(response, "order123", 40.0)

        assert result.success is True
        assert result.order_id == "order123"
        assert result.order_status == "CANCELLED"

    def test_parse_cancel_response_success_bool(self, client):
        """Boolean True cancel response should parse correctly."""
        result = client._parse_cancel_response(True, "order123", 35.0)

        assert result.success is True
        assert result.order_status == "CANCELLED"

    def test_parse_cancel_response_failure_bool(self, client):
        """Boolean False cancel response should return REJECTED."""
        result = client._parse_cancel_response(False, "order123", 45.0)

        assert result.success is False
        assert result.status == ApiResultStatus.REJECTED

    def test_parse_status_response_success(self, client):
        """Successful status response should parse correctly."""
        response = {
            "status": "FILLED",
            "filledSize": 100.0,
            "averagePrice": 0.55,
        }
        result = client._parse_status_response(response, "order123", 55.0)

        assert result.success is True
        assert result.order_status == "FILLED"
        assert result.filled_size == 100.0
        assert result.average_price == 0.55


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================


class TestCreateApiClient:
    """Test create_api_client factory function."""

    def test_create_without_env_vars_raises(self):
        """create_api_client without env vars should raise."""
        # Clear env vars
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                create_api_client()

    @patch.dict(os.environ, {
        PRIVATE_KEY_ENV_VAR: "test_pk",
        API_KEY_ENV_VAR: "test_key",
        API_SECRET_ENV_VAR: "test_secret",
        API_PASSPHRASE_ENV_VAR: "test_passphrase",
        FUNDER_ADDRESS_ENV_VAR: "test_funder",
    })
    def test_create_with_env_vars_succeeds(self):
        """create_api_client with valid env vars should succeed."""
        client = create_api_client()
        assert client is not None
        assert isinstance(client, PolymarketApiClient)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
