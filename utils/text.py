import re
from typing import List, Tuple


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences based on punctuation

    Args:
        text: Input text

    Returns:
        List of sentences
    """
    # Match common sentence terminators and other punctuation in both Chinese and English
    sentence_ends = r"(?<=[。！？.!?;；:：，,、])\s*"
    sentences = re.split(sentence_ends, text)
    return [s.strip() for s in sentences if s.strip()]


def process_streaming_text(chunk: str, current_buffer: str = "") -> Tuple[List[str], str]:
    """Process streaming text and extract complete sentences

    Args:
        chunk: New text chunk from streaming
        current_buffer: Current accumulated text buffer

    Returns:
        Tuple of (complete sentences, remaining buffer)
    """
    # Add new chunk to buffer
    text_buffer = current_buffer + chunk
    
    # Define sentence endings (same as in split_into_sentences)
    sentence_endings = ["。", "！", "？", ".", "!", "?", "，", ",", "、", ";", "；", ":", "："]
    
    # Check if we have any sentence endings
    if not any(end in text_buffer for end in sentence_endings):
        # No complete sentences yet
        return [], text_buffer
        
    # Split into sentences
    sentences = split_into_sentences(text_buffer)
    
    # Check if last part is a complete sentence
    if text_buffer.endswith(tuple(sentence_endings)):
        # All text forms complete sentences
        return sentences, ""
    else:
        # Last part is incomplete, keep it in buffer
        complete_sentences = sentences[:-1]
        remaining_buffer = sentences[-1] if sentences else ""
        return complete_sentences, remaining_buffer


def clean_text(text: str) -> str:
    """Clean text by removing excess whitespace and special characters

    Args:
        text: Input text

    Returns:
        Cleaned text
    """
    return re.sub(r"\s+", " ", text).strip()
