import asyncio
import json
import os
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import azure.cognitiveservices.speech as speechsdk
import logging
from dotenv import load_dotenv
import uuid
import threading
import time
import struct
import openai
import async_timeout
from openai import AsyncOpenAI
import base64
from collections import deque
import httpx

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Azure Speech SDK configuration
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

# Azure TTS configuration
AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

# Configure OpenAI client
if OPENAI_BASE_URL:
    openai_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL
    )
else:
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
    logger.error("Azure Speech credentials not found. Please set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION environment variables.")

if not OPENAI_API_KEY:
    logger.error("OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
else:
    logger.info(f"Using OpenAI model: {OPENAI_MODEL}")
    if OPENAI_BASE_URL:
        logger.info(f"Using custom OpenAI base URL: {OPENAI_BASE_URL}")

class AudioDiagnostics:
    """Helper class to diagnose audio issues"""
    def __init__(self):
        self.total_bytes = 0
        self.chunks_received = 0
        self.last_report_time = time.time()
        self.report_interval = 5  # seconds
        
    def record_chunk(self, chunk):
        """Record information about an audio chunk"""
        self.total_bytes += len(chunk)
        self.chunks_received += 1
        
        # Report stats periodically
        current_time = time.time()
        if current_time - self.last_report_time > self.report_interval:
            self.report_stats()
            self.last_report_time = current_time
            
    def report_stats(self):
        """Report audio statistics"""
        if self.chunks_received == 0:
            logger.warning("No audio chunks received in the last interval")
            return
            
        avg_chunk_size = self.total_bytes / self.chunks_received
        
        # Check if audio data seems valid
        if avg_chunk_size < 10:
            logger.warning(f"Audio chunks seem very small (avg {avg_chunk_size:.2f} bytes)")
        
        logger.info(f"Audio stats: {self.chunks_received} chunks, {self.total_bytes} bytes total, {avg_chunk_size:.2f} bytes avg")
        
        # Analyze first few bytes of first chunk to check format if we have chunks
        if self.chunks_received > 0 and hasattr(self, 'first_chunk') and self.first_chunk:
            self.analyze_audio_format(self.first_chunk)
            
        # Reset counters for next interval
        self.total_bytes = 0
        self.chunks_received = 0
    
    def save_first_chunk(self, chunk):
        """Save first chunk for format analysis"""
        if not hasattr(self, 'first_chunk') or not self.first_chunk:
            self.first_chunk = chunk
            self.analyze_audio_format(chunk)
    
    def analyze_audio_format(self, chunk):
        """Try to detect audio format issues"""
        if len(chunk) < 10:
            logger.warning("Audio chunk too small to analyze format")
            return
            
        # Check if data looks like PCM (should have variation in values)
        try:
            # Try to interpret as 16-bit PCM
            if len(chunk) >= 20:  # Get at least 10 samples
                pcm_samples = struct.unpack(f"<{len(chunk)//2}h", chunk[:20])
                
                # Check amplitude variation
                min_val = min(pcm_samples)
                max_val = max(pcm_samples)
                if max_val - min_val < 100:
                    logger.warning(f"Low audio amplitude variation: min={min_val}, max={max_val}. Check if microphone is working")
                    
                # Check if all zero (silence)
                if max_val == 0 and min_val == 0:
                    logger.warning("Audio appears to be silence (all zeros)")
                    
                logger.info(f"Audio seems to be PCM format with amplitude range: {min_val} to {max_val}")
        except Exception as e:
            logger.warning(f"Failed to analyze audio format: {e}")

class AzureStreamingRecognizer:
    def __init__(self, subscription_key, region, language="zh-CN"):
        self.subscription_key = subscription_key
        self.region = region
        self.language = language
        self.push_stream = None
        self.recognizer = None
        self.websocket = None
        self.session_id = str(uuid.uuid4())
        self.loop = None
        self.is_recognizing = False
        self.audio_diagnostics = AudioDiagnostics()
        self._setup_recognizer()
        
    def _setup_recognizer(self):
        # Create push stream
        self.push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        
        # Create speech configuration
        speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription_key, region=self.region)
        speech_config.speech_recognition_language = self.language
        
        # # Set streaming behavior options
        # speech_config.set_property(
        #     speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "Lexical"
        # )
        
        # # Shorter silence timeouts for more responsive experience
        # speech_config.set_property(
        #     speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "2000"
        # )
        # speech_config.set_property(
        #     speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "800"
        # )
        
        # Enable both dictation and conversation modes for best results with Chinese
        speech_config.enable_dictation()
        
        # Log audio format expected by Azure
        logger.info(f"Azure expects audio format: 16-bit PCM, 16kHz, mono")
        
        # Streaming recognizer
        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, 
            audio_config=audio_config)
        
        # For tracking the last partial result
        self.last_partial_result = ""
        
    def set_websocket(self, websocket, loop):
        """Set the WebSocket connection and event loop for sending results"""
        self.websocket = websocket
        self.loop = loop
        
    def setup_handlers(self):
        """Set up event handlers for speech recognition"""
        # Recognizing event (partial results)
        self.recognizer.recognizing.connect(self._on_recognizing)
            
        # Recognized event (final results)
        self.recognizer.recognized.connect(self._on_recognized)
            
        # Errors and cancellation
        self.recognizer.canceled.connect(self._on_canceled)
        self.recognizer.session_stopped.connect(self._on_session_stopped)
        
        # Speech start/end detection for better diagnostics
        self.recognizer.session_started.connect(self._on_session_started)
        self.recognizer.speech_start_detected.connect(self._on_speech_start_detected)
        self.recognizer.speech_end_detected.connect(self._on_speech_end_detected)
    
    def _on_session_started(self, evt):
        """Handle session started event"""
        logger.info(f"SESSION STARTED: {evt}")
        
    def _on_speech_start_detected(self, evt):
        """Handle speech start detection"""
        logger.info(f"SPEECH START DETECTED")
        
    def _on_speech_end_detected(self, evt):
        """Handle speech end detection"""
        logger.info(f"SPEECH END DETECTED")
    
    def _on_recognizing(self, evt):
        """Handle partial recognition results"""
        text = evt.result.text
        logger.info(f"RECOGNIZING: '{text}'")
        
        # Save the last partial result if it's not empty
        if text.strip():
            self.last_partial_result = text
            
        if self.websocket and self.loop and text.strip():  # Only send non-empty results
            async def send_partial():
                await self.websocket.send_json({
                    "type": "partial_transcript",
                    "content": text,
                    "session_id": self.session_id
                })
            
            asyncio.run_coroutine_threadsafe(send_partial(), self.loop)
    
    def _on_recognized(self, evt):
        """Handle final recognition results"""
        text = evt.result.text
        logger.info(f"RECOGNIZED: '{text}'")
        
        # Only process non-empty results to avoid UI clutter
        if self.websocket and self.loop and text.strip():
            async def process_and_send_final():
                await self.websocket.send_json({
                    "type": "final_transcript",
                    "content": text,
                    "session_id": self.session_id
                })
                
                # Send to LLM for processing if the text is not empty
                if text.strip():
                    await process_with_llm(self.websocket, text, self.session_id)
            
            asyncio.run_coroutine_threadsafe(process_and_send_final(), self.loop)
            
            # Clear the last partial result as we got a final result
            self.last_partial_result = ""
        elif not text.strip():
            logger.info("Empty recognition result - no text found in audio")
    
    def _on_canceled(self, evt):
        """Handle cancellation and errors"""
        logger.error(f"CANCELED: {evt.result.reason}")
        if evt.result.reason == speechsdk.CancellationReason.Error:
            error_details = evt.result.cancellation_details.error_details
            logger.error(f"Error details: {error_details}")
        
        if self.websocket and self.loop:
            async def send_error():
                error_message = "Error: "
                if evt.result.reason == speechsdk.CancellationReason.Error:
                    error_message += evt.result.cancellation_details.error_details
                else:
                    error_message += str(evt.result.reason)
                
                await self.websocket.send_json({
                    "type": "error",
                    "message": error_message,
                    "session_id": self.session_id
                })
            
            asyncio.run_coroutine_threadsafe(send_error(), self.loop)
        
        self.is_recognizing = False
    
    def _on_session_stopped(self, evt):
        """Handle session stopped events"""
        logger.info("Session stopped")
        
        # If we have a partial result but no final result was generated,
        # use the last partial result as a final result
        if self.websocket and self.loop and self.last_partial_result.strip():
            async def send_final_from_partial():
                logger.info(f"Using last partial result as final: '{self.last_partial_result}'")
                
                # Send the last partial result as a final result
                await self.websocket.send_json({
                    "type": "final_transcript",
                    "content": self.last_partial_result,
                    "session_id": self.session_id
                })
                
                # Process with LLM
                await process_with_llm(self.websocket, self.last_partial_result, self.session_id)
                
                # Clear the last partial result
                self.last_partial_result = ""
            
            asyncio.run_coroutine_threadsafe(send_final_from_partial(), self.loop)
        
        if self.websocket and self.loop:
            async def send_status():
                await self.websocket.send_json({
                    "type": "status",
                    "status": "stopped",
                    "session_id": self.session_id
                })
            
            asyncio.run_coroutine_threadsafe(send_status(), self.loop)
        
        self.is_recognizing = False
    
    def feed_audio(self, audio_chunk):
        """Process incoming PCM audio chunk"""
        if not audio_chunk or len(audio_chunk) == 0:
            logger.warning("Received empty audio chunk")
            return
            
        # Diagnose audio data
        self.audio_diagnostics.record_chunk(audio_chunk)
        self.audio_diagnostics.save_first_chunk(audio_chunk)
        
        if self.push_stream:
            self.push_stream.write(audio_chunk)
    
    async def start_continuous_recognition(self):
        """Start continuous recognition"""
        if self.is_recognizing:
            logger.info("Recognition already in progress, ignoring start request")
            return
            
        logger.info("Starting continuous recognition")
        if self.websocket:
            await self.websocket.send_json({
                "type": "status",
                "status": "listening",
                "session_id": self.session_id
            })
        
        # Use thread to avoid blocking the event loop with synchronous call
        def start_recognition_thread():
            try:
                self.recognizer.start_continuous_recognition()
                self.is_recognizing = True
                logger.info("Continuous recognition started successfully")
            except Exception as e:
                logger.error(f"Failed to start recognition: {e}")
                self.is_recognizing = False
                
                # Notify about the error
                if self.websocket and self.loop:
                    async def send_error():
                        await self.websocket.send_json({
                            "type": "error",
                            "message": f"Recognition start error: {str(e)}",
                            "session_id": self.session_id
                        })
                    asyncio.run_coroutine_threadsafe(send_error(), self.loop)
        
        # Start recognition in a new thread
        threading.Thread(target=start_recognition_thread).start()
    
    async def stop_continuous_recognition(self):
        """Stop continuous recognition"""
        if not self.is_recognizing:
            logger.info("Recognition not active, ignoring stop request")
            return
            
        logger.info("Stopping continuous recognition")
        
        # Use thread to avoid blocking the event loop with synchronous call
        def stop_recognition_thread():
            try:
                self.recognizer.stop_continuous_recognition()
                logger.info("Continuous recognition stopped successfully")
            except Exception as e:
                logger.error(f"Failed to stop recognition: {e}")
            finally:
                self.is_recognizing = False
                
                # Always notify UI that we've stopped regardless of errors
                if self.websocket and self.loop:
                    async def send_status():
                        await self.websocket.send_json({
                            "type": "status",
                            "status": "stopped",
                            "session_id": self.session_id
                        })
                    asyncio.run_coroutine_threadsafe(send_status(), self.loop)
        
        # Stop recognition in a new thread
        threading.Thread(target=stop_recognition_thread).start()

