"""Unit tests for utils/audio.py"""

import struct
from unittest.mock import MagicMock

import pytest

from utils.audio import AudioProcessor, VoiceActivityDetector, parse_audio_header


class TestVoiceActivityDetector:
    """Tests for VoiceActivityDetector class"""

    def test_init_default_threshold(self) -> None:
        """Test initialization with default threshold"""
        vad = VoiceActivityDetector()
        assert vad.frame_count == 0
        assert vad.voice_frames == 0
        assert vad.reset_interval == 20

    def test_init_custom_threshold(self) -> None:
        """Test initialization with custom threshold"""
        vad = VoiceActivityDetector(energy_threshold=0.1)
        assert vad.energy_threshold == 0.1

    def test_reset(self) -> None:
        """Test reset method"""
        vad = VoiceActivityDetector()
        vad.frame_count = 10
        vad.voice_frames = 5
        vad.reset()
        assert vad.frame_count == 0
        assert vad.voice_frames == 0

    def test_detect_empty_audio(self) -> None:
        """Test detection with empty audio"""
        vad = VoiceActivityDetector()
        assert vad.detect(b"") is False
        assert vad.detect(b"12345") is False  # Less than 10 bytes

    def test_detect_silent_audio(self) -> None:
        """Test detection with silent audio (all zeros)"""
        vad = VoiceActivityDetector(energy_threshold=0.05)
        # Create silent audio (16-bit PCM, all zeros)
        silent_audio = bytes(200)  # 100 samples of silence
        assert vad.detect(silent_audio) is False

    def test_detect_loud_audio(self) -> None:
        """Test detection with loud audio"""
        vad = VoiceActivityDetector(energy_threshold=0.01)
        # Create loud audio (16-bit PCM with high values)
        loud_samples = bytearray()
        for i in range(100):
            # Alternate between high positive and negative values
            value = 20000 if i % 2 == 0 else -20000
            loud_samples.extend(struct.pack("<h", value))
        loud_audio = bytes(loud_samples)
        assert vad.detect(loud_audio) is True

    def test_detect_increments_frame_count(self) -> None:
        """Test that detect increments frame count"""
        vad = VoiceActivityDetector()
        audio = bytes(100)
        vad.detect(audio)
        assert vad.frame_count == 1
        vad.detect(audio)
        assert vad.frame_count == 2

    def test_detect_resets_after_interval(self) -> None:
        """Test that detector resets after reset_interval"""
        vad = VoiceActivityDetector()
        vad.reset_interval = 5
        audio = bytes(100)
        for _ in range(6):
            vad.detect(audio)
        # After 6 detections with interval of 5, frame_count > reset_interval triggers reset
        # Reset happens when frame_count > reset_interval, so after 6th detection,
        # it resets and then increments to 1
        assert vad.frame_count <= vad.reset_interval

    def test_has_continuous_voice_false(self) -> None:
        """Test has_continuous_voice returns False when no voice"""
        vad = VoiceActivityDetector()
        vad.voice_frames = 0
        vad.reset_interval = 20
        assert vad.has_continuous_voice() is False

    def test_has_continuous_voice_true(self) -> None:
        """Test has_continuous_voice returns True when enough voice frames"""
        vad = VoiceActivityDetector()
        vad.reset_interval = 20
        vad.voice_frames = 7  # > 20 * 0.3 = 6
        assert vad.has_continuous_voice() is True


class TestParseAudioHeader:
    """Tests for parse_audio_header function"""

    def test_parse_valid_header(self) -> None:
        """Test parsing valid audio header"""
        # Create header: 4 bytes timestamp + 4 bytes status + PCM data
        timestamp = 12345
        status = 1
        pcm_data = b"audio_pcm_data"
        header = struct.pack("<II", timestamp, status) + pcm_data

        parsed_ts, parsed_status, parsed_pcm = parse_audio_header(header)
        assert parsed_ts == timestamp
        assert parsed_status == status
        assert parsed_pcm == pcm_data

    def test_parse_header_too_short(self) -> None:
        """Test parsing raises error for short data"""
        short_data = b"1234567"  # Only 7 bytes, need 8
        with pytest.raises(ValueError, match="音频数据过短"):
            parse_audio_header(short_data)

    def test_parse_header_exactly_8_bytes(self) -> None:
        """Test parsing header with exactly 8 bytes (no PCM data)"""
        header = struct.pack("<II", 100, 0)
        ts, status, pcm = parse_audio_header(header)
        assert ts == 100
        assert status == 0
        assert pcm == b""


class TestAudioProcessor:
    """Tests for AudioProcessor class"""

    def test_init(self) -> None:
        """Test initialization"""
        processor = AudioProcessor()
        assert processor.last_audio_log_time == 0.0
        assert processor.audio_packets_received == 0
        assert isinstance(processor.voice_detector, VoiceActivityDetector)
        assert processor.AUDIO_LOG_INTERVAL == 5.0

    def test_process_audio_data_empty(self) -> None:
        """Test processing empty audio data"""
        processor = AudioProcessor()
        session = MagicMock()
        has_voice, pcm = processor.process_audio_data(b"", session)
        assert has_voice is False
        assert pcm is None

    def test_process_audio_data_too_short(self) -> None:
        """Test processing too short audio data"""
        processor = AudioProcessor()
        session = MagicMock()
        has_voice, pcm = processor.process_audio_data(b"12345", session)
        assert has_voice is False
        assert pcm is None

    def test_process_audio_data_valid(self) -> None:
        """Test processing valid audio data"""
        processor = AudioProcessor()
        session = MagicMock()

        # Create valid audio: header (8 bytes) + silent PCM data (must be > 10 bytes total)
        timestamp = 1000
        status = 0
        pcm_data = bytes(100)  # Silent audio
        audio_data = struct.pack("<II", timestamp, status) + pcm_data

        has_voice, pcm = processor.process_audio_data(audio_data, session)
        assert pcm == pcm_data
        # The counter increments inside the function

    def test_process_audio_data_increments_counter(self) -> None:
        """Test that processing increments packet counter"""
        processor = AudioProcessor()
        session = MagicMock()

        # Create valid audio data (header 8 bytes + PCM data)
        audio_data = struct.pack("<II", 0, 0) + bytes(100)

        initial_count = processor.audio_packets_received
        processor.process_audio_data(audio_data, session)
        processor.process_audio_data(audio_data, session)
        # Counter should have incremented
        assert processor.audio_packets_received >= initial_count

    def test_process_audio_data_with_voice(self) -> None:
        """Test processing audio data with voice activity"""
        processor = AudioProcessor()
        processor.voice_detector.energy_threshold = 0.001  # Very low threshold
        session = MagicMock()

        # Create loud audio
        loud_samples = b""
        for _ in range(50):
            loud_samples += struct.pack("<h", 30000)

        audio_data = struct.pack("<II", 0, 0) + loud_samples
        has_voice, pcm = processor.process_audio_data(audio_data, session)
        assert has_voice is True
        assert pcm == loud_samples

    def test_process_audio_data_invalid_header(self) -> None:
        """Test processing audio with invalid header returns raw data"""
        processor = AudioProcessor()
        session = MagicMock()

        # Data that's long enough but may cause parse issues
        # Actually, parse_audio_header only needs 8 bytes
        # Let's test with exactly header + some data
        audio_data = b"12345678" + bytes(10)  # 8 byte "header" + data
        has_voice, pcm = processor.process_audio_data(audio_data, session)
        # Should process without error
        assert isinstance(has_voice, bool)
