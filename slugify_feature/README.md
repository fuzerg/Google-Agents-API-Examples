# Slugify String Utility

A python utility for converting arbitrary text into a URL-safe slug.

## Features
- Converts text to lowercase.
- Normalizes Unicode characters (e.g., handles diacritics like `Café` -> `cafe`).
- Collapses non-alphanumeric punctuation and spaces into single hyphens.
- Trims leading and trailing hyphens.

## Usage

```python
from slug_utility import slugify

slug = slugify("Hello, World!!! This is a test...")
print(slug)  # Output: "hello-world-this-is-a-test"
```

## Running Tests

To run the unit tests, use:
```bash
python3 -m unittest discover -v
```
