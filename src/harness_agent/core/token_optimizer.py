"""Token and output optimization module for agent responses and terminal outputs."""

import os
import re
from typing import Optional

# ANSI escape sequence pattern covering 7-bit and 8-bit ANSI / VT100 control codes
ANSI_ESCAPE_PATTERN = re.compile(r"(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]")

# Unicode ranges for emoji, pictographs, dingbats, and decorative symbols
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    "\U0001F680-\U0001F6FF"  # Transport and Map
    "\U0001F1E0-\U0001F1FF"  # Regional indicator symbols (flags)
    "\U0001F700-\U0001F77F"  # Alchemical Symbols
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002700-\U000027BF"  # Dingbats
    "\U00002600-\U000026FF"  # Miscellaneous Symbols
    "\U00002300-\U000023FF"  # Miscellaneous Technical
    "\U00002B50"  # Star
    "\U000020E3"  # Combining Enclosing Keycap
    "\U0000FE0E-\U0000FE0F"  # Variation Selectors
    "]+",
    flags=re.UNICODE,
)


def strip_ansi(text: str) -> str:
    """Strips ANSI escape sequences from text.

    Args:
        text: The raw terminal string containing potential ANSI escapes.

    Returns:
        Clean plain text without escape sequences.
    """
    if not text:
        return text
    return ANSI_ESCAPE_PATTERN.sub("", text)


def strip_emojis(text: str) -> str:
    """Strips Unicode emoji icons, pictographs, and dingbats from text.

    Args:
        text: Raw text potentially containing decorative emojis/icons.

    Returns:
        Sanitized plain text without emoji symbols.
    """
    if not text:
        return text
    return EMOJI_PATTERN.sub("", text)


def truncate_output(
    text: str,
    max_lines: int = 60,
    head_lines: int = 20,
    tail_lines: int = 40,
    spillover_path: Optional[str] = None,
    remove_emojis: bool = True,
) -> str:
    """Truncates command or tool output preserving head and tail context.

    Args:
        text: Raw text to truncate.
        max_lines: Maximum line threshold before truncation occurs.
        head_lines: Number of prefix lines to keep.
        tail_lines: Number of suffix lines to keep.
        spillover_path: Optional path to write the full untruncated content.
        remove_emojis: Whether to strip decorative emojis from the text.

    Returns:
        Formatted text with truncation notice if truncated.

    Raises:
        ValueError: If head_lines + tail_lines > max_lines or negative parameters given.
    """
    if text is None:
        return ""
    if not text:
        return ""

    if head_lines < 0 or tail_lines < 0 or max_lines < 0:
        raise ValueError("Line counts cannot be negative.")

    if head_lines + tail_lines > max_lines:
        raise ValueError(
            f"head_lines ({head_lines}) + tail_lines ({tail_lines}) "
            f"cannot exceed max_lines ({max_lines})."
        )

    # Process text: clean ANSI first
    cleaned = strip_ansi(text)
    if remove_emojis:
        cleaned = strip_emojis(cleaned)

    # Save to spillover_path if requested
    if spillover_path:
        os.makedirs(os.path.dirname(os.path.abspath(spillover_path)), exist_ok=True)
        with open(spillover_path, "w", encoding="utf-8") as f:
            f.write(cleaned)

    # Split lines normalizing CRLF and LF
    lines = cleaned.splitlines()

    if len(lines) <= max_lines:
        return "\n".join(lines)

    head = lines[:head_lines]
    tail = lines[-tail_lines:] if tail_lines > 0 else []
    omitted_count = len(lines) - (head_lines + tail_lines)

    saved_info = spillover_path if spillover_path else "not saved"
    delimiter = (
        f"[... {omitted_count} lines omitted to conserve tokens. Full output: {saved_info} ...]"
    )

    parts = []
    if head:
        parts.append("\n".join(head))
    parts.append(delimiter)
    if tail:
        parts.append("\n".join(tail))

    return "\n".join(parts)
