"""A simple greeting example.

Demonstrates a small, well-typed function with a ``main`` guard so the
module is safe to import without side effects.
"""


def greet(name: str) -> None:
    """Print a greeting for the given name.

    Args:
        name: The name to greet.
    """
    message = "Hello, " + name
    print(message)


if __name__ == "__main__":
    greet("Claude")
