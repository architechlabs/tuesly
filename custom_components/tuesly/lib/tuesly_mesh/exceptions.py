"""Exception hierarchy for Tuesly.

All exceptions inherit from ``TueslyError``. Callers can catch the
base class for broad handling or specific subclasses for targeted recovery.

SECURITY: Exception messages MUST NEVER contain secret material
(keys, passwords, tokens). Use length/type descriptions only.
"""

from __future__ import annotations


class TueslyError(Exception):
    """Base exception for all Tuesly operations."""


class MeshConnectionError(TueslyError):
    """Failed to establish or maintain a BLE connection."""


class DeviceNotFoundError(TueslyError):
    """Target BLE device was not discovered during scanning."""


class MeshTimeoutError(TueslyError):
    """BLE operation exceeded the allowed time limit."""


class ProvisioningError(TueslyError):
    """Provisioning handshake failed."""


class ProtocolError(TueslyError):
    """Wire-level protocol violation."""


class MalformedPacketError(ProtocolError):
    """Received packet failed structural validation."""


class CryptoError(TueslyError):
    """Cryptographic operation failed."""


class AuthenticationError(CryptoError):
    """Mesh authentication (session key / pair proof) failed."""


class SecretAccessError(TueslyError):
    """Failed to read or write a secret via 1Password."""


class SIGMeshError(TueslyError):
    """SIG Mesh protocol or configuration error."""


class SIGMeshKeyError(SIGMeshError):
    """Required SIG Mesh key not available."""


class PowerControlError(TueslyError):
    """Bridge power control operation failed."""


class DisconnectedError(MeshConnectionError):
    """Operation attempted while device is disconnected."""


class CommandQueueFullError(TueslyError):
    """Command queue has reached its maximum capacity."""


class CommandExpiredError(TueslyError):
    """Command expired before it could be sent (TTL exceeded)."""


class InvalidRequestError(TueslyError):
    """Invalid command request parameters."""


class InvalidResultError(TueslyError):
    """Invalid command result data."""


class CorrelationConflictError(TueslyError):
    """Correlation key conflict — request_id already registered."""


# --- Backward-compatible aliases ---

# Phase 1 legacy aliases
BLEError = TueslyError
BLEConnectionError = MeshConnectionError
BLEDeviceNotFoundError = DeviceNotFoundError
BLETimeoutError = MeshTimeoutError
BLEServiceError = ProtocolError
BLECharacteristicError = ProtocolError
BLENotificationError = MeshConnectionError
