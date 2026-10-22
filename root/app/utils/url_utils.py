"""URL normalization and manipulation utilities."""


def normalize_url(url: str) -> str:
    """Normalize a raw URL string by stripping whitespace and ensuring a scheme prefix.

    Args:
        url: Raw URL string that may or may not include an http(s):// scheme.

    Returns:
        str: Trimmed URL guaranteed to start with http:// or https:// (or empty string if blank).
    """
    cleaned = url.strip()
    if cleaned and not cleaned.startswith(("http://", "https://")):
        return f"https://{cleaned}"
    return cleaned
