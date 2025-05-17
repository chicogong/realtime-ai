import asyncio
import json
import time
from typing import Any, Dict, Optional, Set

import async_timeout
import httpx
from fastapi import WebSocket
from loguru import logger

from config import Config
from services.tts.base import BaseTTSService


class AzureTTSService(BaseTTSService):
    """Azure TTS服务实现"""

    # 全局资源
    _http_client = None  # 共享HTTP客户端
    active_tasks: Set[asyncio.Task] = set()  # 活动任务集合，用于中断

    def __init__(self, subscription_key: str, region: str, voice_name: str = Config.AZURE_TTS_VOICE) -> None:
        """初始化Azure TTS服务

        Args:
            subscription_key: Azure语音服务订阅密钥
            region: Azure服务区域
            voice_name: 语音名称
        """
        super().__init__()
        self.subscription_key = subscription_key
        self.region = region
        self.voice_name = voice_name
        self.is_processing = False
        self.send_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()  # 用于发送数据的队列
        self.send_task: Optional[asyncio.Task[None]] = None

        logger.info(f"Azure TTS服务初始化: 语音={voice_name}")

    @classmethod
    async def get_http_client(cls) -> httpx.AsyncClient:
        """获取或创建HTTP客户端

        Returns:
            HTTP客户端实例
        """
        if cls._http_client is None or cls._http_client.is_closed:
            cls._http_client = httpx.AsyncClient()
        return cls._http_client

    async def synthesize_text(self, text: str, websocket: WebSocket, is_first: bool = False) -> None:
        """将文本合成为语音并发送到客户端

        Args:
            text: 要合成的文本
            websocket: WebSocket连接
            is_first: 是否是本次响应的第一句话
        """
        if not text.strip():
            logger.warning("尝试合成空文本")
            return

        logger.info(f"合成文本: '{text}'")

        # 确保发送任务正在运行
        if not self.send_task or self.send_task.done():
            self.send_task = asyncio.create_task(self._process_send_queue(websocket))
            # 将任务添加到活动任务集合
            AzureTTSService.active_tasks.add(self.send_task)
            self.send_task.add_done_callback(AzureTTSService.active_tasks.discard)

        try:
            # 获取HTTP客户端
            client = await AzureTTSService.get_http_client()

            # 构建SSML
            ssml = f"""
            <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>
                <voice name='{self.voice_name}'>
                    <prosody rate='0%' pitch='0%'>
                        {text}
                    </prosody>
                </voice>
            </speak>
            """

            # 构建请求
            url = f"https://{self.region}.tts.speech.azure.cn/cognitiveservices/v1"
            headers = {
                "Ocp-Apim-Subscription-Key": self.subscription_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
                "User-Agent": "RealTimeAI",
            }

            # 发送请求并获取音频数据
            start_time = time.time()
            logger.info(f"开始TTS请求，文本长度: {len(text)}个字符")

            async with async_timeout.timeout(10):  # 10秒超时
                response = await client.post(url, headers=headers, content=ssml.encode("utf-8"))
                response.raise_for_status()

                # 获取音频数据
                audio_data = response.content

                logger.info(f"TTS请求完成，耗时: {time.time() - start_time:.2f}秒，音频大小: {len(audio_data)} 字节")

                # 检查会话是否已中断
                from session import get_session

                if self.session_id is None:
                    logger.error("session_id is None")
                    return
                    
                session = get_session(self.session_id)
                if session and session.is_interrupted():
                    logger.info(f"会话已中断，跳过添加音频到队列")
                    return

                # 将音频数据加入发送队列
                item = {"audio_data": audio_data, "is_first": is_first, "text": text}
                await self.send_queue.put(item)

        except asyncio.TimeoutError:
            logger.error(f"TTS请求超时: {text[:30]}...")
            # 通知客户端错误
            await websocket.send_json({"type": "error", "message": "TTS请求超时", "session_id": self.session_id})
        except Exception as e:
            logger.error(f"TTS处理错误: {e}")
            # 通知客户端错误
            await websocket.send_json({"type": "error", "message": f"TTS错误: {str(e)}", "session_id": self.session_id})

    async def _process_send_queue(self, websocket: WebSocket) -> None:
        """处理发送队列中的音频数据，按队列顺序发送

        Args:
            websocket: WebSocket连接
        """
        self.is_processing = True
        total_audio_size = 0
        audio_chunk_count = 0

        try:
            while True:
                # 获取下一个待发送项目
                item = await self.send_queue.get()
                audio_data = item["audio_data"]
                is_first = item["is_first"]
                text = item["text"]

                # 检查会话是否已中断
                from session import get_session

                if self.session_id is None:
                    logger.error("session_id is None")
                    self.send_queue.task_done()
                    continue
                    
                session = get_session(self.session_id)
                if session and session.is_interrupted():
                    logger.info(f"会话已中断，跳过音频发送: {text[:30]}...")
                    self.send_queue.task_done()
                    continue

                # 标记TTS正在进行
                session.is_tts_active = True

                try:
                    # 发送音频类型信息
                    await websocket.send_json(
                        {
                            "type": "tts_start",
                            "format": "raw-16khz-16bit-mono-pcm",
                            "is_first": is_first,
                            "text": text,
                            "session_id": self.session_id,
                        }
                    )

                    # 发送音频数据
                    await websocket.send_bytes(audio_data)

                    # 发送音频结束标记
                    await websocket.send_json({"type": "tts_end", "session_id": self.session_id})

                    total_audio_size += len(audio_data)
                    audio_chunk_count += 1

                    logger.info(f"音频数据已发送, 大小: {len(audio_data)} 字节")
                except Exception as e:
                    logger.error(f"发送音频数据错误: {e}")
                finally:
                    # 标记TTS已完成
                    session.is_tts_active = False

                # 标记任务完成
                self.send_queue.task_done()
        except asyncio.CancelledError:
            logger.info("TTS发送队列任务被取消")
        except Exception as e:
            logger.error(f"TTS发送队列处理异常: {e}")
        finally:
            self.is_processing = False

    @classmethod
    async def interrupt_all(cls) -> None:
        """中断所有活动的TTS任务"""
        for task in list(cls.active_tasks):
            if not task.done():
                logger.info(f"中断TTS任务: {task}")
                task.cancel()

        # 等待任务取消完成
        if cls.active_tasks:
            await asyncio.gather(
                *[asyncio.create_task(asyncio.sleep(0.1)) for _ in cls.active_tasks], return_exceptions=True
            )

    async def interrupt(self) -> bool:
        """中断当前的语音合成

        Returns:
            是否成功中断
        """
        if self.send_task and not self.send_task.done():
            logger.info(f"中断TTS任务: {self.send_task}")
            self.send_task.cancel()

            # 等待任务被正确取消
            try:
                await asyncio.wait_for(asyncio.create_task(asyncio.sleep(0.1)), timeout=0.2)
            except asyncio.TimeoutError:
                pass

            # 重置队列
            while not self.send_queue.empty():
                try:
                    self.send_queue.get_nowait()
                    self.send_queue.task_done()
                except Exception:
                    pass

            return True
        return False

    @classmethod
    async def close_all(cls) -> None:
        """关闭所有TTS资源"""
        # 取消所有活动任务
        await cls.interrupt_all()

        # 关闭HTTP客户端
        if cls._http_client is not None and not cls._http_client.is_closed:
            await cls._http_client.aclose()
            cls._http_client = None

    async def close(self) -> None:
        """关闭TTS服务，释放资源"""
        await self.interrupt()
