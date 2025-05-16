import asyncio
import json
import struct
import time
from typing import Any, Dict, Optional, Tuple, List

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from config import Config
from models.session import get_all_sessions, get_session, remove_session
from services.asr import create_asr_service
from services.llm import create_llm_service
from services.tts import close_all_tts_services, create_tts_service
from utils.audio import VoiceActivityDetector, parse_audio_header
from utils.text import split_into_sentences


class AudioProcessor:
    """处理音频相关的功能"""

    def __init__(self):
        self.last_audio_log_time = 0
        self.audio_packets_received = 0
        self.voice_detector = VoiceActivityDetector()
        self.AUDIO_LOG_INTERVAL = 5.0

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


class LLMProcessor:
    """处理LLM相关的功能"""

    @staticmethod
    async def process_response(websocket: WebSocket, text: str, session_id: str) -> None:
        """处理LLM响应"""
        session = get_session(session_id)
        session.clear_interrupt()
        session.is_processing_llm = True
        session.update_activity()

        try:
            logger.info(f"LLM处理文本: '{text}' [sid:{session_id}]")

            # 检查WebSocket连接状态
            if websocket.client_state.value == 3:  # 3 表示连接已关闭
                logger.info("WebSocket连接已关闭，停止LLM处理")
                return

            await websocket.send_json({"type": "llm_status", "status": "processing", "session_id": session_id})

            tts_processor = await LLMProcessor._setup_services(websocket, session_id)
            if not tts_processor:
                return

            session.tts_processor = tts_processor
            llm_service = create_llm_service()
            if not llm_service:
                await websocket.send_json({"type": "error", "message": "无法创建LLM服务", "session_id": session_id})
                return

            await LLMProcessor._process_llm_stream(websocket, llm_service, text, tts_processor, session_id)

        except Exception as e:
            logger.error(f"LLM处理错误: {e}")
            # 只有在连接未关闭时才发送错误消息
            if websocket.client_state.value != 3:
                try:
                    await websocket.send_json(
                        {"type": "error", "message": f"LLM错误: {str(e)}", "session_id": session_id}
                    )
                except Exception as send_error:
                    logger.error(f"发送错误消息失败: {send_error}")
        finally:
            session.is_processing_llm = False
            session.is_tts_active = False
            session.response_stream = None

    @staticmethod
    async def _setup_services(websocket: WebSocket, session_id: str) -> Optional[Any]:
        """设置TTS服务"""
        tts_processor = create_tts_service(session_id)
        if not tts_processor:
            await websocket.send_json({"type": "error", "message": "无法创建TTS服务", "session_id": session_id})
            return None
        return tts_processor

    @staticmethod
    async def _process_llm_stream(
        websocket: WebSocket,
        llm_service: Any,
        text: str,
        tts_processor: Any,
        session_id: str
    ) -> None:
        """处理LLM流式响应"""
        session = get_session(session_id)
        session.response_stream = llm_service

        collected_response = ""
        text_buffer = ""
        sentences_queue = []
        first_sentence_processed = False

        try:
            async for chunk in llm_service.generate_response(text):
                if session.is_interrupted():
                    logger.info(f"检测到中断请求，停止LLM流 [sid:{session_id}]")
                    break

                # 检查WebSocket连接状态
                if websocket.client_state.value == 3:  # 3 表示连接已关闭
                    logger.info("WebSocket连接已关闭，停止LLM流处理")
                    break

                collected_response += chunk
                text_buffer += chunk

                if any(end in text_buffer for end in ["。", "！", "？", ".", "!", "?"]):
                    new_sentences = split_into_sentences(text_buffer)
                    if new_sentences:
                        sentences_queue.extend(new_sentences)

                        if not first_sentence_processed and len(sentences_queue) > 0:
                            first_sentence = sentences_queue.pop(0)
                            if not session.is_interrupted():
                                await tts_processor.synthesize_text(first_sentence, websocket, is_first=True)
                                first_sentence_processed = True

                        while len(sentences_queue) > 0:
                            if session.is_interrupted():
                                break
                            sentence = sentences_queue.pop(0)
                            await tts_processor.synthesize_text(sentence, websocket, is_first=False)

                        last_sentence = new_sentences[-1]
                        if text_buffer.endswith(last_sentence):
                            text_buffer = ""
                        else:
                            text_buffer = text_buffer[text_buffer.rfind(last_sentence) + len(last_sentence) :]

                if not session.is_interrupted():
                    try:
                        await websocket.send_json(
                            {
                                "type": "llm_response",
                                "content": collected_response,
                                "is_complete": False,
                                "session_id": session_id,
                            }
                        )
                    except Exception as e:
                        if "close message has been sent" in str(e):
                            logger.info("WebSocket连接已关闭，停止发送LLM响应")
                            break
                        raise e

            await LLMProcessor._handle_remaining_text(
                websocket,
                text_buffer,
                sentences_queue,
                tts_processor,
                session_id,
                first_sentence_processed,
                collected_response,
            )

        except asyncio.TimeoutError:
            logger.error("LLM流式处理超时")
            if websocket.client_state.value != 3:
                try:
                    await websocket.send_json({"type": "error", "message": "LLM流式处理超时", "session_id": session_id})
                except Exception as send_error:
                    logger.error(f"发送超时错误消息失败: {send_error}")

    @staticmethod
    async def _handle_remaining_text(
        websocket: WebSocket,
        text_buffer: str,
        sentences_queue: List[str],
        tts_processor: Any,
        session_id: str,
        first_sentence_processed: bool,
        collected_response: str,
    ) -> None:
        """处理剩余的文本"""
        session = get_session(session_id)

        if text_buffer and not session.is_interrupted():
            sentences_queue.append(text_buffer)

        while len(sentences_queue) > 0 and not session.is_interrupted():
            sentence = sentences_queue.pop(0)
            await tts_processor.synthesize_text(sentence, websocket, is_first=not first_sentence_processed)
            first_sentence_processed = True

        if collected_response and not session.is_interrupted():
            await websocket.send_json(
                {"type": "llm_response", "content": collected_response, "is_complete": True, "session_id": session_id}
            )
            logger.info(f"LLM响应完成: '{collected_response}'")
        elif session.is_interrupted():
            logger.info("LLM处理被中断")
            await websocket.send_json(
                {
                    "type": "llm_response",
                    "content": "对话被中断",
                    "is_complete": True,
                    "was_interrupted": True,
                    "session_id": session_id,
                }
            )
        else:
            logger.warning("未收集到任何LLM响应")
            await websocket.send_json({"type": "error", "message": "LLM未生成任何响应", "session_id": session_id})


