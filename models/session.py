import time
import logging
import uuid
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

class SessionState:
    """管理用户会话状态"""
    
    def __init__(self, session_id: str = None):
        """初始化会话状态
        
        Args:
            session_id: 会话唯一标识符，如不提供则自动生成
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.is_processing_llm = False     # 是否正在处理LLM请求
        self.is_tts_active = False         # 是否正在进行TTS合成
        self.response_stream = None        # 当前响应流
        self.interrupt_requested = False   # 是否请求中断
        self.tts_processor = None          # TTS处理器
        self.last_activity = time.time()   # 最后活动时间
        self.asr_recognizer = None         # ASR识别器
    
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


# 全局会话状态字典
sessions: Dict[str, SessionState] = {}

def get_session(session_id: str) -> SessionState:
    """获取或创建会话状态
    
    Args:
        session_id: 会话ID
        
    Returns:
        会话状态对象
    """
    if session_id not in sessions:
        sessions[session_id] = SessionState(session_id)
    return sessions[session_id]

def remove_session(session_id: str) -> None:
    """移除会话
    
    Args:
        session_id: 会话ID
    """
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"会话已移除: {session_id}")

def get_all_sessions() -> Dict[str, SessionState]:
    """获取所有会话
    
    Returns:
        所有会话的字典
    """
    return sessions 