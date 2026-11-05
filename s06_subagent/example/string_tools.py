"""String utilities for the s06_subagent example.

Provides :func:`slugify`, a small helper that turns arbitrary
human-readable text into a clean, lowercase, ASCII, hyphen-separated
slug suitable for URLs, file names, and identifiers.
"""

import re
import unicodedata

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Convert *text* into a lowercase ASCII slug.

    Steps performed:
      1. Normalize unicode (NFKD) and strip combining marks so
         accented characters become plain ASCII letters.
      2. Convert to lowercase.
      3. Replace any run of non-alphanumeric characters with a single '-'.
      4. Strip leading/trailing '-'.
      5. Return '' for empty input or input that becomes empty.

    Examples:
        >>> slugify("Hello, World!")
        'hello-world'
        >>> slugify("  Héllo  Wörld ")
        'hello-world'
        >>> slugify("Already-a-slug")
        'already-a-slug'
        >>> slugify("")
        ''
        >>> slugify("!!!")
        ''
    """
    # 1. Normalize and drop combining marks (e.g. "é" -> "e").
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    # Drop anything still outside ASCII (e.g. characters NFKD cannot decompose).
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii")
    # 2. Lowercase.
    ascii_text = ascii_text.lower()
    # 3. Collapse runs of non-alphanumeric characters into a single '-'.
    slug = _NON_ALNUM_RE.sub("-", ascii_text)
    # 4. Strip leading/trailing '-'.
    slug = slug.strip("-")
    # 5. Empty input or fully stripped result yields ''.
    return slug


if __name__ == "__main__":
    examples = ["Hello, World!", "  Héllo  Wörld "]
    for text in examples:
        print(f"{text!r} -> {slugify(text)!r}")
