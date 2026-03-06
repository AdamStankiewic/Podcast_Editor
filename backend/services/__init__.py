"""
Services package
Contains all business logic services

TTS providers are lazily imported to avoid torch dependency at import time.
Use get_tts_provider() factory function to get provider instances.
"""
from backend.services.tts_provider import (
    TTSProvider,
    TTSProviderType,
    TTSConfig,
    TTSResult,
    get_tts_provider
)

# Legacy Azure TTS class (always available)
from backend.services.azure_tts_batch import AzureTTSBatchService

__all__ = [
    # TTS Provider abstraction
    "TTSProvider",
    "TTSProviderType",
    "TTSConfig",
    "TTSResult",
    "get_tts_provider",
    # Legacy class for backwards compatibility
    "AzureTTSBatchService",
]


def get_chatterbox_provider():
    """Lazy import ChatterboxTTSProvider to avoid torch dependency at module load"""
    from backend.services.chatterbox_tts import ChatterboxTTSProvider
    return ChatterboxTTSProvider


def get_azure_provider():
    """Get Azure TTS Provider class"""
    from backend.services.azure_tts_batch import AzureTTSProvider
    return AzureTTSProvider
