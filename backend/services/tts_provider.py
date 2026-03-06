"""
TTS Provider Abstraction Layer

Defines the interface for Text-to-Speech providers, allowing easy switching
between Azure TTS, Chatterbox, and other providers.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from enum import Enum


class TTSProviderType(Enum):
    """Available TTS providers"""
    CHATTERBOX = "chatterbox"
    AZURE = "azure"


@dataclass
class TTSConfig:
    """Configuration for TTS generation"""
    voice: str = ""                    # Voice name/ID or path to reference audio
    target_language: str = "pl"        # Target language code
    rate: float = 1.0                  # Speech rate (1.0 = normal)
    exaggeration: float = 0.4          # Emotion exaggeration (Chatterbox: 0.0-1.0)
    cfg_weight: float = 0.5            # CFG weight for Chatterbox

    # Provider-specific settings
    azure_pitch: str = "0%"            # Azure pitch adjustment
    azure_rate: str = "-10%"           # Azure rate string
    azure_region: str = "northeurope"  # Azure region
    azure_key: str = ""                # Azure API key


@dataclass
class TTSResult:
    """Result of TTS generation"""
    audio_path: Path
    duration_seconds: float
    provider: TTSProviderType
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class TTSProvider(ABC):
    """Abstract base class for TTS providers"""

    provider_type: TTSProviderType

    @abstractmethod
    def generate_audio(
        self,
        text: str,
        output_path: Path,
        config: TTSConfig,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> TTSResult:
        """
        Generate audio from text

        Args:
            text: Plain text to synthesize (pronunciations already applied)
            output_path: Path for output WAV file
            config: TTS configuration
            progress_callback: Optional callback(current, total, message)

        Returns:
            TTSResult with audio path and metadata
        """
        pass

    @abstractmethod
    def supports_voice_cloning(self) -> bool:
        """Returns True if provider supports voice cloning"""
        pass

    @abstractmethod
    def set_reference_audio(self, audio_path: Path) -> None:
        """Set reference audio for voice cloning (if supported)"""
        pass

    @abstractmethod
    def get_supported_languages(self) -> list:
        """Get list of supported language codes"""
        pass

    def validate_config(self, config: TTSConfig) -> tuple[bool, str]:
        """
        Validate configuration for this provider

        Returns:
            (is_valid, error_message)
        """
        return True, ""


def get_tts_provider(
    provider_type: TTSProviderType = TTSProviderType.CHATTERBOX,
    **kwargs
) -> TTSProvider:
    """
    Factory function to get TTS provider instance

    Args:
        provider_type: Type of provider to use
        **kwargs: Provider-specific initialization arguments

    Returns:
        TTSProvider instance
    """
    if provider_type == TTSProviderType.CHATTERBOX:
        from backend.services.chatterbox_tts import ChatterboxTTSProvider
        return ChatterboxTTSProvider(**kwargs)

    elif provider_type == TTSProviderType.AZURE:
        from backend.services.azure_tts_batch import AzureTTSProvider
        return AzureTTSProvider(**kwargs)

    else:
        raise ValueError(f"Unknown TTS provider: {provider_type}")
