import asyncio
import json
import os
import re
import logging
import uuid
import threading
import time
import struct
from collections import deque
from typing import Dict, Optional, Any, List, Callable, Coroutine

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
import httpx
import async_timeout
from openai import AsyncOpenAI

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 环境变量配置
class Config:
    """集中管理应用配置"""
    # Azure 语音服务配置
    AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
    AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
    AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    
    # OpenAI API配置
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    
    # 语音识别配置
    ASR_LANGUAGE = "zh-CN"
    VOICE_ENERGY_THRESHOLD = 0.05  # 语音能量阈值
    
    # 验证配置
    @classmethod
    def validate(cls):
        """验证必要的配置是否存在"""
        if not cls.AZURE_SPEECH_KEY or not cls.AZURE_SPEECH_REGION:
            logger.error("Azure Speech凭据缺失。请设置AZURE_SPEECH_KEY和AZURE_SPEECH_REGION环境变量。")
            return False
            
        if not cls.OPENAI_API_KEY:
            logger.error("OpenAI API密钥缺失。请设置OPENAI_API_KEY环境变量。")
            return False
        
        logger.info(f"使用OpenAI模型: {cls.OPENAI_MODEL}")
        if cls.OPENAI_BASE_URL:
            logger.info(f"使用自定义OpenAI基础URL: {cls.OPENAI_BASE_URL}")
        
        return True

# 验证配置
Config.validate()

# 初始化FastAPI应用
app = FastAPI(title="实时AI对话API")

# 配置OpenAI客户端
openai_client = AsyncOpenAI(
    api_key=Config.OPENAI_API_KEY,
    base_url=Config.OPENAI_BASE_URL if Config.OPENAI_BASE_URL else None
)

# 会话状态管理
class SessionState:
    """管理用户会话状态"""
    
    def __init__(self, session_id: str):
        """初始化会话状态
        
        Args:
            session_id: 会话唯一标识符
        """
        self.session_id = session_id
        self.is_processing_llm = False  # 是否正在处理LLM请求
        self.is_tts_active = False      # 是否正在进行TTS合成
        self.response_stream = None     # 当前响应流
        self.interrupt_requested = False # 是否请求中断
        self.tts_processor = None       # TTS处理器
        self.last_activity = time.time() # 最后活动时间
    
    def request_interrupt(self) -> None:
        """标记会话需要被中断"""
        logger.info(f"中断请求已接收，会话ID: {self.session_id}")
        self.interrupt_requested = True
    
    def clear_interrupt(self) -> None:
        """清除中断标记"""
        self.interrupt_requested = False
    
    def is_interrupted(self) -> bool:
        """检查是否请求了中断"""
        return self.interrupt_requested
    
    def update_activity(self) -> None:
        """更新最后活动时间"""
        self.last_activity = time.time()
    
    def is_inactive(self, timeout_seconds: int = 300) -> bool:
        """检查会话是否已不活跃
        
        Args:
            timeout_seconds: 超时时间（秒）
            
        Returns:
            如果会话不活跃，返回True
        """
        return (time.time() - self.last_activity) > timeout_seconds

# 会话状态字典
session_states: Dict[str, SessionState] = {}

# 音频诊断工具
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
            logger.warning("本报告周期内未收到音频块")
            return
        
        avg_chunk_size = self.total_bytes / self.chunks_received
        
        # 检查音频数据是否有效
        if avg_chunk_size < 10:
            logger.warning(f"音频块非常小（平均{avg_chunk_size:.2f}字节）")
        
        logger.info(f"音频统计: {self.chunks_received}块, 共{self.total_bytes}字节, 平均{avg_chunk_size:.2f}字节/块")
        
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

# 语音活动检测器
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
                if i*2+1 < len(audio_chunk):
                    # 解析2字节为16位整数
                    value = int.from_bytes(audio_chunk[i*2:i*2+2], byteorder='little', signed=True)
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

