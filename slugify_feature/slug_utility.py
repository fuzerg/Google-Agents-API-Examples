import re
import unicodedata

def slugify(text: str) -> str:
    """
    Converts arbitrary text into a URL-safe slug.
    
    Rules:
    - Convert to lowercase.
    - Normalize unicode characters to decompose combined characters, then strip non-ASCII.
    - Replace spaces and punctuation (anything that is not alphanumeric or hyphens) with hyphens.
    - Collapse multiple consecutive hyphens into a single hyphen.
    - Trim leading and trailing hyphens.
    """
    if not isinstance(text, str):
        return ""
        
    # Normalize unicode to NFKD to separate characters from their diacritics
    text = unicodedata.normalize('NFKD', text)
    # Strip any combining diacritics (category 'Mn')
    text = "".join([c for c in text if not unicodedata.combining(c)])
    # Convert to lowercase
    text = text.lower()
    # Replace non-alphanumeric/non-hyphen characters with hyphens
    text = re.sub(r'[^a-z0-9\-]', '-', text)
    # Collapse multiple consecutive hyphens
    text = re.sub(r'-+', '-', text)
    # Trim leading/trailing hyphens
    text = text.strip('-')
    
    return text
