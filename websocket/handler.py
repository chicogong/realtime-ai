import asyncio
import json
import uuid
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from services.asr import BaseASRService, create_asr_service
from session import get_session, remove_session
from utils.audio import AudioProcessor
from websocket.models import parse_command
from websocket.pipeline import PipelineHandler


class WebSocketHandler:
    """Handles WebSocket connections and message processing"""

    def __init__(self) -> None:
        self.audio_processor = AudioProcessor()

    async def handle_connection(self, websocket: WebSocket) -> None:
        """Handle WebSocket connection lifecycle"""
        await websocket.accept()

        # Create new session
        session_id = str(uuid.uuid4())
        logger.info(f"New WebSocket connection established, session ID: {session_id}")

        # Get session object and update activity
        session = get_session(session_id)
        session.update_activity()
        loop = asyncio.get_running_loop()

        # Setup ASR service
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
            logger.info(f"WebSocket connection closed, session ID: {session_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": f"WebSocket error: {str(e)}",
                    "session_id": session_id
                })
            except Exception:
                pass
        finally:
            await self._cleanup(websocket, asr_service, session_id, pipeline)

    async def _setup_asr_service(self, websocket: WebSocket, session_id: str, loop: Any) -> Optional[BaseASRService]:
        """Setup ASR service for the session"""
        asr_service = create_asr_service()
        if not asr_service:
            await websocket.send_json({
                "type": "error",
                "message": "Could not create ASR service",
                "session_id": session_id
            })
            await websocket.close()
            return None

        session = get_session(session_id)
        if session:
            logger.info(f"Setting up ASR service, session ID: {session_id}")
            session.asr_recognizer = asr_service
            asr_service.set_websocket(websocket, loop, session_id)
            # Inject callback to avoid circular import
            asr_service.set_transcript_callback(process_final_transcript)
            asr_service.setup_handlers()
        return asr_service

    async def _handle_messages(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """Process incoming WebSocket messages"""
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
                logger.error(f"Error processing message: {e}")
                break

    async def _handle_audio_data(self, audio_data: bytes, asr_service: BaseASRService, session_id: str) -> None:
        """Process audio data and check for voice activity"""
        # Get session once and reuse
        session = get_session(session_id)
        has_voice, pcm_data = self.audio_processor.process_audio_data(audio_data, session)

        if pcm_data:
            # Check if voice should interrupt ongoing processing
            if session and has_voice and (session.is_tts_active or session.is_processing_llm):
                if self.audio_processor.voice_detector.has_continuous_voice():
                    logger.info(f"Detected significant voice input, interrupting current response, session ID: {session_id}")
                    session.request_interrupt()
                    self.audio_processor.voice_detector.reset()

            # Feed audio to ASR
            asr_service.feed_audio(pcm_data)

    async def _handle_text_command(self, text: str, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """Process text commands from client"""
        try:
            message = json.loads(text)

            # Validate command using Pydantic model
            command = parse_command(message)
            if not command:
                logger.warning(f"Invalid or unknown command: {message.get('type')}")
                await websocket.send_json({
                    "type": "error",
                    "message": f"Invalid command type: {message.get('type')}",
                    "session_id": session_id
                })
                return

            # Route commands to appropriate handlers
            command_handlers = {
                "stop": self._handle_stop_command,
                "start": lambda ws, asr, sid: asr.start_recognition(),
                "reset": self._handle_reset_command,
                "interrupt": self._handle_interrupt_command
            }

            handler = command_handlers.get(command.type)
            if handler:
                await handler(websocket, asr_service, session_id)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in command: {e}")
            await websocket.send_json({
                "type": "error",
                "message": "Invalid JSON format",
                "session_id": session_id
            })
        except Exception as e:
            logger.error(f"Command processing error: {e}")
            await websocket.send_json({
                "type": "error",
                "message": f"Command error: {str(e)}",
                "session_id": session_id
            })

    async def _handle_stop_command(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """Handle stop command - stop all processing"""
        await asr_service.stop_recognition()
        logger.info(f"Stop command received, stopping all TTS and LLM processes, session ID: {session_id}")

        session = get_session(session_id)
        if session:
            session.request_interrupt()

        await websocket.send_json({
            "type": "stop_acknowledged",
            "message": "All processing stopped",
            "queues_cleared": True,
            "session_id": session_id
        })

    async def _handle_reset_command(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """Handle reset command - recreate ASR service"""
        await asr_service.stop_recognition()
        await asyncio.sleep(1)

        new_asr_service = create_asr_service()
        if new_asr_service:
            session = get_session(session_id)
            if session:
                session.asr_recognizer = new_asr_service
                new_asr_service.set_websocket(websocket, asyncio.get_running_loop(), session_id)
                # Inject callback to avoid circular import
                new_asr_service.set_transcript_callback(process_final_transcript)
                new_asr_service.setup_handlers()
                await new_asr_service.start_recognition()
        else:
            await websocket.send_json({
                "type": "error",
                "message": "Could not create new ASR service",
                "session_id": session_id
            })

    async def _handle_interrupt_command(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str) -> None:
        """Handle interrupt command - stop current processing but keep connection"""
        logger.info(f"Interrupt command received, session ID: {session_id}")

        session = get_session(session_id)
        if session:
            session.request_interrupt()
            await websocket.send_json({
                "type": "interrupt_acknowledged",
                "session_id": session_id
            })
        else:
            logger.error(f"Cannot get session {session_id}, unable to process interrupt command")

    async def _cleanup(self, websocket: WebSocket, asr_service: BaseASRService, session_id: str, pipeline: PipelineHandler) -> None:
        """Clean up resources when connection ends"""
        # Stop ASR service
        if asr_service:
            try:
                await asr_service.stop_recognition()
            except Exception as e:
                logger.error(f"Error stopping ASR service: {e}")

        # Clean up pipeline resources
        await pipeline.cleanup()

        # Remove session
        remove_session(session_id)

        # Close WebSocket connection
        try:
            await websocket.close()
        except Exception as e:
            logger.error(f"Error closing WebSocket connection: {e}")


async def handle_websocket_connection(websocket: WebSocket) -> None:
    """Entry point for WebSocket connection handling"""
    handler = WebSocketHandler()
    await handler.handle_connection(websocket)


async def process_final_transcript(websocket: WebSocket, text: str, session_id: str) -> None:
    """Process final speech recognition result"""
    if not text.strip():
        return

    logger.info(f"Processing final recognition result: '{text}'")
    session = get_session(session_id)

    # Add recognition result to ASR queue
    await session.asr_queue.put(text)