# Azure流式语音识别器
class AzureStreamingRecognizer:
    """Azure流式语音识别处理器"""
    
    def __init__(self, subscription_key: str, region: str, language: str = Config.ASR_LANGUAGE):
        """初始化Azure语音识别器
        
        Args:
            subscription_key: Azure语音服务订阅密钥
            region: Azure语音服务区域
            language: 识别的语言代码
        """
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
        self.last_partial_result = ""  # 最后的部分识别结果
        
        # 初始化识别器
        self._setup_recognizer()
    
    def _setup_recognizer(self) -> None:
        """设置Azure语音识别器"""
        try:
            # 创建推送流
            self.push_stream = speechsdk.audio.PushAudioInputStream()
            audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
            
            # 创建语音配置
            speech_config = speechsdk.SpeechConfig(
                subscription=self.subscription_key, 
                region=self.region
            )
            speech_config.speech_recognition_language = self.language
            
            # 启用听写模式以获得更好的结果
            speech_config.enable_dictation()
            
            # 记录音频格式信息
            logger.info(f"Azure期望的音频格式: 16位PCM，16kHz，单声道")
            
            # 创建流式识别器
            self.recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config
            )
            
            logger.info("Azure语音识别器初始化成功")
        except Exception as e:
            logger.error(f"设置Azure语音识别器失败: {e}")
            raise
    
    def set_websocket(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop) -> None:
        """设置WebSocket连接和事件循环
        
        Args:
            websocket: 连接到客户端的WebSocket对象
            loop: 异步事件循环
        """
        self.websocket = websocket
        self.loop = loop
    
    def setup_handlers(self) -> None:
        """设置识别事件处理程序"""
        # 识别中事件（部分结果）
        self.recognizer.recognizing.connect(self._on_recognizing)
        
        # 识别完成事件（最终结果）
        self.recognizer.recognized.connect(self._on_recognized)
        
        # 错误和取消事件
        self.recognizer.canceled.connect(self._on_canceled)
        self.recognizer.session_stopped.connect(self._on_session_stopped)
        
        # 语音检测事件
        self.recognizer.session_started.connect(self._on_session_started)
        self.recognizer.speech_start_detected.connect(self._on_speech_start_detected)
        self.recognizer.speech_end_detected.connect(self._on_speech_end_detected)
    
    def _on_session_started(self, evt) -> None:
        """处理会话开始事件"""
        logger.info(f"语音识别会话已开始: {evt}")
    
    def _on_speech_start_detected(self, evt) -> None:
        """处理语音开始检测"""
        logger.info("检测到语音开始")
    
    def _on_speech_end_detected(self, evt) -> None:
        """处理语音结束检测"""
        logger.info("检测到语音结束")
    
    def _on_recognizing(self, evt) -> None:
        """处理部分识别结果
        
        Args:
            evt: 识别事件对象
        """
        text = evt.result.text
        logger.info(f"部分识别: '{text}'")
        
        # 保存非空的部分结果
        if text.strip():
            self.last_partial_result = text
        
        # 通过WebSocket发送部分识别结果
        if self.websocket and self.loop and text.strip():
            async def send_partial():
                await self.websocket.send_json({
                    "type": "partial_transcript",
                    "content": text,
                    "session_id": self.session_id
                })
            
            asyncio.run_coroutine_threadsafe(send_partial(), self.loop)
    
    def _on_recognized(self, evt) -> None:
        """处理最终识别结果
        
        Args:
            evt: 识别事件对象
        """
        text = evt.result.text
        logger.info(f"最终识别: '{text}'")
        
        # 只处理非空结果
        if text.strip() and self.websocket and self.loop:
            async def process_and_send_final():
                # 发送最终识别结果
                await self.websocket.send_json({
                    "type": "final_transcript",
                    "content": text,
                    "session_id": self.session_id
                })
                
                # 处理文本并生成AI响应
                if text.strip():
                    await process_with_llm(self.websocket, text, self.session_id)
            
            asyncio.run_coroutine_threadsafe(process_and_send_final(), self.loop)
            
            # 清除部分结果
            self.last_partial_result = ""
        elif not text.strip():
            logger.info("识别结果为空，未检测到文本")
    
    def _on_canceled(self, evt) -> None:
        """处理取消和错误
        
        Args:
            evt: 取消事件对象
        """
        logger.error(f"识别已取消: {evt.result.reason}")
        
        if evt.result.reason == speechsdk.CancellationReason.Error:
            error_details = evt.result.cancellation_details.error_details
            logger.error(f"错误详情: {error_details}")
        
        # 通知客户端
        if self.websocket and self.loop:
            async def send_error():
                error_message = "错误: "
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
    
    def _on_session_stopped(self, evt) -> None:
        """处理会话停止事件
        
        Args:
            evt: 会话停止事件
        """
        logger.info("语音识别会话已停止")
        
        # 如果有部分结果但没有生成最终结果，则使用部分结果作为最终结果
        if self.websocket and self.loop and self.last_partial_result.strip():
            async def send_final_from_partial():
                logger.info(f"使用最后的部分结果作为最终结果: '{self.last_partial_result}'")
                
                # 发送最后的部分结果作为最终结果
                await self.websocket.send_json({
                    "type": "final_transcript",
                    "content": self.last_partial_result,
                    "session_id": self.session_id
                })
                
                # 处理响应
                await process_with_llm(self.websocket, self.last_partial_result, self.session_id)
                
                # 清除部分结果
                self.last_partial_result = ""
            
            asyncio.run_coroutine_threadsafe(send_final_from_partial(), self.loop)
        
        # 更新客户端状态
        if self.websocket and self.loop:
            async def send_status():
                await self.websocket.send_json({
                    "type": "status",
                    "status": "stopped",
                    "session_id": self.session_id
                })
            
            asyncio.run_coroutine_threadsafe(send_status(), self.loop)
        
        self.is_recognizing = False
    
    def feed_audio(self, audio_chunk: bytes) -> None:
        """处理传入的PCM音频块
        
        Args:
            audio_chunk: PCM音频数据
        """
        if not audio_chunk or len(audio_chunk) == 0:
            logger.warning("收到空音频块")
            return
        
        # 音频诊断
        self.audio_diagnostics.record_chunk(audio_chunk)
        
        # 送入语音识别器
        if self.push_stream:
            self.push_stream.write(audio_chunk)
    
    async def start_continuous_recognition(self) -> None:
        """开始连续识别"""
        if self.is_recognizing:
            logger.info("识别已在进行中，忽略开始请求")
            return
        
        logger.info("开始连续识别")
        
        # 更新客户端状态
        if self.websocket:
            await self.websocket.send_json({
                "type": "status",
                "status": "listening",
                "session_id": self.session_id
            })
        
        # 在线程中启动识别以避免阻塞事件循环
        def start_recognition_thread():
            try:
                self.recognizer.start_continuous_recognition()
                self.is_recognizing = True
                logger.info("连续识别成功启动")
            except Exception as e:
                logger.error(f"启动识别失败: {e}")
                self.is_recognizing = False
                
                # 通知错误
                if self.websocket and self.loop:
                    async def send_error():
                        await self.websocket.send_json({
                            "type": "error",
                            "message": f"识别启动错误: {str(e)}",
                            "session_id": self.session_id
                        })
                    asyncio.run_coroutine_threadsafe(send_error(), self.loop)
        
        # 启动识别线程
        threading.Thread(target=start_recognition_thread).start()
    
    async def stop_continuous_recognition(self) -> None:
        """停止连续识别"""
        if not self.is_recognizing:
            logger.info("识别未在进行中，忽略停止请求")
            return
        
        logger.info("停止连续识别")
        
        # 在线程中停止识别
        def stop_recognition_thread():
            try:
                self.recognizer.stop_continuous_recognition()
                logger.info("连续识别成功停止")
            except Exception as e:
                logger.error(f"停止识别失败: {e}")
            finally:
                self.is_recognizing = False
                
                # 总是通知UI我们已停止
                if self.websocket and self.loop:
                    async def send_status():
                        await self.websocket.send_json({
                            "type": "status",
                            "status": "stopped",
                            "session_id": self.session_id
                        })
                    asyncio.run_coroutine_threadsafe(send_status(), self.loop)
        
        # 启动停止线程
        threading.Thread(target=stop_recognition_thread).start()