class WebSocketHandler:
    """处理WebSocket连接和消息"""

    def __init__(self) -> None:
        self.audio_processor = AudioProcessor()

    async def handle_connection(self, websocket: WebSocket) -> None:
        """处理WebSocket连接"""
        await websocket.accept()

        loop = asyncio.get_running_loop()
        session_id = get_session(None).session_id
        logger.info(f"新WebSocket连接已建立，会话ID: {session_id}")

        session = get_session(session_id)
        asr_service = await self._setup_asr_service(websocket, session_id, loop)
        if not asr_service:
            return

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
            await self._cleanup(websocket, asr_service, session_id)

    async def _setup_asr_service(self, websocket: WebSocket, session_id: str, loop: Any) -> Optional[Any]:
        """设置ASR服务"""
        asr_service = create_asr_service()
        if not asr_service:
            await websocket.send_json({"type": "error", "message": "无法创建ASR服务", "session_id": session_id})
            await websocket.close()
            return None

        session = get_session(session_id)
        session.asr_recognizer = asr_service
        asr_service.set_websocket(websocket, loop, session_id)
        asr_service.setup_handlers()
        return asr_service

    async def _handle_messages(self, websocket: WebSocket, asr_service: Any, session_id: str) -> None:
        """处理WebSocket消息"""
        while True:
            data = await websocket.receive()

            if "bytes" in data:
                await self._handle_audio_data(data["bytes"], asr_service, session_id)
            elif "text" in data:
                await self._handle_text_command(data["text"], websocket, asr_service, session_id)

    async def _handle_audio_data(self, audio_data: bytes, asr_service: Any, session_id: str) -> None:
        """处理音频数据"""
        has_voice, pcm_data = self.audio_processor.process_audio_data(audio_data, get_session(session_id))

        if pcm_data:
            session = get_session(session_id)
            if has_voice and (session.is_tts_active or session.is_processing_llm):
                if self.audio_processor.voice_detector.has_continuous_voice():
                    logger.info(f"检测到明显的语音输入，打断当前响应，会话ID: {session_id}")
                    await self._stop_tts_and_clear_queues(websocket, session_id)
                    self.audio_processor.voice_detector.reset()

            asr_service.feed_audio(pcm_data)

    async def _handle_text_command(self, text: str, websocket: WebSocket, asr_service: Any, session_id: str) -> None:
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

    async def _handle_stop_command(self, websocket: WebSocket, asr_service: Any, session_id: str) -> None:
        """处理停止命令"""
        await asr_service.stop_recognition()
        logger.info(f"停止命令接收，停止所有TTS和LLM进程，会话ID: {session_id}")
        await self._stop_tts_and_clear_queues(websocket, session_id)
        await websocket.send_json(
            {"type": "stop_acknowledged", "message": "所有处理已停止", "queues_cleared": True, "session_id": session_id}
        )

    async def _handle_reset_command(self, websocket: WebSocket, asr_service: Any, session_id: str) -> None:
        """处理重置命令"""
        await asr_service.stop_recognition()
        await asyncio.sleep(1)

        new_asr_service = create_asr_service()
        if new_asr_service:
            session = get_session(session_id)
            session.asr_recognizer = new_asr_service
            new_asr_service.set_websocket(websocket, asyncio.get_running_loop(), session_id)
            new_asr_service.setup_handlers()
            await new_asr_service.start_recognition()
            asr_service = new_asr_service
        else:
            await websocket.send_json({"type": "error", "message": "无法创建新的ASR服务", "session_id": session_id})

    async def _handle_interrupt_command(self, websocket: WebSocket, session_id: str) -> None:
        """处理中断命令"""
        logger.info(f"接收到中断命令，会话ID: {session_id}")
        session = get_session(session_id)
        session.request_interrupt()
        await self._stop_tts_and_clear_queues(websocket, session_id)
        await websocket.send_json({"type": "interrupt_acknowledged", "session_id": session_id})

    async def _stop_tts_and_clear_queues(self, websocket: WebSocket, session_id: str) -> None:
        """停止TTS响应并清空所有队列"""
        session = get_session(session_id)
        session.request_interrupt()

        if session.tts_processor:
            await session.tts_processor.interrupt()

        await websocket.send_json({"type": "tts_stop", "session_id": session_id})

    async def _cleanup(self, websocket: WebSocket, asr_service: Any, session_id: str) -> None:
        """清理资源"""
        if asr_service:
            try:
                await asr_service.stop_recognition()
            except:
                pass

        session = get_session(session_id)
        try:
            if session.tts_processor:
                await session.tts_processor.close()
        except:
            pass

        remove_session(session_id)

        try:
            await websocket.close()
        except:
            pass


class SessionCleaner:
    """处理会话清理任务"""

    @staticmethod
    async def cleanup_inactive_sessions():
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
    await LLMProcessor.process_response(websocket, text, session_id)


async def cleanup_inactive_sessions() -> None:
    """清理不活跃会话的主入口函数"""
    await SessionCleaner.cleanup_inactive_sessions()
