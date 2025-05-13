import re
from typing import List

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

def clean_text(text: str) -> str:
    """清理文本，移除多余空格和特殊字符
    
    Args:
        text: 输入文本
        
    Returns:
        清理后的文本
    """
    # 移除多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    # 其他清理规则可以在这里添加
    return text 