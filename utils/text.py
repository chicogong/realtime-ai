import re
from typing import List


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences based on punctuation

    Args:
        text: Input text

    Returns:
        List of sentences
    """
    # Match common sentence terminators in both Chinese and English
    sentence_ends = r"(?<=[。！？.!?;；:：])\s*"
    sentences = re.split(sentence_ends, text)
    return [s.strip() for s in sentences if s.strip()]


def clean_text(text: str) -> str:
    """Clean text by removing excess whitespace and special characters

    Args:
        text: Input text

    Returns:
        Cleaned text
    """
    return re.sub(r"\s+", " ", text).strip()
