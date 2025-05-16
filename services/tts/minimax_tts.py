import asyncio
import time
import json
import traceback
import struct
from typing import Dict, Optional, Set, Any
from loguru import logger

import httpx
import async_timeout
from fastapi import WebSocket

from config import Config
from services.tts.base import BaseTTSService

class MiniMaxTTSService(BaseTTSService):
    """MiniMax TTS服务实现"""
    
    # 全局资源
    _http_client = None  # 共享HTTP客户端
    active_tasks: Set[asyncio.Task] = set()  # 活动任务集合，用于中断
    
    def __init__(self, api_key: str, voice_id: str = "male-qn-qingse"):
        """初始化MiniMax TTS服务
        
        Args:
            api_key: MiniMax API密钥
            voice_id: 语音ID
        """
        super().__init__()
        self.api_key = api_key
        self.voice_id = voice_id
        self.speed = 1  # 语速，整数值
        self.volume = 1  # 音量，整数值
        self.pitch = 0  # 音调，整数值
        self.emotion = ""  # 情感，默认为空
        self.model = "speech-01-hd"  # 模型名称
        self.group_id = ""  # 组ID，可能为空
        
        self.is_processing = False
        self.send_queue = asyncio.Queue()  # 用于发送数据的队列
        self.send_task = None
        
        # 网络延迟和首帧延迟
        self.network_latency = 0
        self.first_frame_latency = 0
        
        logger.info(f"MiniMax TTS服务初始化: 语音={voice_id}")
    
    @classmethod
    async def get_http_client(cls) -> httpx.AsyncClient:
        """获取或创建HTTP客户端
        
        Returns:
            HTTP客户端实例
        """
        if cls._http_client is None or cls._http_client.is_closed:
            # 设置超时参数
            timeout = httpx.Timeout(30.0, connect=10.0)
            cls._http_client = httpx.AsyncClient(timeout=timeout)
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
            MiniMaxTTSService.active_tasks.add(self.send_task)
            self.send_task.add_done_callback(MiniMaxTTSService.active_tasks.discard)
        
        try:
            # 获取HTTP客户端
            client = await MiniMaxTTSService.get_http_client()
            
            # 构建请求
            url = "https://api.minimax.chat/v1/t2a_v2"
            if self.group_id:
                url = f"{url}?GroupId={self.group_id}"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*"
            }
            
            payload = {
                "model": self.model,
                "text": text,
                "stream": True,
                "voice_setting": {
                    "voice_id": self.voice_id,
                    "speed": self.speed,
                    "vol": self.volume,
                    "pitch": self.pitch
                },
                "audio_setting": {
                    "sample_rate": 16000,
                    "format": "pcm",
                    "channel": 1
                }
            }
            
            # 增加情绪参数传递
            if self.emotion:
                payload["voice_setting"]["emotion"] = self.emotion
            
            # 发送请求并获取音频数据
            start_time = time.time()
            logger.info(f"开始MiniMax TTS请求，文本长度: {len(text)}个字符")
            
            # 用于收集音频数据的列表
            all_audio_data = bytearray()
            
            try:
                async with async_timeout.timeout(10):  # 10秒超时
                    # 使用流式响应
                    first_chunk = True
                    
                    # 行缓冲区，用于正确处理跨网络块的数据
                    buffer = bytearray()
                    
                    async with client.stream("POST", url, headers=headers, json=payload, timeout=30.0) as response:
                        response.raise_for_status()
                        
                        # 根据参考实现来处理响应内容
                        async for chunk in response.aiter_bytes():
                            # 检查会话是否已中断
                            from models.session import get_session
                            session = get_session(self.session_id)
                            if session.is_interrupted():
                                logger.info(f"会话已中断，停止TTS流")
                                break
                                
                            if len(chunk) == 0 or chunk == b'\n':
                                continue
                                
                            # 记录首帧延迟
                            if first_chunk:
                                self.first_frame_latency = int((time.time() - start_time) * 1000)
                                logger.info(f"首帧延迟: {self.first_frame_latency} ms")
                                first_chunk = False
                                
                            # 追加到行缓冲区
                            buffer.extend(chunk)
                            
                            # 分割行
                            lines = buffer.split(b'\n')
                            
                            # 处理完整的行
                            for i in range(len(lines) - 1):
                                line = lines[i]
                                if not line:
                                    continue
                                    
                                # 处理data:前缀的行
                                if line.startswith(b'data:'):
                                    json_str = None
                                    
                                    # 提取JSON字符串
                                    if line.startswith(b'data:') and line[5:6] != b' ':
                                        json_str = line[5:]
                                    elif line.startswith(b'data: '):
                                        json_str = line[6:]
                                    
                                    if not json_str:
                                        continue
                                        
                                    try:
                                        # 解析JSON
                                        data = json.loads(json_str)
                                        
                                        # 检查错误
                                        if "base_resp" in data:
                                            base_resp = data["base_resp"]
                                            status_code = base_resp.get("status_code")
                                            status_msg = base_resp.get("status_msg")
                                            if status_code != 0:
                                                logger.error(f"MiniMax TTS错误: status_code={status_code}, status_msg={status_msg}, trace_id={trace_id}, requestid={request_id}")
                                                continue
                                        
                                        # 提取额外信息
                                        if "extra_info" in data:
                                            extra_info = data.get("extra_info")
                                            logger.info(f"MiniMax TTS额外信息: {extra_info}")
                                            continue
                                        
                                        # 提取音频数据
                                        if "data" in data and "extra_info" not in data:
                                            if "audio" in data["data"]:
                                                audio_hex = data["data"]["audio"]
                                                if audio_hex and audio_hex != '\n':
                                                    # 将hex格式转换为二进制数据
                                                    try:
                                                        decoded_audio = bytes.fromhex(audio_hex)
                                                        if decoded_audio:
                                                            # 确保PCM数据有效
                                                            if len(decoded_audio) > 0:
                                                                # 将音频数据追加到总缓冲区
                                                                all_audio_data.extend(decoded_audio)
                                                    except ValueError as hex_err:
                                                        logger.error(f"音频数据hex解码错误: {str(hex_err)}")
                                    except Exception as e:
                                        logger.error(f"处理音频数据异常: {str(e)}")
                            
                            # 保留最后一行，可能不完整
                            buffer = lines[-1]
                    
                    # 处理完成，将完整音频数据加入发送队列
                    if all_audio_data:
                        # 再次检查会话是否已中断
                        if session.is_interrupted():
                            logger.info(f"会话已中断，跳过添加音频到队列")
                            return
                            
                        item = {
                            "audio_data": bytes(all_audio_data),
                            "is_first": is_first,
                            "text": text
                        }
                        await self.send_queue.put(item)
                        logger.info(f"MiniMax TTS请求完成，耗时: {time.time() - start_time:.2f}秒，总大小: {len(all_audio_data)} 字节")
                
            except asyncio.TimeoutError:
                logger.error(f"MiniMax TTS请求超时: {text[:30]}...")
                # 通知客户端错误
                await websocket.send_json({
                    "type": "error",
                    "message": "TTS请求超时",
                    "session_id": self.session_id
                })
        except Exception as e:
            logger.error(f"MiniMax TTS处理错误: {e}")
            # 通知客户端错误
            await websocket.send_json({
                "type": "error",
                "message": f"TTS错误: {str(e)}",
                "session_id": self.session_id
            })
    
    async def _process_send_queue(self, websocket: WebSocket) -> None:
        """处理发送队列中的音频数据，按队列顺序发送
        
        Args:
            websocket: WebSocket连接
        """
        self.is_processing = True
        total_audio_size = 0
        audio_chunk_count = 0
        
        try:
            logger.info(f"音频处理队列任务已启动")
            while True:
                # 获取下一个待发送项目
                item = await self.send_queue.get()
                audio_data = item["audio_data"]
                is_first = item["is_first"]
                text = item["text"]
                
                # 检查会话是否已中断
                from models.session import get_session
                session = get_session(self.session_id)
                if session.is_interrupted():
                    logger.info(f"会话已中断，跳过音频发送: {text[:30]}...")
                    self.send_queue.task_done()
                    continue
                
                # 标记TTS正在进行
                session.is_tts_active = True
                
                try:
                    # 发送音频信息
                    await websocket.send_json({
                        "type": "tts_start",
                        "format": "raw-16khz-16bit-mono-pcm",
                        "is_first": is_first,
                        "text": text,
                        "session_id": self.session_id
                    })
                    
                    # 发送音频数据
                    await websocket.send_bytes(audio_data)
                    
                    # 发送音频结束标记
                    await websocket.send_json({
                        "type": "tts_end",
                        "session_id": self.session_id
                    })
                    
                    # 更新统计信息
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
            logger.info("音频处理队列被取消")
        except Exception as e:
            logger.error(f"TTS处理队列异常: {e}")
        finally:
            self.is_processing = False
            logger.info(f"音频处理队列任务已结束: 总块数={audio_chunk_count}, 总大小={total_audio_size}字节")
    
    @classmethod
    async def interrupt_all(cls) -> None:
        """中断所有活动的TTS任务"""
        for task in list(cls.active_tasks):
            if not task.done():
                task.cancel()
        
        # 等待所有任务取消完成
        if cls.active_tasks:
            await asyncio.gather(*cls.active_tasks, return_exceptions=True)
    
    async def interrupt(self) -> bool:
        """中断当前会话的TTS任务
        
        Returns:
            是否成功中断
        """
        interrupted = False
        
        # 清空发送队列
        while not self.send_queue.empty():
            try:
                self.send_queue.get_nowait()
                self.send_queue.task_done()
                interrupted = True
            except asyncio.QueueEmpty:
                break
        
        # 取消发送任务
        if self.send_task and not self.send_task.done():
            self.send_task.cancel()
            interrupted = True
            try:
                await self.send_task
            except asyncio.CancelledError:
                pass
        
        return interrupted
    
    @classmethod
    async def close_all(cls) -> None:
        """关闭所有MiniMax TTS资源"""
        # 中断所有活动任务
        await cls.interrupt_all()
        
        # 关闭HTTP客户端
        if cls._http_client is not None and not cls._http_client.is_closed:
            await cls._http_client.aclose()
            cls._http_client = None
    
    async def close(self) -> None:
        """关闭当前TTS服务实例"""
        await self.interrupt() 