class SimpleAzureTTS:
    """简单的Azure TTS流式实现，专为中国区设计"""
    
    def __init__(self, subscription_key, region, voice_name=AZURE_TTS_VOICE):
        self.subscription_key = subscription_key
        self.region = region
        self.voice_name = voice_name
        # 使用中国区域的域名
        self.endpoint = f"https://{region}.tts.speech.azure.cn/cognitiveservices/v1"
        self.http_client = httpx.AsyncClient(timeout=30.0)
        # 添加发送队列，确保块顺序
        self.send_queue = asyncio.Queue()
        self.send_task = None
        self.is_processing = False
        logger.info(f"中国区TTS已初始化，使用声音: {voice_name}，终端: {self.endpoint}")
    
    async def synthesize_text_stream(self, text, websocket, session_id, is_first=False):
        """将文本流式合成为PCM音频并直接发送到客户端"""
        if not text or not text.strip():
            logger.warning("TTS收到空文本")
            return
        
        logger.info(f"正在流式合成文本: '{text}'")
        
        try:
            # 构建简单的SSML
            ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN"><voice name="{self.voice_name}">{text}</voice></speak>"""
            
            # 设置请求头
            headers = {
                "Ocp-Apim-Subscription-Key": self.subscription_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
                "Accept": "audio/wav"  # 接受流式音频
            }
            
            # 生成句子ID
            sentence_id = str(uuid.uuid4())
            
            # 启动发送处理器（如果尚未启动）
            if not self.send_task or self.send_task.done():
                self.send_task = asyncio.create_task(self._process_send_queue(websocket))
                
            # 发送流式请求
            start_time = time.time()
            total_bytes = 0
            chunk_count = 0
            
            # 创建初始句子信息消息
            sentence_start = {
                "type": "tts_sentence_start",
                "sentence_id": sentence_id,
                "text": text,
                "is_first": is_first,
                "session_id": session_id
            }
            
            # 将句子开始消息放入队列
            await self.send_queue.put((0, sentence_start))
            
            async with self.http_client.stream("POST", 
                                              self.endpoint, 
                                              headers=headers, 
                                              content=ssml) as response:
                if response.status_code != 200:
                    logger.error(f"TTS请求失败，状态码: {response.status_code}")
                    error_text = await response.aread()
                    logger.error(f"错误: {error_text}")
                    
                    # 发送错误消息
                    error_msg = {
                        "type": "error",
                        "message": f"TTS合成失败: {response.status_code}",
                        "session_id": session_id
                    }
                    await self.send_queue.put((999999, error_msg))  # 高优先级
                    return
                
                # 逐块处理流式响应并加入发送队列
                async for chunk in response.aiter_bytes(chunk_size=4096):  # 使用更小的块大小
                    if chunk:
                        chunk_count += 1
                        total_bytes += len(chunk)
                        
                        # 创建音频块消息（使用二进制格式而非base64编码）
                        audio_msg = {
                            "type": "tts_audio_binary",
                            "sentence_id": sentence_id,
                            "binary_data": chunk,  # 这个字段将被特殊处理发送为二进制
                            "chunk_number": chunk_count,
                            "is_first_chunk": chunk_count == 1 and is_first,
                            "session_id": session_id
                        }
                        
                        # 将音频块消息放入队列（使用chunk_count作为优先级确保顺序）
                        await self.send_queue.put((chunk_count, audio_msg))
            
            # 记录性能
            duration = time.time() - start_time
            logger.info(f"TTS流式合成完成，耗时: {duration:.2f}秒，共{chunk_count}个块，总大小: {total_bytes} 字节")
            
            # 发送流式结束标记
            sentence_end = {
                "type": "tts_sentence_end",
                "sentence_id": sentence_id,
                "text": text,
                "session_id": session_id
            }
            
            # 放入队列，确保最后处理
            await self.send_queue.put((chunk_count + 1, sentence_end))
            
        except Exception as e:
            logger.error(f"TTS流式合成错误: {e}")
            # 尝试发送错误消息
            try:
                error_msg = {
                    "type": "error",
                    "message": f"TTS合成错误: {str(e)}",
                    "session_id": session_id
                }
                await self.send_queue.put((999999, error_msg))  # 高优先级
            except:
                pass
    
    async def _process_send_queue(self, websocket):
        """处理发送队列中的消息"""
        self.is_processing = True
        pending_msgs = []
        
        try:
            while True:
                # 尝试获取一个消息
                try:
                    priority, msg = await asyncio.wait_for(self.send_queue.get(), timeout=1.0)
                    pending_msgs.append((priority, msg))
                    self.send_queue.task_done()
                    
                    # 尝试一次性获取所有可用消息
                    try:
                        while not self.send_queue.empty():
                            p, m = await self.send_queue.get()
                            pending_msgs.append((p, m))
                            self.send_queue.task_done()
                    except:
                        pass
                    
                    # 对消息按优先级（块序号）排序
                    pending_msgs.sort(key=lambda x: x[0])
                    
                    # 依次发送所有排序后的消息
                    for _, message in pending_msgs:
                        if message["type"] == "tts_audio_binary":
                            # 二进制数据需要特殊处理
                            binary_data = message.pop("binary_data")
                            
                            # 先发送消息头部
                            await websocket.send_json({
                                "type": "tts_binary_header",
                                "sentence_id": message["sentence_id"],
                                "chunk_number": message["chunk_number"],
                                "is_first_chunk": message["is_first_chunk"],
                                "session_id": message["session_id"]
                            })
                            
                            # 再发送二进制数据
                            await websocket.send_bytes(binary_data)
                        else:
                            # 普通JSON消息
                            await websocket.send_json(message)
                    
                    # 清空已处理消息
                    pending_msgs = []
                
                except asyncio.TimeoutError:
                    # 超时意味着队列暂时空闲，但我们继续等待
                    if self.send_queue.empty() and len(pending_msgs) == 0:
                        # 如果队列已经空了，并且没有待处理消息，检查是否还有更多数据
                        if not self.is_processing:
                            # 如果处理已完成，退出循环
                            break
                
                except Exception as e:
                    logger.error(f"处理TTS发送队列出错: {e}")
                    # 处理失败，继续处理下一条消息
                    pending_msgs = []
        
        except asyncio.CancelledError:
            logger.info("TTS发送队列处理被取消")
        except Exception as e:
            logger.error(f"TTS发送队列处理异常: {e}")
        finally:
            self.is_processing = False
    
    async def close(self):
        """关闭HTTP客户端和清理资源"""
        # 取消发送任务
        if self.send_task and not self.send_task.done():
            self.send_task.cancel()
            try:
                await self.send_task
            except asyncio.CancelledError:
                pass
        
        # 关闭HTTP客户端
        await self.http_client.aclose()

