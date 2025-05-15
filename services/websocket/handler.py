import asyncio
import json
import struct
import time
from typing import Dict, Any, Optional
from loguru import logger

from fastapi import WebSocket, WebSocketDisconnect
from utils.audio import VoiceActivityDetector, parse_audio_header
from utils.text import split_into_sentences
from models.session import get_session, remove_session
from services.asr import create_asr_service
from services.llm import create_llm_service
from services.tts import create_tts_service, close_all_tts_services
from config import Config

# 音频日志记录间隔(秒)
AUDIO_LOG_INTERVAL = 5.0
last_audio_log_time = 0
audio_packets_received = 0

async def process_final_transcript(websocket: WebSocket, text: str, session_id: str) -> None:
    """处理最终转录文本，生成LLM响应并转换为语音
    
    Args:
        websocket: WebSocket连接对象
        text: 转录文本
        session_id: 会话ID
    """
    # 首先停止任何正在进行的TTS响应
    await stop_tts_and_clear_queues(websocket, session_id)
    
    # 获取会话状态
    session = get_session(session_id)
    session.clear_interrupt()  # 清除之前的中断标记
    session.is_processing_llm = True
    session.update_activity()  # 更新活动时间
    
    try:
        logger.info(f"LLM处理文本: '{text}' [sid:{session_id}]")
        
        # 向客户端发送LLM处理状态
        await websocket.send_json({
            "type": "llm_status",
            "status": "processing",
            "session_id": session_id
        })
        
        # 创建TTS处理器
        tts_processor = create_tts_service(session_id)
        if not tts_processor:
            await websocket.send_json({
                "type": "error",
                "message": "无法创建TTS服务",
                "session_id": session_id
            })
            return
            
        # 保存TTS处理器到会话状态
        session.tts_processor = tts_processor
        
        # 创建LLM服务
        llm_service = create_llm_service()
        if not llm_service:
            await websocket.send_json({
                "type": "error",
                "message": "无法创建LLM服务",
                "session_id": session_id
            })
            return
        
        # 从LLM流式收集文本的变量
        collected_response = ""
        text_buffer = ""
        sentences_queue = []  # 使用列表存储句子
        
        # 标记是否已经处理了第一句
        first_sentence_processed = False
        
        # 处理LLM流式回复
        try:
            # 保存流以便需要时中断
            session.response_stream = llm_service
            
            # 生成响应
            async for chunk in llm_service.generate_response(text):
                # 检查是否请求了中断
                if session.is_interrupted():
                    logger.info(f"检测到中断请求，停止LLM流 [sid:{session_id}]")
                    break
                    
                collected_response += chunk
                text_buffer += chunk
                
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
                            if not session.is_interrupted():
                                await tts_processor.synthesize_text(
                                    first_sentence, 
                                    websocket,
                                    is_first=True
                                )
                                first_sentence_processed = True
                        
                        # 处理队列中的其他句子
                        while len(sentences_queue) > 0:
                            # 检查是否请求了中断
                            if session.is_interrupted():
                                logger.info(f"中断请求，停止处理剩余句子 [sid:{session_id}]")
                                break
                                
                            sentence = sentences_queue.pop(0)
                            await tts_processor.synthesize_text(
                                sentence, 
                                websocket,
                                is_first=False
                            )
                        
                        # 清空缓冲区，保留可能未完成的部分
                        last_sentence = new_sentences[-1]
                        if text_buffer.endswith(last_sentence):
                            text_buffer = ""
                        else:
                            text_buffer = text_buffer[text_buffer.rfind(last_sentence) + len(last_sentence):]
                
                # 向客户端发送当前文本状态
                if not session.is_interrupted():
                    await websocket.send_json({
                        "type": "llm_response",
                        "content": collected_response,
                        "is_complete": False,
                        "session_id": session_id
                    })
            
            # 处理剩余的文本
            if text_buffer and not session.is_interrupted():
                sentences_queue.append(text_buffer)
                text_buffer = ""
            
            # 处理队列中的所有剩余句子
            while len(sentences_queue) > 0 and not session.is_interrupted():
                sentence = sentences_queue.pop(0)
                await tts_processor.synthesize_text(
                    sentence, 
                    websocket,
                    is_first=not first_sentence_processed
                )
                first_sentence_processed = True
            
        except asyncio.TimeoutError:
            logger.error("LLM流式处理超时")
            await websocket.send_json({
                "type": "error",
                "message": "LLM流式处理超时",
                "session_id": session_id
            })
        
        # 发送完整回复（如果没有被中断）
        if collected_response and not session.is_interrupted():
            await websocket.send_json({
                "type": "llm_response",
                "content": collected_response,
                "is_complete": True,
                "session_id": session_id
            })
            
            # 记录历史
            logger.info(f"LLM响应完成: '{collected_response}'")
        elif session.is_interrupted():
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
        session.is_processing_llm = False
        session.is_tts_active = False
        session.response_stream = None

