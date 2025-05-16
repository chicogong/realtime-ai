import asyncio
import threading
from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk
from loguru import logger

from services.asr.base import BaseASRService
from utils.audio import AudioDiagnostics


class AzureASRService(BaseASRService):
    """Azure语音识别服务实现"""

    def __init__(self, subscription_key: str, region: str, language: str = "zh-CN"):
        """初始化Azure ASR服务

        Args:
            subscription_key: Azure语音服务订阅密钥
            region: Azure服务区域
            language: 识别语言
        """
        super().__init__(language)
        self.subscription_key = subscription_key
        self.region = region
        self.push_stream = None
        self.recognizer = None
        self.audio_diagnostics = AudioDiagnostics()

        # 初始化识别器
        self._setup_recognizer()

    def _setup_recognizer(self) -> None:
        """设置Azure语音识别器"""
        try:
            # 创建推送流
            self.push_stream = speechsdk.audio.PushAudioInputStream()
            audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)

            # 创建语音配置
            speech_config = speechsdk.SpeechConfig(subscription=self.subscription_key, region=self.region)
            speech_config.speech_recognition_language = self.language
            speech_config.enable_dictation()

            logger.info("Azure期望的音频格式: 16位PCM，16kHz，单声道")

            # 创建流式识别器
            self.recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

            logger.info("Azure语音识别器初始化成功")
        except Exception as e:
            logger.error(f"设置Azure语音识别器失败: {e}")
            raise

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
        """会话开始事件处理"""
        logger.info(f"语音识别会话已开始: {evt}")

    def _on_speech_start_detected(self, evt) -> None:
        """语音开始事件处理"""
        logger.info("检测到语音开始")

    def _on_speech_end_detected(self, evt) -> None:
        """语音结束事件处理"""
        logger.info("检测到语音结束")

    def _on_recognizing(self, evt) -> None:
        """处理部分识别结果"""
        text = evt.result.text
        logger.info(f"部分识别: '{text}'")

        # 保存非空的部分结果
        if text.strip():
            self.last_partial_result = text

        # 通过WebSocket发送部分识别结果
        if self.websocket and self.loop and text.strip():

            async def send_partial():
                await self.send_partial_transcript(text)

            asyncio.run_coroutine_threadsafe(send_partial(), self.loop)

    def _on_recognized(self, evt) -> None:
        """处理最终识别结果"""
        text = evt.result.text
        logger.info(f"最终识别: '{text}'")

        # 只处理非空结果
        if text.strip() and self.websocket and self.loop:
            from services.websocket.handler import process_final_transcript

            async def process_and_send_final():
                # 发送最终识别结果
                await self.send_final_transcript(text)

                # 处理文本并生成AI响应
                if text.strip():
                    await process_final_transcript(self.websocket, text, self.session_id)

            asyncio.run_coroutine_threadsafe(process_and_send_final(), self.loop)

            # 清除部分结果
            self.last_partial_result = ""
        elif not text.strip():
            logger.info("识别结果为空，未检测到文本")

    def _on_canceled(self, evt) -> None:
        """处理取消和错误"""
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

                await self.send_error(error_message)

            asyncio.run_coroutine_threadsafe(send_error(), self.loop)

        self.is_recognizing = False

    def _on_session_stopped(self, evt) -> None:
        """处理会话停止事件"""
        logger.info("语音识别会话已停止")

        # 如果有部分结果但没有生成最终结果，则使用部分结果作为最终结果
        if self.websocket and self.loop and self.last_partial_result.strip():
            from services.websocket.handler import process_final_transcript

            async def send_final_from_partial():
                logger.info(f"使用最后的部分结果作为最终结果: '{self.last_partial_result}'")

                # 发送最后的部分结果作为最终结果
                await self.send_final_transcript(self.last_partial_result)

                # 处理响应
                await process_final_transcript(self.websocket, self.last_partial_result, self.session_id)

                # 清除部分结果
                self.last_partial_result = ""

            asyncio.run_coroutine_threadsafe(send_final_from_partial(), self.loop)

        # 更新客户端状态
        if self.websocket and self.loop:

            async def send_status():
                await self.send_status("stopped")

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
            try:
                self.push_stream.write(audio_chunk)
            except Exception as e:
                logger.error(f"推送音频数据错误: {e}")

    async def start_recognition(self) -> None:
        """启动连续识别"""
        if self.is_recognizing:
            logger.warning("语音识别已经在运行中")
            return

        logger.info("开始连续语音识别")
        self.is_recognizing = True

        try:
            # 异步启动识别，需要在单独的线程中进行
            thread = threading.Thread(target=self._start_recognition_thread)
            thread.daemon = True
            thread.start()

            # 通知客户端
            await self.send_status("listening")
        except Exception as e:
            self.is_recognizing = False
            logger.error(f"启动语音识别失败: {e}")

            if self.websocket:
                await self.send_error(f"启动语音识别失败: {str(e)}")

    def _start_recognition_thread(self) -> None:
        """在单独的线程中启动连续识别"""
        try:
            # 启动连续识别
            self.recognizer.start_continuous_recognition()
        except Exception as e:
            logger.error(f"连续识别启动错误: {e}")

            # 通知主线程有错误
            if self.loop:

                async def send_error():
                    await self.send_error(f"连续识别启动错误: {str(e)}")
                    self.is_recognizing = False

                asyncio.run_coroutine_threadsafe(send_error(), self.loop)

    async def stop_recognition(self) -> None:
        """停止连续识别"""
        if not self.is_recognizing:
            logger.warning("语音识别未运行")
            return

        logger.info("停止连续语音识别")

        try:
            # 异步停止识别，需要在单独的线程中进行
            thread = threading.Thread(target=self._stop_recognition_thread)
            thread.daemon = True
            thread.start()

            # 通知客户端
            await self.send_status("stopped")
        except Exception as e:
            logger.error(f"停止语音识别失败: {e}")
            if self.websocket:
                await self.send_error(f"停止语音识别失败: {str(e)}")

    def _stop_recognition_thread(self) -> None:
        """在单独的线程中停止连续识别"""
        try:
            # 停止连续识别
            self.recognizer.stop_continuous_recognition()
            self.is_recognizing = False
        except Exception as e:
            logger.error(f"连续识别停止错误: {e}")

            # 通知主线程有错误
            if self.loop:

                async def send_status():
                    await self.send_error(f"连续识别停止错误: {str(e)}")

                asyncio.run_coroutine_threadsafe(send_status(), self.loop)
