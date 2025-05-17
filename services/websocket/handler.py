import asyncio
import json
import struct
import time
import uuid
from typing import Any, Dict, Optional, Tuple, List, Union, cast

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from config import Config
from models.session import get_all_sessions, get_session, remove_session, SessionState
from services.asr import create_asr_service, BaseASRService
from services.llm import create_llm_service
from services.tts import close_all_tts_services, create_tts_service
from utils.audio import VoiceActivityDetector, parse_audio_header
from utils.text import split_into_sentences
from .pipeline import PipelineHandler


class AudioProcessor:
    """处理音频相关的功能"""

    def __init__(self) -> None:
        self.last_audio_log_time: float = 0.0
        self.audio_packets_received: int = 0
        self.voice_detector = VoiceActivityDetector()
        self.AUDIO_LOG_INTERVAL: float = 5.0

    def process_audio_data(self, audio_data: bytes, session: Any) -> Tuple[bool, Optional[bytes]]:
        """处理音频数据，返回是否有语音活动和PCM数据"""
        if not audio_data or len(audio_data) < 10:
            logger.warning("收到无效的音频数据: 数据为空或长度不足")
            return False, None

        try:
            timestamp, status_flags, pcm_data = parse_audio_header(audio_data)

            # 限制音频日志输出频率
            self.audio_packets_received += 1
            current_time = time.time()

            if Config.DEBUG and current_time - self.last_audio_log_time > self.AUDIO_LOG_INTERVAL:
                logger.debug(f"音频接收统计: {self.audio_packets_received}个数据包 (过去{self.AUDIO_LOG_INTERVAL}秒)")
                self.last_audio_log_time = current_time
                self.audio_packets_received = 0

            # 检测是否有语音活动
            has_voice = self.voice_detector.detect(pcm_data)
            return has_voice, pcm_data

        except Exception as e:
            logger.error(f"处理音频头部出错: {e}")
            return False, audio_data if len(audio_data) > 2 else None