async def stop_tts_and_clear_queues(websocket: WebSocket, session_id: str) -> None:
    """停止TTS响应并清空所有队列
    
    Args:
        websocket: WebSocket连接对象
        session_id: 会话ID
    """
    # 获取会话状态
    session = get_session(session_id)
    
    # 标记中断
    session.request_interrupt()
    
    # 中断TTS
    if session.tts_processor:
        await session.tts_processor.interrupt()
    
    # 通知客户端停止任何音频播放
    await websocket.send_json({
        "type": "tts_stop",
        "session_id": session_id
    })

async def handle_websocket_connection(websocket: WebSocket) -> None:
    """处理WebSocket连接
    
    Args:
        websocket: WebSocket连接对象
    """
    await websocket.accept()
    
    # 获取当前事件循环
    loop = asyncio.get_running_loop()
    
    # 生成唯一会话ID
    session_id = get_session(None).session_id
    logger.info(f"新WebSocket连接已建立，会话ID: {session_id}")
    
    # 获取会话状态
    session = get_session(session_id)
    
    # 创建语音活动检测器
    voice_detector = VoiceActivityDetector()
    
    # 初始化Azure识别器
    asr_service = create_asr_service()
    if not asr_service:
        await websocket.send_json({
            "type": "error",
            "message": "无法创建ASR服务",
            "session_id": session_id
        })
        await websocket.close()
        return
    
    # 保存ASR服务到会话状态
    session.asr_recognizer = asr_service
    
    # 设置WebSocket和事件循环
    asr_service.set_websocket(websocket, loop, session_id)
    asr_service.setup_handlers()
    
    try:
        # 开始识别
        await asr_service.start_recognition()
        
        # 处理传入的数据
        while True:
            data = await websocket.receive()
            
            if "bytes" in data:
                # 处理二进制音频数据
                audio_data = data["bytes"]
                if audio_data and len(audio_data) >= 10:  # 至少需要头部(8字节)加一个16位样本(2字节)
                    try:
                        # 解析头部信息
                        timestamp, status_flags, pcm_data = parse_audio_header(audio_data)
                        
                        # 限制音频日志输出频率，每5秒记录一次汇总信息
                        global last_audio_log_time, audio_packets_received
                        audio_packets_received += 1
                        current_time = time.time()
                        
                        if Config.DEBUG and current_time - last_audio_log_time > AUDIO_LOG_INTERVAL:
                            logger.debug(f"音频接收统计: {audio_packets_received}个数据包 (过去{AUDIO_LOG_INTERVAL}秒)")
                            last_audio_log_time = current_time
                            audio_packets_received = 0
                        
                        # 检测是否有语音活动
                        has_voice = voice_detector.detect(pcm_data)
                        
                        # 检查是否有正在进行的TTS响应，如果有则发送打断信令
                        if has_voice and (session.is_tts_active or session.is_processing_llm):
                            # 只有当检测到显著的语音活动时才发送打断信令
                            if voice_detector.has_continuous_voice():
                                logger.info(f"检测到明显的语音输入，打断当前响应，会话ID: {session_id}")
                                
                                # 停止所有TTS和清空队列
                                await stop_tts_and_clear_queues(websocket, session_id)
                                
                                # 重置语音检测器
                                voice_detector.reset()
                        
                        # 继续处理音频
                        asr_service.feed_audio(pcm_data)
                    except Exception as e:
                        logger.error(f"处理音频头部出错: {e}")
                        # 如果头部解析失败，尝试直接处理原始数据
                        if len(audio_data) > 2:
                            asr_service.feed_audio(audio_data)
                else:
                    logger.warning("收到无效的音频数据: 数据为空或长度不足")
            
            elif "text" in data:
                # 处理文本命令
                try:
                    message = json.loads(data["text"])
                    cmd_type = message.get("type")
                    
                    if cmd_type == "stop":
                        await asr_service.stop_recognition()
                        
                        # 停止所有TTS和LLM进程
                        logger.info(f"停止命令接收，停止所有TTS和LLM进程，会话ID: {session_id}")
                        
                        # 停止TTS和清空队列
                        await stop_tts_and_clear_queues(websocket, session_id)
                        
                        # 通知客户端已完全停止
                        await websocket.send_json({
                            "type": "stop_acknowledged",
                            "message": "所有处理已停止",
                            "queues_cleared": True,
                            "session_id": session_id
                        })
                    elif cmd_type == "start":
                        await asr_service.start_recognition()
                    elif cmd_type == "reset":
                        await asr_service.stop_recognition()
                        
                        # 等待一段时间确保前一个会话完全停止
                        await asyncio.sleep(1)
                        
                        # 创建新的识别器实例
                        new_asr_service = create_asr_service()
                        if new_asr_service:
                            # 保存新ASR服务到会话状态
                            session.asr_recognizer = new_asr_service
                            
                            # 设置WebSocket和事件循环
                            new_asr_service.set_websocket(websocket, loop, session_id)
                            new_asr_service.setup_handlers()
                            await new_asr_service.start_recognition()
                            
                            # 更新当前使用的ASR服务
                            asr_service = new_asr_service
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "message": "无法创建新的ASR服务",
                                "session_id": session_id
                            })
                    elif cmd_type == "interrupt":
                        # 处理中断命令
                        logger.info(f"接收到中断命令，会话ID: {session_id}")
                        
                        # 标记中断
                        session.request_interrupt()
                        
                        # 停止TTS和清空队列
                        await stop_tts_and_clear_queues(websocket, session_id)
                        
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
        logger.info(f"WebSocket断开连接，会话ID: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"WebSocket错误: {str(e)}"
            })
        except:
            pass
    finally:
        # 停止识别
        if asr_service:
            try:
                await asr_service.stop_recognition()
            except:
                pass
        
        # 关闭所有TTS资源
        try:
            if session.tts_processor:
                await session.tts_processor.close()
        except:
            pass
        
        # 清理会话状态
        remove_session(session_id)
        
        # 尝试关闭WebSocket（如果尚未关闭）
        try:
            await websocket.close()
        except:
            pass

async def cleanup_inactive_sessions() -> None:
    """定期清理不活跃的会话"""
    from models.session import get_all_sessions
    
    while True:
        try:
            # 等待一段时间
            await asyncio.sleep(60)  # 每分钟检查一次
            
            # 获取所有会话
            sessions = get_all_sessions()
            
            # 查找并清理不活跃的会话
            inactive_session_ids = []
            for session_id, state in sessions.items():
                if state.is_inactive(timeout_seconds=Config.SESSION_TIMEOUT):
                    inactive_session_ids.append(session_id)
            
            # 清理不活跃的会话
            for session_id in inactive_session_ids:
                logger.info(f"清理不活跃会话: {session_id}")
                
                # 尝试中断任何活动的处理
                try:
                    if sessions[session_id].tts_processor:
                        await sessions[session_id].tts_processor.interrupt()
                except:
                    pass
                
                # 删除会话状态
                remove_session(session_id)
            
        except Exception as e:
            logger.error(f"会话清理错误: {e}")
            await asyncio.sleep(60)  # 发生错误时，等待一分钟后重试