def split_into_sentences(text):
    """将文本分成句子"""
    # 匹配中文和英文常见的句子终止符
    sentence_ends = r'(?<=[。！？.!?;；:：])\s*'
    sentences = re.split(sentence_ends, text)
    # 过滤空句子
    return [s.strip() for s in sentences if s.strip()]

async def process_with_llm(websocket, text, session_id):
    """使用LLM处理文本，将回复流式转换为语音并发送"""
    try:
        logger.info(f"Processing with LLM: '{text}'")
        
        # 向客户端发送LLM处理状态
        await websocket.send_json({
            "type": "llm_status",
            "status": "processing",
            "session_id": session_id
        })
        
        # 初始化TTS处理器（使用简单中国区版本）
        tts_processor = SimpleAzureTTS(
            subscription_key=AZURE_SPEECH_KEY,
            region=AZURE_SPEECH_REGION
        )
        
        # 从LLM流式收集文本的变量
        collected_response = ""
        text_buffer = ""
        sentences_queue = deque()
        
        # 标记是否已经处理了第一句
        first_sentence_processed = False
        
        # 当前正在处理的TTS任务
        current_tts_task = None
        
        async def process_sentences():
            """处理句子并流式合成音频"""
            nonlocal first_sentence_processed, current_tts_task
            
            while True:
                if sentences_queue and (current_tts_task is None or current_tts_task.done()):
                    # 获取下一个待处理的句子
                    sentence = sentences_queue.popleft()
                    
                    # 启动流式合成并直接发送
                    current_tts_task = asyncio.create_task(
                        tts_processor.synthesize_text_stream(
                            sentence, 
                            websocket, 
                            session_id,
                            is_first=not first_sentence_processed
                        )
                    )
                    
                    # 标记已处理第一句
                    if not first_sentence_processed:
                        first_sentence_processed = True
                
                # 短暂等待
                await asyncio.sleep(0.1)
                
                # 如果没有更多句子且已经收到完整回复，退出循环
                if not sentences_queue and process_sentences.llm_complete:
                    # 确保最后一个TTS任务完成
                    if current_tts_task and not current_tts_task.done():
                        await current_tts_task
                    break
        
        # 标记LLM是否完成
        process_sentences.llm_complete = False
        
        # 启动句子处理任务
        sentence_processor = asyncio.create_task(process_sentences())
        
        # 处理LLM流式回复
        try:
            async with async_timeout.timeout(30):
                # 创建流式回复
                response_stream = await openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": "你是一个智能语音助手小蕊，请用口语化、简短的回答客户问题，不要回复任何表情符号"},
                        {"role": "user", "content": text}
                    ],
                    stream=True
                )
                
                # 迭代流式回复
                async for chunk in response_stream:
                    if hasattr(chunk.choices[0], "delta"):
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            content = delta.content
                            collected_response += content
                            text_buffer += content
                            
                            # 检查缓冲区是否包含完整句子
                            if any(end in text_buffer for end in ["。", "！", "？", ".", "!", "?"]):
                                # 提取句子
                                new_sentences = split_into_sentences(text_buffer)
                                if new_sentences:
                                    # 添加句子到队列
                                    sentences_queue.extend(new_sentences)
                                    # 清空缓冲区，保留可能未完成的部分
                                    last_sentence = new_sentences[-1]
                                    if text_buffer.endswith(last_sentence):
                                        text_buffer = ""
                                    else:
                                        text_buffer = text_buffer[text_buffer.rfind(last_sentence) + len(last_sentence):]
                            
                            # 向客户端发送当前文本状态
                            await websocket.send_json({
                                "type": "llm_response",
                                "content": collected_response,
                                "is_complete": False,
                                "session_id": session_id
                            })
                
                # 处理剩余的文本
                if text_buffer:
                    sentences_queue.append(text_buffer)
                    text_buffer = ""
                
                # 标记LLM处理完成
                process_sentences.llm_complete = True
                
                # 等待所有句子都被处理
                await sentence_processor
                
        except asyncio.TimeoutError:
            logger.error("LLM streaming timed out after 30 seconds")
            await websocket.send_json({
                "type": "error",
                "message": "LLM streaming timed out",
                "session_id": session_id
            })
        
        # 关闭TTS处理器
        await tts_processor.close()
        
        # 发送完整回复
        if collected_response:
            await websocket.send_json({
                "type": "llm_response",
                "content": collected_response,
                "is_complete": True,
                "session_id": session_id
            })
            
            # 记录历史
            logger.info(f"LLM response complete: '{collected_response}'")
        else:
            logger.warning("No LLM response was collected")
            await websocket.send_json({
                "type": "error",
                "message": "LLM did not generate any response",
                "session_id": session_id
            })
        
    except Exception as e:
        logger.error(f"Error processing with LLM: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"LLM error: {str(e)}",
            "session_id": session_id
        })

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Get current event loop for the async operation
    loop = asyncio.get_running_loop()
    
    # Initialize Azure recognizer
    recognizer = AzureStreamingRecognizer(
        subscription_key=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION,
        language="zh-CN"
    )
    
    recognizer.set_websocket(websocket, loop)
    recognizer.setup_handlers()
    
    try:
        # Start recognition
        await recognizer.start_continuous_recognition()
        
        # Process incoming audio data
        while True:
            data = await websocket.receive()
            
            if "bytes" in data:
                # Process binary audio data
                audio_data = data["bytes"]
                if audio_data:
                    recognizer.feed_audio(audio_data)
                else:
                    logger.warning("Received empty audio data")
            
            elif "text" in data:
                # Process text commands
                try:
                    message = json.loads(data["text"])
                    cmd_type = message.get("type")
                    
                    if cmd_type == "stop":
                        await recognizer.stop_continuous_recognition()
                    elif cmd_type == "start":
                        await recognizer.start_continuous_recognition()
                    elif cmd_type == "reset":
                        await recognizer.stop_continuous_recognition()
                        
                        # Wait a bit to ensure previous session is fully stopped
                        await asyncio.sleep(1)
                        
                        # Create new recognizer instance
                        recognizer = AzureStreamingRecognizer(
                            subscription_key=AZURE_SPEECH_KEY,
                            region=AZURE_SPEECH_REGION,
                            language="zh-CN"
                        )
                        recognizer.set_websocket(websocket, loop)
                        recognizer.setup_handlers()
                        await recognizer.start_continuous_recognition()
                except Exception as e:
                    logger.error(f"Error processing command: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Command error: {str(e)}"
                    })
    
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        await recognizer.stop_continuous_recognition()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"WebSocket error: {str(e)}"
            })
        except:
            pass
        await recognizer.stop_continuous_recognition()

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_root():
    with open("static/index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)