import json
import sys
import re


def camel_to_screaming_snake(name):
    """Convert camelCase to SCREAMING_SNAKE_CASE"""
    # Insert an underscore before any uppercase letter that follows a lowercase letter
    s1 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert an underscore before any uppercase letter that follows another uppercase
    # letter and is followed by a lowercase letter
    s2 = re.sub("([A-Z])([A-Z][a-z])", r"\1_\2", s1)
    return s2.upper()


constants = json.loads(sys.argv[1])

print('"""Variable constants for Virby — generated from _lib.constants"""\n')
for key, value in constants.items():
    python_key = camel_to_screaming_snake(key)

    if isinstance(value, str):
        print(f'{python_key} = "{value}"')
    else:
        print(f"{python_key} = {value}")
