import asyncio
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from config import Config
from session import get_session, remove_session
from services.asr import create_asr_service, BaseASRService
from utils.audio import AudioProcessor
from websocket.pipeline import PipelineHandler


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


async def handle_websocket_connection(websocket: WebSocket) -> None:
    """WebSocket连接处理入口点"""
    handler = WebSocketHandler()
    await handler.handle_connection(websocket)


async def process_final_transcript(websocket: WebSocket, text: str, session_id: str) -> None:
    """处理最终的语音识别结果"""
    if not text.strip():
        return
        
    logger.info(f"处理最终识别结果: '{text}'")
    session = get_session(session_id)
    
    # 将识别结果添加到ASR队列
    await session.asr_queue.put(text)
