import struct
import time
from typing import Tuple, Optional

from loguru import logger

from config import Config


# 诊断功能已移除，简化代码


class VoiceActivityDetector:
    """检测用户语音活动"""

    def __init__(self, energy_threshold: float = Config.VOICE_ENERGY_THRESHOLD) -> None:
        """初始化语音活动检测器

        Args:
            energy_threshold: 能量阈值，用于确定语音活动
        """
        self.energy_threshold = energy_threshold
        self.frame_count = 0
        self.voice_frames = 0
        self.reset_interval = 20  # 每隔多少帧重置计数

    def reset(self) -> None:
        """重置检测器状态"""
        self.frame_count = 0
        self.voice_frames = 0

    def detect(self, audio_chunk: bytes) -> bool:
        """检测音频块中是否包含语音

        Args:
            audio_chunk: 音频数据块

        Returns:
            如果检测到语音，返回True
        """
        if not audio_chunk or len(audio_chunk) < 10:
            return False

        # 仅每N帧检查一次
        self.frame_count += 1
        if self.frame_count > self.reset_interval:
            self.reset()

        try:
            # 计算音频能量
            max_samples = min(50, len(audio_chunk) // 2)  # 最多处理50个样本
            if max_samples <= 0:
                return False

            # 解析PCM样本
            pcm_samples = []
            for i in range(max_samples):
                if i * 2 + 1 < len(audio_chunk):
                    # 解析2字节为16位整数
                    value = int.from_bytes(audio_chunk[i * 2 : i * 2 + 2], byteorder="little", signed=True)
                    pcm_samples.append(value)

            if not pcm_samples:
                return False

            # 计算平均能量
            energy = sum(abs(sample) for sample in pcm_samples) / len(pcm_samples)

            # 归一化能量值（16位PCM范围是-32768到32767）
            normalized_energy = energy / 32768.0

            # 判断是否超过阈值
            has_voice = normalized_energy > self.energy_threshold
            if has_voice:
                self.voice_frames += 1

            return has_voice

        except Exception as e:
            logger.debug(f"语音检测错误: {e}")
            return False

    def has_continuous_voice(self) -> bool:
        """判断是否检测到连续的语音帧

        Returns:
            如果有持续语音，返回True
        """
        # 如果语音帧数超过阈值比例，认为有持续语音
        return self.voice_frames > (self.reset_interval * 0.3)


def parse_audio_header(audio_data: bytes) -> Tuple[int, int, bytes]:
    """解析音频数据中的头部信息

    Args:
        audio_data: 原始音频数据，包含头部信息

    Returns:
        时间戳，状态标志和PCM数据
    """
    if len(audio_data) < 8:
        raise ValueError("音频数据过短，无法解析头部")

    # 解析头部信息
    # [4字节时间戳][4字节状态标志][PCM数据]
    header = audio_data[:8]
    timestamp = struct.unpack("<I", header[:4])[0]  # 小端序时间戳
    status_flags = struct.unpack("<I", header[4:8])[0]  # 小端序状态标志

    # 提取PCM数据部分
    pcm_data = audio_data[8:]

    return timestamp, status_flags, pcm_data