class SimpleAzureTTS:
    """简单的Azure TTS流式实现，专为中国区设计"""
    
    # 全局句子队列和处理标志
    global_sentence_queue = asyncio.Queue()
    is_processing_sentence = False
    _sentence_processor_task = None
    _http_client = None  # 共享HTTP客户端
    
    # 正在处理的任务集合，用于中断
    active_tasks = set()
    
    @classmethod
    async def get_http_client(cls) -> httpx.AsyncClient:
        """获取或创建共享HTTP客户端
        
        Returns:
            HTTP客户端实例
        """
        if cls._http_client is None or cls._http_client.is_closed:
            cls._http_client = httpx.AsyncClient(timeout=30.0)
        return cls._http_client
    
    def __init__(self, subscription_key: str, region: str, voice_name: str = Config.AZURE_TTS_VOICE):
        """初始化TTS处理器
        
        Args:
            subscription_key: Azure语音服务订阅密钥
            region: Azure语音服务区域
            voice_name: TTS声音名称
        """
        self.subscription_key = subscription_key
        self.region = region
        self.voice_name = voice_name
        # 使用中国区域的域名
        self.endpoint = f"https://{region}.tts.speech.azure.cn/cognitiveservices/v1"
        # 发送队列
        self.send_queue = asyncio.Queue()
        self.send_task = None
        self.is_processing = False
        # 会话ID
        self.session_id = None
        
        # 启动全局句子处理器（如果尚未启动）
        if SimpleAzureTTS._sentence_processor_task is None or SimpleAzureTTS._sentence_processor_task.done():
            SimpleAzureTTS._sentence_processor_task = asyncio.create_task(
                SimpleAzureTTS._process_sentence_queue()
            )
        
        logger.info(f"中国区TTS已初始化，使用声音: {voice_name}，终端: {self.endpoint}")
    
    def set_session_id(self, session_id: str) -> None:
        """设置此TTS处理器的会话ID
        
        Args:
            session_id: 会话唯一标识符
        """
        self.session_id = session_id
    
    @classmethod
    async def _process_sentence_queue(cls) -> None:
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
    
    @classmethod
    async def interrupt_session(cls, session_id: str) -> bool:
        """中断特定会话的所有TTS任务
        
        Args:
            session_id: 要中断的会话ID
            
        Returns:
            如果有任务被中断，返回True
        """
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
    
    async def synthesize_text_stream(self, text: str, websocket: WebSocket, session_id: str, is_first: bool = False) -> None:
        """将文本流式合成为PCM音频并直接发送到客户端
        
        Args:
            text: 要合成的文本
            websocket: WebSocket连接
            session_id: 会话ID
            is_first: 是否是第一个句子
        """
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
    
    async def _process_single_sentence(self, text: str, websocket: WebSocket, session_id: str, is_first: bool) -> None:
        """处理单个句子的TTS合成
        
        Args:
            text: 要合成的文本
            websocket: WebSocket连接
            session_id: 会话ID
            is_first: 是否是第一个句子
        """
        logger.info(f"正在流式合成文本: '{text}'")
        
        # 获取HTTP客户端
        http_client = await SimpleAzureTTS.get_http_client()
        
        try:
            # 构建简单的SSML
            ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
                <voice name="{self.voice_name}">{text}</voice>
            </speak>"""
            
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
                # 验证文本长度
                if len(text) < 1 or len(text) > 1000:
                    logger.warning(f"文本长度异常: {len(text)}字符")
                    
                # 使用较短的超时时间
                timeout = httpx.Timeout(10.0, connect=5.0)
                
                async with http_client.stream("POST", 
                                          self.endpoint, 
                                          headers=headers, 
                                          content=ssml,
                                          timeout=timeout) as response:
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
                    
                    # 收集所有块并批量处理
                    chunks = []
                    
                    # 逐块处理流式响应并加入发送队列
                    async for chunk in response.aiter_bytes(chunk_size=4096):  # 使用更小的块大小
                        if chunk:
                            chunks.append(chunk)
                            total_bytes += len(chunk)
                    
                    # 检查是否有内容
                    if not chunks:
                        logger.warning(f"TTS响应没有返回音频数据: '{text}'")
                        # 发送空的结束标记以便客户端继续
                        await self.send_queue.put((1, {
                            "type": "tts_sentence_end",
                            "sentence_id": sentence_id,
                            "text": text,
                            "session_id": session_id,
                            "empty_response": True
                        }))
                        return
                    
                    # 检查会话是否已中断
                    session_state = session_states.get(session_id)
                    if session_state and session_state.is_interrupted():
                        logger.info(f"会话已中断，放弃发送TTS数据: '{text}'")
                        return
                    
                    # 依次处理所有数据块
                    for i, chunk in enumerate(chunks):
                        chunk_count = i + 1
                        
                        # 创建音频块消息（使用二进制格式）
                        audio_msg = {
                            "type": "tts_audio_binary",
                            "sentence_id": sentence_id,
                            "binary_data": chunk,  # 这个字段将被特殊处理发送为二进制
                            "chunk_number": chunk_count,
                            "is_first_chunk": chunk_count == 1 and is_first,
                            "total_chunks": len(chunks),
                            "session_id": session_id
                        }
                        
                        # 将音频块消息放入队列（使用chunk_count作为优先级确保顺序）
                        await self.send_queue.put((chunk_count, audio_msg))
                        
                        # 每隔一些块检查中断状态
                        if chunk_count % 5 == 0:
                            if session_state and session_state.is_interrupted():
                                logger.info(f"检测到中断，停止发送剩余TTS块")
                                break
                    
                    # 记录性能
                    duration = time.time() - start_time
                    logger.info(f"TTS流式合成完成，耗时: {duration:.2f}秒，共{chunk_count}个块，总大小: {total_bytes} 字节")
                    
                    # 只有在不中断的情况下发送结束标记
                    if not (session_state and session_state.is_interrupted()):
                        # 发送流式结束标记
                        sentence_end = {
                            "type": "tts_sentence_end",
                            "sentence_id": sentence_id,
                            "text": text,
                            "session_id": session_id
                        }
                        
                        # 放入队列，确保最后处理
                        await self.send_queue.put((chunk_count + 1, sentence_end))
                
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
    async def close_all(cls) -> None:
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
    
    async def close(self) -> None:
        """关闭资源"""
        # 取消发送任务
        if self.send_task and not self.send_task.done():
            self.send_task.cancel()
            try:
                await self.send_task
            except asyncio.CancelledError:
                pass
    
    async def _process_send_queue(self, websocket: WebSocket) -> None:
        """处理发送队列中的消息
        
        Args:
            websocket: WebSocket连接
        """
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
                            
                            # 确保数据有效
                            if not binary_data or len(binary_data) == 0:
                                logger.warning(f"跳过空的音频数据块: {message.get('chunk_number')}")
                                continue
                            
                            try:
                                # 创建包含元数据的二进制头部
                                # 格式: [4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
                                # 生成唯一请求ID (使用句子ID的哈希值)
                                request_id = hash(message["sentence_id"]) & 0xFFFFFFFF  # 取32位正整数
                                chunk_number = message["chunk_number"]
                                timestamp = int(time.time() * 1000) & 0xFFFFFFFF  # 毫秒时间戳
                                
                                # 创建头部
                                header = struct.pack("<III", request_id, chunk_number, timestamp)
                                
                                # 合并头部和PCM数据
                                combined_data = header + binary_data
                                
                                # 直接发送合并后的二进制数据
                                await websocket.send_bytes(combined_data)
                                
                                # 如果是第一个块，记录日志
                                if message.get("is_first_chunk", False):
                                    logger.info(f"发送首个音频块，ID: {request_id}, 块号: {chunk_number}, 大小: {len(binary_data)} 字节")
                            except Exception as e:
                                logger.error(f"发送音频数据出错: {e}")
                        else:
                            # 发送普通JSON消息
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

def split_into_sentences(text: str) -> List[str]:
    """将文本分成句子
    
    Args:
        text: 输入文本
        
    Returns:
        句子列表
    """
    # 匹配中文和英文常见的句子终止符
    sentence_ends = r'(?<=[。！？.!?;；:：])\s*'
    sentences = re.split(sentence_ends, text)
    # 过滤空句子
    return [s.strip() for s in sentences if s.strip()]

async def process_with_llm(websocket: WebSocket, text: str, session_id: str) -> None:
    """使用LLM处理文本，将回复流式转换为语音并发送
    
    Args:
        websocket: WebSocket连接
        text: 用户输入文本
        session_id: 会话ID
    """
    tts_processor = None
    
    # 获取或创建会话状态
    if session_id not in session_states:
        session_states[session_id] = SessionState(session_id)
    
    session_state = session_states[session_id]
    session_state.clear_interrupt()  # 清除之前的中断标记
    session_state.is_processing_llm = True
    session_state.update_activity()  # 更新活动时间
    
    try:
        logger.info(f"使用LLM处理文本: '{text}'")
        
        # 向客户端发送LLM处理状态
        await websocket.send_json({
            "type": "llm_status",
            "status": "processing",
            "session_id": session_id
        })
        
        # 初始化TTS处理器
        tts_processor = SimpleAzureTTS(
            subscription_key=Config.AZURE_SPEECH_KEY,
            region=Config.AZURE_SPEECH_REGION
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
                    model=Config.OPENAI_MODEL,
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
            logger.error("LLM流式处理超时（30秒）")
            await websocket.send_json({
                "type": "error",
                "message": "LLM流式处理超时",
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
            logger.info(f"LLM响应完成: '{collected_response}'")
        elif session_state.is_interrupted():
            logger.info("LLM处理被中断")
            await websocket.send_json({
                "type": "llm_response",
                "content": "对话被中断",
                "is_complete": True,
                "was_interrupted": True,
                "session_id": session_id
            })
        else:
            logger.warning("未收集到任何LLM响应")
            await websocket.send_json({
                "type": "error",
                "message": "LLM未生成任何响应",
                "session_id": session_id
            })
        
    except Exception as e:
        logger.error(f"LLM处理错误: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"LLM错误: {str(e)}",
            "session_id": session_id
        })
    finally:
        # 清理状态
        session_state.is_processing_llm = False
        session_state.is_tts_active = False
        session_state.response_stream = None

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket连接终端点
    
    处理与客户端的实时通信
    
    Args:
        websocket: WebSocket连接
    """
    await websocket.accept()
    
    # 获取当前事件循环
    loop = asyncio.get_running_loop()
    
    # 生成唯一会话ID
    session_id = str(uuid.uuid4())
    session_states[session_id] = SessionState(session_id)
    
    # 创建语音活动检测器
    voice_detector = VoiceActivityDetector()
    
    # 初始化Azure识别器
    recognizer = AzureStreamingRecognizer(
        subscription_key=Config.AZURE_SPEECH_KEY,
        region=Config.AZURE_SPEECH_REGION,
        language=Config.ASR_LANGUAGE
    )
    
    recognizer.set_websocket(websocket, loop)
    recognizer.setup_handlers()
    
    try:
        # 开始识别
        await recognizer.start_continuous_recognition()
        
        # 处理传入的音频数据
        while True:
            data = await websocket.receive()
            
            if "bytes" in data:
                # 处理二进制音频数据
                audio_data = data["bytes"]
                if audio_data:
                    # 进行简单验证
                    if len(audio_data) < 2:  # 至少需要一个16位样本
                        continue
                        
                    # 检测是否有语音活动
                    has_voice = voice_detector.detect(audio_data)
                    
                    # 检查是否有正在进行的TTS响应，如果有则发送打断信令
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
                    logger.warning("收到空音频数据")
            
            elif "text" in data:
                # 处理文本命令
                try:
                    message = json.loads(data["text"])
                    cmd_type = message.get("type")
                    
                    if cmd_type == "stop":
                        await recognizer.stop_continuous_recognition()
                        
                        # 停止所有TTS和LLM进程
                        logger.info(f"停止命令接收，停止所有TTS和LLM进程，会话ID: {session_id}")
                        
                        # 获取会话状态
                        session_state = session_states.get(session_id)
                        if session_state:
                            # 标记中断
                            session_state.request_interrupt()
                            
                            # 中断TTS
                            await SimpleAzureTTS.interrupt_session(session_id)
                            
                            # 通知客户端已完全停止
                            await websocket.send_json({
                                "type": "stop_acknowledged",
                                "message": "所有处理已停止",
                                "session_id": session_id
                            })
                    elif cmd_type == "start":
                        await recognizer.start_continuous_recognition()
                    elif cmd_type == "reset":
                        await recognizer.stop_continuous_recognition()
                        
                        # 等待一段时间确保前一个会话完全停止
                        await asyncio.sleep(1)
                        
                        # 创建新的识别器实例
                        recognizer = AzureStreamingRecognizer(
                            subscription_key=Config.AZURE_SPEECH_KEY,
                            region=Config.AZURE_SPEECH_REGION,
                            language=Config.ASR_LANGUAGE
                        )
                        recognizer.set_websocket(websocket, loop)
                        recognizer.setup_handlers()
                        await recognizer.start_continuous_recognition()
                    elif cmd_type == "interrupt":
                        # 处理中断命令
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
                    logger.error(f"处理命令错误: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"命令错误: {str(e)}"
                    })
    
    except WebSocketDisconnect:
        logger.info("WebSocket断开连接")
        await recognizer.stop_continuous_recognition()
        # 关闭所有TTS资源
        await SimpleAzureTTS.close_all()
        # 清理会话状态
        if session_id in session_states:
            del session_states[session_id]
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"WebSocket错误: {str(e)}"
            })
        except:
            pass
        await recognizer.stop_continuous_recognition()
        # 关闭所有TTS资源
        await SimpleAzureTTS.close_all()
        # 清理会话状态
        if session_id in session_states:
            del session_states[session_id]

