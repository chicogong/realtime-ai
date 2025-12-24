"""Security utilities for handling sensitive data"""

from typing import Any, Dict, Set


class SensitiveDataMasker:
    """Utility class for masking sensitive data in logs and outputs"""

    # Keys that indicate sensitive values
    SENSITIVE_KEYS: Set[str] = {
        "api_key",
        "apikey",
        "api-key",
        "subscription_key",
        "key",
        "token",
        "password",
        "pwd",
        "secret",
        "bearer_token",
        "authorization",
        "credential",
        "credentials",
    }

    @classmethod
    def is_sensitive_key(cls, key: str) -> bool:
        """Check if a key name indicates sensitive data"""
        key_lower = key.lower().replace("-", "_")
        return any(sensitive in key_lower for sensitive in cls.SENSITIVE_KEYS)

    @classmethod
    def mask_value(cls, value: Any, key: str = "") -> str:
        """Mask a sensitive value, showing only first and last 2 characters

        Args:
            value: The value to potentially mask
            key: The key name (used to determine if masking is needed)

        Returns:
            Masked string if sensitive, otherwise original string representation
        """
        if not isinstance(value, str):
            value = str(value)

        if not value:
            return str(value)

        # Check if this is a sensitive key
        if key and cls.is_sensitive_key(key):
            if len(value) <= 4:
                return "*" * len(value)
            return str(value[:2] + "*" * (len(value) - 4) + value[-2:])

        return str(value)

    @classmethod
    def mask_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask all sensitive values in a dictionary

        Args:
            data: Dictionary potentially containing sensitive values

        Returns:
            New dictionary with sensitive values masked
        """
        masked: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                masked[key] = cls.mask_dict(value)
            else:
                masked[key] = cls.mask_value(value, key)
        return masked

    @classmethod
    def mask_url(cls, url: str) -> str:
        """Mask sensitive parameters in a URL

        Args:
            url: URL that may contain sensitive query parameters

        Returns:
            URL with sensitive parameters masked
        """
        if not url:
            return url

        # Simple approach: mask common patterns
        import re

        # Mask api_key, key, token parameters
        patterns = [
            (r"(api_key=)[^&]+", r"\1****"),
            (r"(key=)[^&]+", r"\1****"),
            (r"(token=)[^&]+", r"\1****"),
            (r"(secret=)[^&]+", r"\1****"),
        ]

        masked_url = url
        for pattern, replacement in patterns:
            masked_url = re.sub(pattern, replacement, masked_url, flags=re.IGNORECASE)

        return masked_url


def mask_sensitive(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to mask sensitive data in a dictionary"""
    return SensitiveDataMasker.mask_dict(data)
