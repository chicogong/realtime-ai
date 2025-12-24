import asyncio

from fastapi import WebSocket
from loguru import logger

from services.llm import create_llm_service
from services.tts import create_tts_service
from session import SessionState
from utils.text import process_streaming_text


class PipelineHandler:
    """Handles the processing pipeline for ASR -> LLM -> TTS"""

    def __init__(self, session: SessionState, websocket: WebSocket) -> None:
        self.session = session
        self.websocket = websocket
        self.llm_service = create_llm_service()
        self.tts_processor = create_tts_service(session.session_id)
        self.tts_completion_event = asyncio.Event()
        self.tts_completion_event.set()  # Initially set to allow first synthesis

    async def start_pipeline(self) -> None:
        """Start all pipeline processing tasks"""
        self.session.pipeline_tasks.extend(
            [
                asyncio.create_task(self._process_asr_queue()),
                asyncio.create_task(self._process_llm_queue()),
                asyncio.create_task(self._process_tts_queue()),
            ]
        )

    async def _process_asr_queue(self) -> None:
        """Process ASR results and send to LLM queue"""
        while True:
            try:
                if self.session.is_interrupted():
                    break

                asr_result = await self.session.asr_queue.get()
                logger.info(f"ASR result: {asr_result}")

                await self._cancel_tts_tasks()
                await self._send_websocket_message("tts_stop")
                await self.session.llm_queue.put(asr_result)
                self.session.asr_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing ASR queue: {e}")
                break

    async def _cancel_tts_tasks(self) -> None:
        """Cancel TTS tasks and clear queue"""
        if self.session.current_tts_task and not self.session.current_tts_task.done():
            self.session.current_tts_task.cancel()
            logger.info("Cancelling current TTS task")

        # Clear TTS queue - use bounded loop for efficiency
        items_to_clear = self.session.tts_queue.qsize()
        for _ in range(items_to_clear):
            try:
                self.session.tts_queue.get_nowait()
                self.session.tts_queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def _process_llm_queue(self) -> None:
        """Process LLM queue and send sentences to TTS queue"""
        while True:
            try:
                if self.session.is_interrupted():
                    break

                text = await self.session.llm_queue.get()

                # Cancel current LLM task if exists
                if self.session.current_llm_task and not self.session.current_llm_task.done():
                    self.session.current_llm_task.cancel()

                # Create new LLM task
                self.session.current_llm_task = asyncio.create_task(self._process_llm_response(text))

                self.session.llm_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing LLM queue: {e}")
                break

    async def _process_llm_response(self, text: str) -> None:
        """Process LLM response and send sentences to TTS queue"""
        try:
            if not self.llm_service:
                logger.error("LLM service not available")
                return

            self.session.is_processing_llm = True
            await self._send_websocket_message("llm_status", status="processing")

            collected_response = ""
            current_subtitle = ""
            sentence_buffer = ""

            async for chunk in self.llm_service.generate_response(text):
                if self.session.is_interrupted():
                    break

                collected_response += chunk
                current_subtitle += chunk

                # Process streaming text and extract complete sentences
                complete_sentences, sentence_buffer = process_streaming_text(chunk, sentence_buffer)

                # Update subtitle in real-time
                await self._send_websocket_message("subtitle", content=current_subtitle, is_complete=False)

                # Process complete sentences for TTS
                for sentence in complete_sentences:
                    logger.info(f"LLM generated sentence: {sentence}")
                    await self._send_websocket_message("subtitle", content=sentence, is_complete=True)
                    await self.session.tts_queue.put(sentence)

                # Send streaming LLM response
                await self._send_websocket_message("llm_response", content=collected_response, is_complete=False)

            # Process remaining text if any
            if sentence_buffer and not self.session.is_interrupted():
                logger.info(f"LLM final sentence: {sentence_buffer}")
                await self._send_websocket_message("subtitle", content=sentence_buffer, is_complete=True)
                await self.session.tts_queue.put(sentence_buffer)

            # Send final complete response
            if not self.session.is_interrupted():
                await self._send_websocket_message("llm_response", content=collected_response, is_complete=True)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error processing LLM response: {e}")
        finally:
            self.session.is_processing_llm = False

    async def _process_tts_queue(self) -> None:
        """Process TTS queue and synthesize speech"""
        while True:
            try:
                if self.session.is_interrupted():
                    break

                # Wait for previous TTS to complete
                await self.tts_completion_event.wait()

                sentence = await self.session.tts_queue.get()
                logger.info(f"TTS processing sentence: {sentence}")

                # Clear the event to prevent next sentence from starting
                self.tts_completion_event.clear()

                # Create new TTS task
                self.session.current_tts_task = asyncio.create_task(self._synthesize_speech(sentence))

                self.session.tts_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing TTS queue: {e}")
                break

    async def _synthesize_speech(self, text: str) -> None:
        """Synthesize speech for a sentence"""
        try:
            if not self.tts_processor:
                logger.error("TTS processor not available")
                return

            self.session.is_tts_active = True
            logger.info(f"Starting TTS synthesis: {text}")

            await self._send_websocket_message("tts_start", format="pcm")
            await self.tts_processor.synthesize_text(text, self.websocket)
            await self._send_websocket_message("tts_end")

            logger.info(f"TTS synthesis completed: {text}")

        except asyncio.CancelledError:
            logger.info("TTS task cancelled")
            await self._send_websocket_message("tts_stop")
        except Exception as e:
            logger.error(f"Error synthesizing speech: {e}")
        finally:
            self.session.is_tts_active = False
            # Set event to allow next sentence to start
            self.tts_completion_event.set()

    async def _send_websocket_message(self, message_type: str, **data: object) -> None:
        """Send formatted message through websocket"""
        message = {"type": message_type, "session_id": self.session.session_id, **data}
        await self.websocket.send_json(message)

    async def cleanup(self) -> None:
        """Cleanup pipeline resources"""
        self.session._cancel_pipeline_tasks()
        if self.tts_processor:
            await self.tts_processor.close()