# 定期清理不活跃的会话
@app.on_event("startup")
async def start_session_cleanup() -> None:
    """启动时开始会话清理任务"""
    asyncio.create_task(cleanup_inactive_sessions())

async def cleanup_inactive_sessions() -> None:
    """定期清理不活跃的会话"""
    while True:
        try:
            # 查找并清理不活跃的会话
            inactive_session_ids = []
            for session_id, state in session_states.items():
                if state.is_inactive(timeout_seconds=600):  # 10分钟无活动
                    inactive_session_ids.append(session_id)
            
            # 清理不活跃的会话
            for session_id in inactive_session_ids:
                logger.info(f"清理不活跃会话: {session_id}")
                # 尝试中断任何活动的处理
                try:
                    await SimpleAzureTTS.interrupt_session(session_id)
                except:
                    pass
                # 删除会话状态
                if session_id in session_states:
                    del session_states[session_id]
            
            # 每分钟检查一次
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"会话清理错误: {e}")
            await asyncio.sleep(60)  # 发生错误时，等待一分钟后重试

# 服务静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_root() -> str:
    """返回主页HTML
    
    Returns:
        HTML文本
    """
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

# 添加应用健康检查端点
@app.get("/health")
async def health_check() -> dict:
    """健康检查端点
    
    Returns:
        健康状态信息
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "session_count": len(session_states),
        "azure_speech_configured": bool(Config.AZURE_SPEECH_KEY and Config.AZURE_SPEECH_REGION),
        "openai_configured": bool(Config.OPENAI_API_KEY)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)