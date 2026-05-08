"""
LLM Provider Protocol for memory layer.

This module defines the abstract interface that all LLM providers must implement.
"""

from typing import AsyncGenerator, Protocol


class LLMProvider(Protocol):
    """
    Protocol for LLM providers used in text generation.

    All concrete LLM provider implementations must implement this interface
    to be compatible with the memory layer's requirements.
    """

    async def generate(
        self,
        prompt: str,
        temperature: float | None = None,
        extra_body: dict | None = None,
        response_format: dict | None = None,
    ) -> str:
        """
        Generate a response for the given prompt.

        Args:
            prompt: Input prompt text
            temperature: Optional temperature override for this request

        Returns:
            Generated response text

        Raises:
            Exception: If generation fails
        """
        ...

    async def generate_stream(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response for the given prompt.

        Yields tokens as they arrive, providing early feedback during LLM calls.

        Args:
            prompt: Input prompt text
            temperature: Optional temperature override
            max_tokens: Optional max tokens override
            response_format: Optional response format

        Yields:
            str: Each chunk of generated text
        """
        ...

    async def test_connection(self) -> bool:
        """
        Test the connection to the LLM provider.

        Returns:
            True if connection successful, False otherwise
        """
        ...

    def __repr__(self) -> str:
        """String representation of the provider."""
        ...


class LLMError(Exception):
    """Exception raised for LLM-related errors."""

    pass
