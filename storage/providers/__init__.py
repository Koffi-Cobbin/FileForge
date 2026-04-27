"""Storage provider package.

Importing this package eagerly loads the registry so that the default
providers are available everywhere the registry is referenced.
"""
from .base import (  # noqa: F401
    BaseStorageProvider,
    DirectUploadTicket,
    ProviderConfigurationError,
    ProviderError,
    ProviderUnsupportedOperation,
    UploadResult,
)
from .registry import registry  # noqa: F401
