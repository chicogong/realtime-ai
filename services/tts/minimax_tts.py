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
        self.model = "speech-02-hd"  # 模型名称
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
        
        # 创建TTS任务
        tts_task = asyncio.create_task(self._process_single_sentence(text, websocket, is_first))
        # 将任务添加到活动任务集合
        MiniMaxTTSService.active_tasks.add(tts_task)
        tts_task.add_done_callback(MiniMaxTTSService.active_tasks.discard)
    
    async def _process_single_sentence(self, text: str, websocket: WebSocket, is_first: bool = False) -> None:
        """处理单个句子的TTS请求
        
        Args:
            text: 要合成的文本
            websocket: WebSocket连接
            is_first: 是否是本次响应的第一句话
        """
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
            
            # 记录请求参数
            logger.info(f"TTS请求参数: model={self.model}, voice_id={self.voice_id}, sample_rate=16000, format=pcm")
            
            # 增加情绪参数传递
            if self.emotion:
                payload["voice_setting"]["emotion"] = self.emotion
            
            # 发送请求并获取音频数据
            start_time = time.time()
            logger.info(f"开始MiniMax TTS请求，文本长度: {len(text)}个字符")
            
            # 通知客户端开始音频处理
            await websocket.send_json({
                "type": "audio_start",
                "format": "raw-16khz-16bit-mono-pcm",  # 16kHz PCM格式
                "is_first": is_first,
                "text": text,
                "session_id": self.session_id
            })
            
            try:
                async with async_timeout.timeout(10):  # 10秒超时
                    # 使用流式响应
                    first_chunk = True
                    
                    # 行缓冲区，用于正确处理跨网络块的数据
                    buffer = bytearray()
                    
                    async with client.stream("POST", url, headers=headers, json=payload, timeout=30.0) as response:
                        response.raise_for_status()
                        
                        # 获取请求ID和追踪ID
                        request_id = response.headers.get("Minimax-Request-Id", "unknown")
                        trace_id = response.headers.get("Trace-Id", "unknown")
                        
                        # 根据参考实现来处理响应内容
                        async for chunk in response.aiter_bytes():
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
                                
                                # 检查是否是data:前缀
                                if line.startswith(b'data:'):
                                    json_str = None
                                    
                                    # 处理无空格data:前缀
                                    if line.startswith(b'data:') and line[5:6] != b' ':
                                        json_str = line[5:]
                                    # 处理有空格data:前缀
                                    elif line.startswith(b'data: '):
                                        json_str = line[6:]
                                    
                                    if not json_str:
                                        continue
                                        
                                    try:
                                        # 尝试解析JSON
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
                                                            # 验证PCM数据
                                                            # 检查数据长度是否为偶数（16位PCM）
                                                            if len(decoded_audio) % 2 != 0:
                                                                logger.warning(f"PCM数据长度不是偶数: {len(decoded_audio)}字节，截断最后一个字节")
                                                                decoded_audio = decoded_audio[:-1]
                                                                
                                                            # 简单验证PCM数据 - 检查前几个样本是否在合理范围内
                                                            valid_pcm = True
                                                            invalid_samples = 0
                                                            # 从二进制数据中解析出前10个16位有符号整数样本
                                                            for j in range(0, min(20, len(decoded_audio)), 2):
                                                                try:
                                                                    sample = struct.unpack('<h', decoded_audio[j:j+2])[0]  # 小端序，有符号16位整数
                                                                    if abs(sample) > 32767:  # 16位有符号整数的范围是-32768到32767
                                                                        invalid_samples += 1
                                                                        if invalid_samples > 2:  # 允许少量异常值
                                                                            valid_pcm = False
                                                                            logger.warning(f"检测到多个无效PCM样本，最后一个: {sample}，位置: {j}")
                                                                            break
                                                                except Exception as e:
                                                                    logger.error(f"PCM样本解析错误: {e}")
                                                            
                                                            # 记录音频数据信息
                                                            hex_len = len(audio_hex)
                                                            bin_len = len(decoded_audio)
                                                            
                                                            # 检查数据长度，确保有有效数据
                                                            if bin_len > 0 and valid_pcm:
                                                                logger.debug(f"解析到有效音频数据: hex长度={hex_len}, 二进制长度={bin_len}字节")
                                                                
                                                                # 将音频数据加入发送队列
                                                                item = {
                                                                    "audio_data": decoded_audio,
                                                                    "is_first": False,
                                                                    "text": "",
                                                                    "is_final": False
                                                                }
                                                                await self.send_queue.put(item)
                                                                logger.debug(f"音频数据已加入队列: {len(decoded_audio)}字节")
                                                            else:
                                                                if not valid_pcm:
                                                                    logger.warning(f"跳过无效PCM数据块: hex长度={hex_len}, 数据可能已损坏")
                                                                elif bin_len == 0:
                                                                    logger.warning(f"跳过空音频数据块: hex长度={hex_len}")
                                                        else:
                                                            logger.warning(f"解码后的音频数据为空: hex长度={len(audio_hex)}")
                                                    except ValueError as hex_err:
                                                        logger.error(f"音频数据hex解码错误: {str(hex_err)}, audio_hex前20个字符: {audio_hex[:20]}, trace_id={trace_id}, requestid={request_id}")
                                    except json.JSONDecodeError as je:
                                        # 记录更详细的错误信息
                                        logger.warning(f"JSON解析错误: {str(je)}, 行内容前50个字符: {line[:50]}")
                                    except Exception as e:
                                        logger.error(f"处理data行异常: {str(e)}, trace_id={trace_id}, requestid={request_id}")
                                else:
                                    # 非data开头的行
                                    logger.debug(f"跳过非data行: {line[:50]}...")
                            
                            # 保留最后一行，可能不完整
                            buffer = lines[-1]
                
                # 处理完成后，发送最终标记
                item = {
                    "audio_data": b"",
                    "is_first": False,
                    "text": "",
                    "is_final": True
                }
                await self.send_queue.put(item)
                
                logger.info(f"MiniMax TTS请求完成，耗时: {time.time() - start_time:.2f}秒")
            
            except asyncio.TimeoutError:
                logger.error(f"MiniMax TTS请求超时: {text[:30]}...")
                # 通知客户端错误
                await websocket.send_json({
                    "type": "error",
                    "message": "TTS请求超时",
                    "session_id": self.session_id
                })
        except Exception as e:
            logger.error(f"MiniMax TTS处理错误: {e}\n{traceback.format_exc()}")
            # 通知客户端错误
            await websocket.send_json({
                "type": "error",
                "message": f"TTS错误: {str(e)}",
                "session_id": self.session_id
            })
    
    async def _process_send_queue(self, websocket: WebSocket) -> None:
        """处理发送队列中的音频数据
        
        Args:
            websocket: WebSocket连接
        """
        self.is_processing = True
        total_audio_size = 0
        audio_chunk_count = 0
        start_time = time.time()
        
        try:
            logger.info(f"音频发送队列处理任务已启动")
            while True:
                # 获取下一个待发送项目
                item = await self.send_queue.get()
                audio_data = item["audio_data"]
                is_final = item["is_final"]
                
                # 检查会话是否已中断
                from models.session import get_session
                session = get_session(self.session_id)
                if session.is_interrupted():
                    logger.info(f"会话已中断，跳过音频发送")
                    self.send_queue.task_done()
                    continue
                
                # 标记TTS正在进行
                session.is_tts_active = True
                
                try:
                    # 发送音频数据（如果有）
                    if audio_data:
                        # 音频统计数据累加
                        audio_size = len(audio_data)
                        total_audio_size += audio_size
                        audio_chunk_count += 1
                        
                        # 确保PCM数据是偶数字节长度（16位PCM每个采样点需要2字节）
                        if audio_size % 2 != 0:
                            logger.warning(f"PCM数据长度不是偶数字节 ({audio_size}字节)，将调整数据大小")
                            # 去掉最后一个字节以保持偶数长度
                            audio_data = audio_data[:-1]
                            audio_size -= 1
                        
                        # 只在第一次或较长间隔后分析PCM数据
                        if audio_chunk_count == 1 or audio_chunk_count % 10 == 0:
                            if audio_size > 0:
                                try:
                                    # 计算PCM音频基本统计信息
                                    import array
                                    samples = array.array('h')
                                    try:
                                        samples.frombytes(audio_data)
                                        if len(samples) > 0:
                                            min_val = min(samples)
                                            max_val = max(samples)
                                            avg_val = sum(samples) / len(samples)
                                            # 计算有效范围 (静音检测)
                                            range_val = max_val - min_val
                                            is_silence = range_val < 100  # 简单判断是否为静音
                                            
                                            log_level = logger.warning if is_silence else logger.info
                                            log_level(f"PCM音频分析: 样本数={len(samples)}, 范围={range_val}, 最小值={min_val}, 最大值={max_val}, 平均值={avg_val:.2f}, 静音={is_silence}")
                                    except Exception as e:
                                        logger.warning(f"PCM分析错误: {str(e)}")
                                except ImportError:
                                    pass
                        
                        # 发送音频数据到客户端
                        logger.debug(f"发送音频块 #{audio_chunk_count}: {audio_size}字节")
                        await websocket.send_bytes(audio_data)
                    
                    # 如果是最后一块数据，发送结束标记
                    if is_final:
                        duration = time.time() - start_time
                        logger.info(f"音频流结束: 总大小={total_audio_size}字节, 块数={audio_chunk_count}, 持续时间={duration:.2f}秒")
                        
                        # 发送音频结束标记
                        await websocket.send_json({
                            "type": "audio_end",
                            "session_id": self.session_id
                        })
                        
                        # 标记TTS已完成
                        session.is_tts_active = False
                except Exception as e:
                    logger.error(f"发送音频数据错误: {e}")
                    session.is_tts_active = False
                
                # 标记任务完成
                self.send_queue.task_done()
                
        except asyncio.CancelledError:
            logger.info("发送队列处理被取消")
        except Exception as e:
            logger.error(f"TTS发送队列处理异常: {e}")
        finally:
            self.is_processing = False
            logger.info(f"音频发送队列处理任务已结束: 总块数={audio_chunk_count}, 总大小={total_audio_size}字节")
    
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