class WebSocketHandler:
    """处理WebSocket连接和消息"""

    def __init__(self) -> None:
        self.audio_processor = AudioProcessor()

    async def handle_connection(self, websocket: WebSocket) -> None:
        """处理WebSocket连接"""
        await websocket.accept()

        # 获取或创建新会话
        session_id = str(uuid.uuid4())
        logger.info(f"新WebSocket连接已建立，会话ID: {session_id}")
        
        # 获取会话对象
        session = get_session(session_id)
        session.update_activity()
        loop = asyncio.get_running_loop()

        asr_service = await self._setup_asr_service(websocket, session_id, loop)
        if not asr_service:
            return

        # Create and start pipeline
        pipeline = PipelineHandler(session, websocket)
        await pipeline.start_pipeline()

        try:
            await asr_service.start_recognition()
            await self._handle_messages(websocket, asr_service, session_id)
        except WebSocketDisconnect:
            logger.info(f"WebSocket断开连接，会话ID: {session_id}")
        except Exception as e:
            logger.error(f"WebSocket错误: {e}")
            try:
                await websocket.send_json({"type": "error", "message": f"WebSocket错误: {str(e)}"})
            except:
                pass
        finally:
            await self._cleanup(websocket, asr_service, session_id, pipeline)

    async def _setup_asr_service(self, websocket: WebSocket, session_id: str, loop: Any) -> Optional[BaseASRService]:
        """设置ASR服务"""
        asr_service = create_asr_service()
        if not asr_service:
            await websocket.send_json({"type": "error", "message": "无法创建ASR服务", "session_id": session_id})
            await websocket.close()
            return None

        session = get_session(session_id)
        if session:
            logger.info(f"设置ASR服务，会话ID: {session_id}")
            session.asr_recognizer = asr_service
            asr_service.set_websocket(websocket, loop, session_id)
            asr_service.setup_handlers()
        return asr_service

    async def _handle_messages(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """处理WebSocket消息"""
        while True:
            try:
                data = await websocket.receive()
                if "bytes" in data:
                    await self._handle_audio_data(data["bytes"], asr_service, session_id)
                elif "text" in data:
                    await self._handle_text_command(data["text"], websocket, asr_service, session_id)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"处理消息错误: {e}")
                break

    async def _handle_audio_data(self, audio_data: bytes, asr_service: BaseASRService, session_id: str) -> None:
        """处理音频数据"""
        has_voice, pcm_data = self.audio_processor.process_audio_data(audio_data, get_session(session_id))

        if pcm_data:
            session = get_session(session_id)
            if session and has_voice and (session.is_tts_active or session.is_processing_llm):
                if self.audio_processor.voice_detector.has_continuous_voice():
                    logger.info(f"检测到明显的语音输入，打断当前响应，会话ID: {session_id}")
                    session.request_interrupt()
                    self.audio_processor.voice_detector.reset()

            asr_service.feed_audio(pcm_data)

    async def _handle_text_command(self, text: str, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """处理文本命令"""
        try:
            message = json.loads(text)
            cmd_type = message.get("type")

            if cmd_type == "stop":
                await self._handle_stop_command(websocket, asr_service, session_id)
            elif cmd_type == "start":
                await asr_service.start_recognition()
            elif cmd_type == "reset":
                await self._handle_reset_command(websocket, asr_service, session_id)
            elif cmd_type == "interrupt":
                await self._handle_interrupt_command(websocket, session_id)

        except Exception as e:
            logger.error(f"处理命令错误: {e}")
            await websocket.send_json({"type": "error", "message": f"命令错误: {str(e)}"})

    async def _handle_stop_command(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """处理停止命令"""
        await asr_service.stop_recognition()
        logger.info(f"停止命令接收，停止所有TTS和LLM进程，会话ID: {session_id}")
        session = get_session(session_id)
        if session:
            session.request_interrupt()
        await websocket.send_json(
            {"type": "stop_acknowledged", "message": "所有处理已停止", "queues_cleared": True, "session_id": session_id}
        )

    async def _handle_reset_command(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """处理重置命令"""
        await asr_service.stop_recognition()
        await asyncio.sleep(1)

        new_asr_service = create_asr_service()
        if new_asr_service:
            session = get_session(session_id)
            if session:
                session.asr_recognizer = new_asr_service
                new_asr_service.set_websocket(websocket, asyncio.get_running_loop(), session_id)
                new_asr_service.setup_handlers()
                await new_asr_service.start_recognition()
        else:
            await websocket.send_json({"type": "error", "message": "无法创建新的ASR服务", "session_id": session_id})

    async def _handle_interrupt_command(self, websocket: WebSocket, session_id: str) -> None:
        """处理中断命令"""
        logger.info(f"接收到中断命令，会话ID: {session_id}")
        session = get_session(session_id)
        if session:
            session.request_interrupt()
            await websocket.send_json({"type": "interrupt_acknowledged", "session_id": session_id})
        else:
            logger.error(f"无法获取会话 {session_id}，无法处理中断命令")

    async def _cleanup(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str, pipeline: PipelineHandler) -> None:
        """清理资源"""
        if asr_service:
            try:
                await asr_service.stop_recognition()
            except Exception as e:
                logger.error(f"停止ASR服务错误: {e}")

        # Cleanup pipeline
        await pipeline.cleanup()
                
        # 移除会话
        remove_session(session_id)

        # 关闭WebSocket连接
        try:
            await websocket.close()
        except Exception as e:
            logger.error(f"关闭WebSocket连接错误: {e}")


class SessionCleaner:
    """处理会话清理任务"""

    @staticmethod
    async def cleanup_inactive_sessions() -> None:
        """定期清理不活跃的会话"""
        while True:
            try:
                await asyncio.sleep(60)
                sessions = get_all_sessions()

                inactive_session_ids = [
                    session_id
                    for session_id, state in sessions.items()
                    if state.is_inactive(timeout_seconds=Config.SESSION_TIMEOUT)
                ]

                for session_id in inactive_session_ids:
                    logger.info(f"清理不活跃会话: {session_id}")
                    try:
                        if sessions[session_id].tts_processor:
                            await sessions[session_id].tts_processor.interrupt()
                    except:
                        pass
                    remove_session(session_id)

            except Exception as e:
                logger.error(f"会话清理错误: {e}")
                await asyncio.sleep(60)


# 导出主要的处理函数
async def handle_websocket_connection(websocket: WebSocket) -> None:
    """处理WebSocket连接的主入口函数"""
    handler = WebSocketHandler()
    await handler.handle_connection(websocket)


async def process_final_transcript(websocket: WebSocket, text: str, session_id: str) -> None:
    """处理最终转录文本的主入口函数"""
    session = get_session(session_id)
    if session:
        await session.asr_queue.put(text)


async def cleanup_inactive_sessions() -> None:
    """清理不活跃会话的主入口函数"""
    await SessionCleaner.cleanup_inactive_sessions()
