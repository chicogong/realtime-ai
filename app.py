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

# 新增：存储用户会话状态的字典
session_states = {}

# 新增：会话状态类
class SessionState:
    def __init__(self, session_id):
        self.session_id = session_id
        self.is_processing_llm = False
        self.is_tts_active = False
        self.response_stream = None
        self.interrupt_requested = False
        self.tts_processor = None

    def request_interrupt(self):
        """标记会话需要被中断"""
        logger.info(f"Interruption requested for session {self.session_id}")
        self.interrupt_requested = True

    def clear_interrupt(self):
        """清除中断标记"""
        self.interrupt_requested = False

    def is_interrupted(self):
        """检查是否请求了中断"""
        return self.interrupt_requested

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
    
    # 全局句子队列和处理标志
    global_sentence_queue = asyncio.Queue()
    is_processing_sentence = False
    _sentence_processor_task = None
    _http_client = None  # 共享HTTP客户端
    
    # 新增：正在处理的任务集合，用于中断
    active_tasks = set()
    
    @classmethod
    async def get_http_client(cls):
        """获取或创建共享HTTP客户端"""
        if cls._http_client is None or cls._http_client.is_closed:
            cls._http_client = httpx.AsyncClient(timeout=30.0)
        return cls._http_client
    
    def __init__(self, subscription_key, region, voice_name=AZURE_TTS_VOICE):
        self.subscription_key = subscription_key
        self.region = region
        self.voice_name = voice_name
        # 使用中国区域的域名
        self.endpoint = f"https://{region}.tts.speech.azure.cn/cognitiveservices/v1"
        # 不再为每个实例创建HTTP客户端
        self.send_queue = asyncio.Queue()
        self.send_task = None
        self.is_processing = False
        # 新增：会话ID和中断标记
        self.session_id = None
        
        # 启动全局句子处理器（如果尚未启动）
        if SimpleAzureTTS._sentence_processor_task is None or SimpleAzureTTS._sentence_processor_task.done():
            SimpleAzureTTS._sentence_processor_task = asyncio.create_task(
                SimpleAzureTTS._process_sentence_queue()
            )
        
        logger.info(f"中国区TTS已初始化，使用声音: {voice_name}，终端: {self.endpoint}")
    
    # 新增：设置会话ID
    def set_session_id(self, session_id):
        """设置此TTS处理器的会话ID"""
        self.session_id = session_id
    
    @classmethod
    async def _process_sentence_queue(cls):
        """全局句子队列处理器，确保一次只处理一个句子"""
        try:
            while True:
                # 获取下一个要处理的句子任务
                sentence_task = await cls.global_sentence_queue.get()
                
                # 标记正在处理句子
                cls.is_processing_sentence = True
                
                try:
                    # 创建任务并跟踪
                    task = asyncio.create_task(sentence_task())
                    
                    # 获取会话ID（如果可用）
                    if hasattr(sentence_task, 'session_id'):
                        task.session_id = sentence_task.session_id
                    
                    cls.active_tasks.add(task)
                    
                    try:
                        # 执行句子处理任务
                        await task
                    except asyncio.CancelledError:
                        logger.info("句子处理任务被取消")
                    finally:
                        # 移除跟踪
                        cls.active_tasks.discard(task)
                        
                except Exception as e:
                    logger.error(f"处理句子时出错: {e}")
                finally:
                    # 标记句子处理完成
                    cls.is_processing_sentence = False
                    cls.global_sentence_queue.task_done()
                    
                    # 等待一小段时间，确保前一个句子的音频处理完毕
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("句子队列处理器被取消")
        except Exception as e:
            logger.error(f"句子队列处理器异常: {e}")
            # 重启处理器
            cls._sentence_processor_task = asyncio.create_task(cls._process_sentence_queue())
    
    # 新增：中断会话相关的所有TTS任务
    @classmethod
    async def interrupt_session(cls, session_id):
        """中断特定会话的所有TTS任务"""
        logger.info(f"正在中断会话 {session_id} 的TTS任务")
        
        # 遍历所有活动任务，取消与此会话相关的任务
        interrupted_tasks = 0
        for task in list(cls.active_tasks):
            if hasattr(task, 'session_id') and task.session_id == session_id:
                logger.info(f"取消会话 {session_id} 的TTS任务")
                task.cancel()
                interrupted_tasks += 1
        
        logger.info(f"会话 {session_id} 的TTS任务中断完成，共取消 {interrupted_tasks} 个任务")
        return interrupted_tasks > 0
    
    async def synthesize_text_stream(self, text, websocket, session_id, is_first=False):
        """将文本流式合成为PCM音频并直接发送到客户端"""
        if not text or not text.strip():
            logger.warning("TTS收到空文本")
            return
        
        # 保存会话ID
        self.set_session_id(session_id)
        
        # 获取会话状态
        session_state = session_states.get(session_id)
        if session_state:
            # 如果请求了中断，直接返回
            if session_state.is_interrupted():
                logger.info(f"检测到中断请求，跳过TTS合成: '{text}'")
                return
            
            # 标记TTS活动状态
            session_state.is_tts_active = True
        
        # 创建句子处理任务
        sentence_task = lambda: self._process_single_sentence(text, websocket, session_id, is_first)
        
        # 添加会话ID属性
        sentence_task.session_id = session_id
        
        # 将任务添加到全局句子队列
        await SimpleAzureTTS.global_sentence_queue.put(sentence_task)
        
        logger.info(f"已将句子添加到队列: '{text}'")
    
    async def _process_single_sentence(self, text, websocket, session_id, is_first):
        """处理单个句子的TTS合成"""
        logger.info(f"正在流式合成文本: '{text}'")
        
        # 获取HTTP客户端
        http_client = await SimpleAzureTTS.get_http_client()
        
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
            
            try:
                async with http_client.stream("POST", 
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
            except httpx.ReadTimeout:
                logger.warning(f"TTS请求超时: '{text}'")
                await self.send_queue.put((999999, {
                    "type": "error",
                    "message": "TTS请求超时",
                    "session_id": session_id
                }))
                return
            except httpx.RequestError as e:
                logger.error(f"TTS请求错误: {e}")
                # 重新创建HTTP客户端
                SimpleAzureTTS._http_client = None
                await self.send_queue.put((999999, {
                    "type": "error",
                    "message": f"TTS请求错误: {str(e)}",
                    "session_id": session_id
                }))
                return
            
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
            
            # 等待发送队列处理完此句子的所有数据
            if self.send_queue.qsize() > 0:
                try:
                    await asyncio.wait_for(self.send_queue.join(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待发送队列处理超时，可能有消息未发送: '{text}'")
            
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
    
    @classmethod
    async def close_all(cls):
        """关闭所有资源"""
        # 关闭HTTP客户端
        if cls._http_client is not None:
            try:
                await cls._http_client.aclose()
                cls._http_client = None
            except:
                pass
        
        # 取消句子处理器
        if cls._sentence_processor_task and not cls._sentence_processor_task.done():
            cls._sentence_processor_task.cancel()
            try:
                await cls._sentence_processor_task
            except asyncio.CancelledError:
                pass
    
    async def close(self):
        """关闭HTTP客户端和清理资源"""
        # 取消发送任务
        if self.send_task and not self.send_task.done():
            self.send_task.cancel()
            try:
                await self.send_task
            except asyncio.CancelledError:
                pass
        
        # 不关闭HTTP客户端，因为它是共享的
    
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

def split_into_sentences(text):
    """将文本分成句子"""
    # 匹配中文和英文常见的句子终止符
    sentence_ends = r'(?<=[。！？.!?;；:：])\s*'
    sentences = re.split(sentence_ends, text)
    # 过滤空句子
    return [s.strip() for s in sentences if s.strip()]

async def process_with_llm(websocket, text, session_id):
    """使用LLM处理文本，将回复流式转换为语音并发送"""
    tts_processor = None
    
    # 获取或创建会话状态
    if session_id not in session_states:
        session_states[session_id] = SessionState(session_id)
    
    session_state = session_states[session_id]
    session_state.clear_interrupt()  # 清除之前的中断标记
    session_state.is_processing_llm = True
    
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
        tts_processor.set_session_id(session_id)
        session_state.tts_processor = tts_processor
        
        # 从LLM流式收集文本的变量
        collected_response = ""
        text_buffer = ""
        sentences_queue = []  # 使用列表存储句子
        
        # 标记是否已经处理了第一句
        first_sentence_processed = False
        
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
                
                # 保存流以便需要时中断
                session_state.response_stream = response_stream
                
                # 迭代流式回复
                async for chunk in response_stream:
                    # 检查是否请求了中断
                    if session_state.is_interrupted():
                        logger.info(f"检测到中断请求，停止LLM流式处理")
                        break
                        
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
                                    # 添加新句子到队列
                                    sentences_queue.extend(new_sentences)
                                    
                                    # 立即处理第一个句子
                                    if not first_sentence_processed and len(sentences_queue) > 0:
                                        first_sentence = sentences_queue.pop(0)
                                        # 检查是否请求了中断
                                        if not session_state.is_interrupted():
                                            await tts_processor.synthesize_text_stream(
                                                first_sentence, 
                                                websocket, 
                                                session_id,
                                                is_first=True
                                            )
                                            first_sentence_processed = True
                                    
                                    # 处理队列中的其他句子
                                    while len(sentences_queue) > 0:
                                        # 检查是否请求了中断
                                        if session_state.is_interrupted():
                                            logger.info(f"检测到中断请求，停止处理剩余句子")
                                            break
                                            
                                        sentence = sentences_queue.pop(0)
                                        await tts_processor.synthesize_text_stream(
                                            sentence, 
                                            websocket, 
                                            session_id,
                                            is_first=False
                                        )
                                    
                                    # 清空缓冲区，保留可能未完成的部分
                                    last_sentence = new_sentences[-1]
                                    if text_buffer.endswith(last_sentence):
                                        text_buffer = ""
                                    else:
                                        text_buffer = text_buffer[text_buffer.rfind(last_sentence) + len(last_sentence):]
                            
                            # 向客户端发送当前文本状态
                            if not session_state.is_interrupted():
                                await websocket.send_json({
                                    "type": "llm_response",
                                    "content": collected_response,
                                    "is_complete": False,
                                    "session_id": session_id
                                })
                
                # 处理剩余的文本
                if text_buffer and not session_state.is_interrupted():
                    sentences_queue.append(text_buffer)
                    text_buffer = ""
                
                # 处理队列中的所有剩余句子
                while len(sentences_queue) > 0 and not session_state.is_interrupted():
                    sentence = sentences_queue.pop(0)
                    await tts_processor.synthesize_text_stream(
                        sentence, 
                        websocket, 
                        session_id,
                        is_first=not first_sentence_processed
                    )
                    first_sentence_processed = True
                
        except asyncio.TimeoutError:
            logger.error("LLM streaming timed out after 30 seconds")
            await websocket.send_json({
                "type": "error",
                "message": "LLM streaming timed out",
                "session_id": session_id
            })
        
        # 发送完整回复（如果没有被中断）
        if collected_response and not session_state.is_interrupted():
            await websocket.send_json({
                "type": "llm_response",
                "content": collected_response,
                "is_complete": True,
                "session_id": session_id
            })
            
            # 记录历史
            logger.info(f"LLM response complete: '{collected_response}'")
        elif session_state.is_interrupted():
            logger.info("LLM processing was interrupted")
            await websocket.send_json({
                "type": "llm_response",
                "content": "对话被中断",
                "is_complete": true,
                "was_interrupted": true,
                "session_id": session_id
            })
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
    finally:
        # 清理状态
        session_state.is_processing_llm = False
        session_state.is_tts_active = False
        session_state.response_stream = None

# 添加语音活动检测工具类
class VoiceActivityDetector:
    def __init__(self):
        self.energy_threshold = 0.01  # 能量阈值，可以根据环境调整
        self.frame_count = 0
        self.voice_frames = 0
        self.reset_interval = 20  # 每隔多少帧重置计数
        
    def reset(self):
        """重置检测器状态"""
        self.frame_count = 0
        self.voice_frames = 0
        
    def detect(self, audio_chunk):
        """检测音频块中是否包含语音"""
        if not audio_chunk or len(audio_chunk) < 10:
            return False
            
        # 只检查每隔一定数量的帧
        self.frame_count += 1
        if self.frame_count > self.reset_interval:
            self.reset()
            
        try:
            # 计算音频能量
            if len(audio_chunk) >= 20:  # 至少需要10个样本点
                pcm_samples = struct.unpack(f"<{len(audio_chunk)//2}h", audio_chunk[:100])
                
                # 计算平均能量
                energy = 0
                for sample in pcm_samples:
                    energy += abs(sample)
                energy = energy / len(pcm_samples)
                
                # 归一化能量值 (16位PCM范围是-32768到32767)
                normalized_energy = energy / 32768.0
                
                # 判断是否超过阈值
                if normalized_energy > self.energy_threshold:
                    self.voice_frames += 1
                    return True
        except Exception as e:
            logger.warning(f"语音检测错误: {e}")
            
        return False
        
    def has_continuous_voice(self):
        """判断是否检测到连续的语音帧"""
        # 如果连续的语音帧数超过一定比例，认为有持续语音
        return self.voice_frames > (self.reset_interval * 0.3)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Get current event loop for the async operation
    loop = asyncio.get_running_loop()
    
    # Generate a unique session ID
    session_id = str(uuid.uuid4())
    session_states[session_id] = SessionState(session_id)
    
    # 创建语音活动检测器
    voice_detector = VoiceActivityDetector()
    
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
                    # 检测是否有语音活动
                    has_voice = voice_detector.detect(audio_data)
                    
                    # 新增：检查是否有正在进行的TTS响应，如果有则发送打断信令
                    session_state = session_states.get(session_id)
                    if has_voice and session_state and (session_state.is_tts_active or session_state.is_processing_llm):
                        # 只有当检测到显著的语音活动时才发送打断信令
                        if voice_detector.has_continuous_voice():
                            logger.info(f"检测到明显的语音输入，打断当前响应，会话ID: {session_id}")
                            
                            # 发送打断信令到客户端
                            await websocket.send_json({
                                "type": "server_interrupt",
                                "message": "检测到新的语音输入，打断当前响应",
                                "session_id": session_id
                            })
                            
                            # 标记中断
                            session_state.request_interrupt()
                            
                            # 中断TTS
                            if await SimpleAzureTTS.interrupt_session(session_id):
                                # 重置语音检测器
                                voice_detector.reset()
                    
                    # 继续处理音频
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
                    elif cmd_type == "interrupt":
                        # 新增：处理中断命令
                        logger.info(f"接收到中断命令，会话ID: {session_id}")
                        
                        # 获取会话状态
                        session_state = session_states.get(session_id)
                        if session_state:
                            # 标记中断
                            session_state.request_interrupt()
                            
                            # 中断TTS
                            await SimpleAzureTTS.interrupt_session(session_id)
                            
                            # 通知客户端已接收中断信号
                            await websocket.send_json({
                                "type": "interrupt_acknowledged",
                                "session_id": session_id
                            })
                        
                except Exception as e:
                    logger.error(f"Error processing command: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Command error: {str(e)}"
                    })
    
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        await recognizer.stop_continuous_recognition()
        # 关闭所有TTS资源
        await SimpleAzureTTS.close_all()
        # 清理会话状态
        if session_id in session_states:
            del session_states[session_id]
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
        # 关闭所有TTS资源
        await SimpleAzureTTS.close_all()
        # 清理会话状态
        if session_id in session_states:
            del session_states[session_id]

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_root():
    with open("static/index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)