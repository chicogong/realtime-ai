"""Unit tests for utils/text.py"""

from utils.text import clean_text, process_streaming_text, split_into_sentences


class TestSplitIntoSentences:
    """Tests for split_into_sentences function

    Note: The function uses lookbehind to split, preserving punctuation with the sentence.
    """

    def test_chinese_sentences(self) -> None:
        """Test splitting Chinese sentences"""
        text = "你好。我是AI助手。有什么可以帮您的吗？"
        result = split_into_sentences(text)
        # Punctuation is preserved with each sentence
        assert result == ["你好。", "我是AI助手。", "有什么可以帮您的吗？"]

    def test_english_sentences(self) -> None:
        """Test splitting English sentences"""
        text = "Hello. I am an AI assistant. How can I help you?"
        result = split_into_sentences(text)
        assert result == ["Hello.", "I am an AI assistant.", "How can I help you?"]

    def test_mixed_punctuation(self) -> None:
        """Test splitting with mixed punctuation"""
        text = "这是第一句！这是第二句？好的。"
        result = split_into_sentences(text)
        assert result == ["这是第一句！", "这是第二句？", "好的。"]

    def test_empty_string(self) -> None:
        """Test with empty string"""
        result = split_into_sentences("")
        assert result == []

    def test_no_punctuation(self) -> None:
        """Test with no punctuation"""
        text = "这是一段没有标点符号的文字"
        result = split_into_sentences(text)
        assert result == ["这是一段没有标点符号的文字"]

    def test_comma_separation(self) -> None:
        """Test comma separated text"""
        text = "第一部分，第二部分，第三部分"
        result = split_into_sentences(text)
        # Last part has no trailing comma
        assert result == ["第一部分，", "第二部分，", "第三部分"]

    def test_single_sentence(self) -> None:
        """Test single sentence"""
        text = "这是一句话。"
        result = split_into_sentences(text)
        assert result == ["这是一句话。"]


class TestProcessStreamingText:
    """Tests for process_streaming_text function"""

    def test_complete_sentence(self) -> None:
        """Test with complete sentence"""
        sentences, buffer = process_streaming_text("你好。", "")
        assert sentences == ["你好。"]
        assert buffer == ""

    def test_incomplete_sentence(self) -> None:
        """Test with incomplete sentence"""
        sentences, buffer = process_streaming_text("你好", "")
        assert sentences == []
        assert buffer == "你好"

    def test_multiple_sentences(self) -> None:
        """Test with multiple complete sentences"""
        sentences, buffer = process_streaming_text("你好。世界！", "")
        assert sentences == ["你好。", "世界！"]
        assert buffer == ""

    def test_with_existing_buffer(self) -> None:
        """Test streaming with existing buffer"""
        sentences, buffer = process_streaming_text("世界。", "你好，")
        assert sentences == ["你好，", "世界。"]
        assert buffer == ""

    def test_partial_completion(self) -> None:
        """Test with partial completion leaving buffer"""
        sentences, buffer = process_streaming_text("世界。再见", "你好，")
        assert sentences == ["你好，", "世界。"]
        assert buffer == "再见"

    def test_empty_chunk(self) -> None:
        """Test with empty chunk"""
        sentences, buffer = process_streaming_text("", "你好")
        assert sentences == []
        assert buffer == "你好"

    def test_english_streaming(self) -> None:
        """Test English text streaming"""
        sentences, buffer = process_streaming_text("Hello. World", "")
        assert sentences == ["Hello."]
        assert buffer == "World"

    def test_streaming_accumulation(self) -> None:
        """Test progressive streaming accumulation"""
        # First chunk - incomplete
        sentences, buffer = process_streaming_text("Hello", "")
        assert sentences == []
        assert buffer == "Hello"

        # Second chunk - completes sentence, but ". " splits into "." and " "
        # The period completes "Hello." but space remains
        sentences, buffer = process_streaming_text(".", buffer)
        assert sentences == ["Hello."]
        assert buffer == ""


class TestCleanText:
    """Tests for clean_text function"""

    def test_excess_whitespace(self) -> None:
        """Test removing excess whitespace"""
        text = "Hello    World"
        result = clean_text(text)
        assert result == "Hello World"

    def test_leading_trailing_whitespace(self) -> None:
        """Test removing leading/trailing whitespace"""
        text = "   Hello World   "
        result = clean_text(text)
        assert result == "Hello World"

    def test_newlines_and_tabs(self) -> None:
        """Test removing newlines and tabs"""
        text = "Hello\n\tWorld"
        result = clean_text(text)
        assert result == "Hello World"

    def test_empty_string(self) -> None:
        """Test with empty string"""
        result = clean_text("")
        assert result == ""

    def test_only_whitespace(self) -> None:
        """Test with only whitespace"""
        result = clean_text("   \n\t   ")
        assert result == ""
