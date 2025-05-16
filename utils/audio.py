import struct
import time
from typing import Tuple

from loguru import logger

from config import Config


class AudioDiagnostics:
    """音频问题诊断辅助类"""

    def __init__(self):
        """初始化音频诊断工具"""
        self.total_bytes = 0
        self.chunks_received = 0
        self.last_report_time = time.time()
        self.report_interval = 5  # 报告间隔（秒）
        self.first_chunk = None

    def record_chunk(self, chunk: bytes) -> None:
        """记录音频块信息

        Args:
            chunk: 音频数据块
        """
        if not chunk:
            return

        self.total_bytes += len(chunk)
        self.chunks_received += 1

        # 保存首个块以便分析
        if not self.first_chunk:
            self.first_chunk = chunk
            self.analyze_audio_format(chunk)

        # 定期报告统计信息
        current_time = time.time()
        if current_time - self.last_report_time > self.report_interval:
            self.report_stats()
            self.last_report_time = current_time

    def report_stats(self) -> None:
        """报告音频统计信息"""
        if self.chunks_received == 0:
            logger.warning("未收到音频块")
            return

        avg_chunk_size = self.total_bytes / self.chunks_received

        # 检查音频数据是否有效
        if avg_chunk_size < 10:
            logger.warning(f"音频块过小(平均{avg_chunk_size:.2f}字节)")

        logger.info(f"音频统计: {self.chunks_received}块 {self.total_bytes}字节 平均{avg_chunk_size:.2f}字节/块")

        # 重置计数器
        self.total_bytes = 0
        self.chunks_received = 0

    def analyze_audio_format(self, chunk: bytes) -> None:
        """分析音频格式以检测潜在问题

        Args:
            chunk: 音频数据块
        """
        if len(chunk) < 10:
            logger.warning("音频块太小，无法分析格式")
            return

        try:
            # 尝试解析为16位PCM
            if len(chunk) >= 20:  # 至少取10个样本
                pcm_samples = struct.unpack(f"<{len(chunk)//2}h", chunk[:20])

                # 检查振幅变化
                min_val = min(pcm_samples)
                max_val = max(pcm_samples)
                amplitude_range = max_val - min_val

                if amplitude_range < 100:
                    logger.warning(f"音频振幅变化很小: 最小={min_val}, 最大={max_val}。请检查麦克风是否正常工作")

                # 检查是否全为零（静音）
                if max_val == 0 and min_val == 0:
                    logger.warning("音频数据全为零（静音）")

                logger.info(f"音频格式看起来是PCM，振幅范围: {min_val}至{max_val}")
        except Exception as e:
            logger.warning(f"音频格式分析失败: {e}")


class VoiceActivityDetector:
    """检测用户语音活动"""

    def __init__(self, energy_threshold: float = Config.VOICE_ENERGY_THRESHOLD):
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
