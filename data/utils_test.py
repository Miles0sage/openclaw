"""Utility functions for OpenClaw data processing."""


def format_usd(amount: float) -> str:
    """Format a float as USD currency.
    
    Args:
        amount: The amount to format as USD.
        
    Returns:
        USD formatted string (e.g., 1234.5 -> '$1,234.50')
    """
    return f"${amount:,.2f}"


def truncate(text: str, max_len: int = 100) -> str:
    """Truncate text to max length with '...' if too long.
    
    Args:
        text: The text to truncate.
        max_len: Maximum length before truncation (default: 100).
        
    Returns:
        Truncated text with '...' if it exceeds max_len.
    """
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


if __name__ == "__main__":
    # Test format_usd
    print("Testing format_usd:")
    print(f"  format_usd(1234.5) = '{format_usd(1234.5)}'")
    print(f"  format_usd(1000000) = '{format_usd(1000000)}'")
    print(f"  format_usd(0.99) = '{format_usd(0.99)}'")
    print(f"  format_usd(-50.25) = '{format_usd(-50.25)}'")
    
    print("\nTesting truncate:")
    # Test truncate with short text
    short_text = "Hello, World!"
    print(f"  truncate('{short_text}') = '{truncate(short_text)}'")
    
    # Test truncate with long text
    long_text = "This is a very long string that should be truncated when it exceeds the maximum length of one hundred characters."
    print(f"  truncate('{long_text}', 50) = '{truncate(long_text, 50)}'")
    
    # Test truncate with default max_len
    default_text = "A" * 150
    print(f"  truncate('A'*150) = '{truncate(default_text)}'")
    
    print("\nAll tests completed!")
