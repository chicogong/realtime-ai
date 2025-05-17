import asyncio
from typing import Optional
from loguru import logger

from models.session import SessionState
from services.llm import create_llm_service
from services.tts import create_tts_service
from utils.text import split_into_sentences


class PipelineHandler:
    """Handles the processing pipeline for ASR -> LLM -> TTS"""

    def __init__(self, session: SessionState, websocket) -> None:
        self.session = session
        self.websocket = websocket
        self.llm_service = create_llm_service()
        self.tts_processor = create_tts_service(session.session_id)
        self.tts_completion_event = asyncio.Event()
        self.tts_completion_event.set()  # Initially set to allow first synthesis

    async def start_pipeline(self) -> None:
        """Start all pipeline tasks"""
        # Start pipeline tasks
        self.session.pipeline_tasks.extend([
            asyncio.create_task(self._process_asr_queue()),
            asyncio.create_task(self._process_llm_queue()),
            asyncio.create_task(self._process_tts_queue())
        ])

    async def _process_asr_queue(self) -> None:
        """Process ASR results and send to LLM queue"""
        while True:
            try:
                if self.session.is_interrupted():
                    break

                # Get ASR result from queue
                asr_result = await self.session.asr_queue.get()
                logger.info(f"ASR结果: {asr_result}")
                
                # Send stop command to frontend
                await self.websocket.send_json({
                    "type": "tts_stop",
                    "session_id": self.session.session_id
                })
                
                # Cancel current TTS task if exists
                if self.session.current_tts_task and not self.session.current_tts_task.done():
                    self.session.current_tts_task.cancel()
                    logger.info("取消当前TTS任务")
                
                # Clear TTS queue
                while not self.session.tts_queue.empty():
                    try:
                        self.session.tts_queue.get_nowait()
                        self.session.tts_queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                
                # Add to LLM queue
                await self.session.llm_queue.put(asr_result)
                
                self.session.asr_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing ASR queue: {e}")
                break

    async def _process_llm_queue(self) -> None:
        """Process LLM queue and send sentences to TTS queue"""
        while True:
            try:
                if self.session.is_interrupted():
                    break

                # Get text from LLM queue
                text = await self.session.llm_queue.get()
                
                # Cancel current LLM task if exists
                if self.session.current_llm_task and not self.session.current_llm_task.done():
                    self.session.current_llm_task.cancel()
                
                # Create new LLM task
                self.session.current_llm_task = asyncio.create_task(
                    self._process_llm_response(text)
                )
                
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
            await self.websocket.send_json({
                "type": "llm_status",
                "status": "processing",
                "session_id": self.session.session_id
            })

            collected_response = ""
            text_buffer = ""
            current_sentence = ""
            
            async for chunk in self.llm_service.generate_response(text):
                if self.session.is_interrupted():
                    break

                collected_response += chunk
                text_buffer += chunk
                current_sentence += chunk
                
                # Send streaming subtitle
                await self.websocket.send_json({
                    "type": "subtitle",
                    "content": current_sentence,
                    "is_complete": False,
                    "session_id": self.session.session_id
                })
                
                # Check for sentence endings
                if any(end in current_sentence for end in ["。", "！", "？", ".", "!", "?"]):
                    # Split into sentences
                    sentences = split_into_sentences(current_sentence)
                    if sentences:
                        # Process all complete sentences
                        for sentence in sentences[:-1]:  # Process all but the last sentence
                            logger.info(f"LLM生成句子: {sentence}")
                            # Send complete sentence subtitle
                            await self.websocket.send_json({
                                "type": "subtitle",
                                "content": sentence,
                                "is_complete": True,
                                "session_id": self.session.session_id
                            })
                            # Send to TTS queue
                            await self.session.tts_queue.put(sentence)
                        
                        # Keep the last sentence in buffer if it's not complete
                        last_sentence = sentences[-1]
                        if current_sentence.endswith(last_sentence):
                            logger.info(f"LLM生成句子: {last_sentence}")
                            # Send complete sentence subtitle
                            await self.websocket.send_json({
                                "type": "subtitle",
                                "content": last_sentence,
                                "is_complete": True,
                                "session_id": self.session.session_id
                            })
                            # Send to TTS queue
                            await self.session.tts_queue.put(last_sentence)
                            current_sentence = ""
                        else:
                            current_sentence = current_sentence[current_sentence.rfind(last_sentence) + len(last_sentence):]

                # Send streaming response
                await self.websocket.send_json({
                    "type": "llm_response",
                    "content": collected_response,
                    "is_complete": False,
                    "session_id": self.session.session_id
                })

            # Process any remaining text
            if current_sentence and not self.session.is_interrupted():
                sentences = split_into_sentences(current_sentence)
                for sentence in sentences:
                    logger.info(f"LLM生成句子: {sentence}")
                    # Send complete sentence subtitle
                    await self.websocket.send_json({
                        "type": "subtitle",
                        "content": sentence,
                        "is_complete": True,
                        "session_id": self.session.session_id
                    })
                    # Send to TTS queue
                    await self.session.tts_queue.put(sentence)

            if not self.session.is_interrupted():
                await self.websocket.send_json({
                    "type": "llm_response",
                    "content": collected_response,
                    "is_complete": True,
                    "session_id": self.session.session_id
                })

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
                
                # Get sentence from TTS queue
                sentence = await self.session.tts_queue.get()
                logger.info(f"TTS处理句子: {sentence}")
                
                # Clear the event to prevent next sentence from starting
                self.tts_completion_event.clear()
                
                # Create new TTS task
                self.session.current_tts_task = asyncio.create_task(
                    self._synthesize_speech(sentence)
                )
                
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
            logger.info(f"开始TTS合成: {text}")
            
            # Send TTS start message
            await self.websocket.send_json({
                "type": "tts_start",
                "format": "pcm",
                "session_id": self.session.session_id
            })
            
            await self.tts_processor.synthesize_text(text, self.websocket)
            logger.info(f"TTS合成完成: {text}")
            
            # Send TTS end message
            await self.websocket.send_json({
                "type": "tts_end",
                "session_id": self.session.session_id
            })

        except asyncio.CancelledError:
            logger.info("TTS任务被取消")
            # Send TTS stop message
            await self.websocket.send_json({
                "type": "tts_stop",
                "session_id": self.session.session_id
            })
            pass
        except Exception as e:
            logger.error(f"Error synthesizing speech: {e}")
        finally:
            self.session.is_tts_active = False
            # Set the event to allow next sentence to start
            self.tts_completion_event.set()

    async def cleanup(self) -> None:
        """Cleanup pipeline resources"""
        self.session._cancel_pipeline_tasks()
        if self.tts_processor:
            await self.tts_processor.close() 