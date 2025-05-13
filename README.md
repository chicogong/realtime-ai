# 实时AI语音对话系统设计文档

## 1. 系统概述

本系统设计为一个低延迟、高质量的实时语音对话平台，允许用户通过麦克风与AI进行自然对话。系统采用流式处理架构，支持动态对话节奏，包括实时打断和智能转向检测。

## 2. 架构设计

### 2.1 系统组件
![系统架构图]

- **客户端**：基于Web浏览器的轻量级界面
- **通信层**：WebSocket双向实时通信
- **服务器**：FastAPI异步处理框架
- **语音处理管道**：
  - 语音到文本转换(STT)
  - 大语言模型(LLM)处理
  - 文本到语音合成(TTS)
- **支持服务**：转向检测、对话状态管理

### 2.2 数据流程图
```
客户端麦克风 → PCM音频采集 → WebSocket传输 → 服务端STT → LLM处理
         ↑                                                  ↓
客户端扬声器 ← PCM音频播放 ← WebSocket传输 ← 服务端TTS ← 文本响应
```

## 3. 关键技术规范

### 3.1 音频传输规范

#### 3.1.1 客户端到服务器（用户语音）
- **音频格式**: 16位PCM
- **采样率**: 24kHz
- **声道数**: 单声道
- **传输协议**: WebSocket二进制传输
- **分块大小**: 2048样本/块
- **消息格式**: 
  ```
  [8字节头部][音频数据]
  头部：[4字节时间戳][4字节状态标志]
  ```

**状态标志位定义**:
- **位0-7**: 音频能量值（0-255）
- **位8**: 麦克风静音状态（1=静音，0=活动）
- **位9**: 首个音频块标记（1=是，0=否）
- **位10**: 最后音频块标记（1=是，0=否）
- **位11-31**: 保留供将来使用

**状态标志位使用示例**:
```javascript
// 创建头部
const headerView = new DataView(buffer, 0, 8);

// 设置时间戳 (毫秒)
const timestamp = Date.now();
headerView.setUint32(0, timestamp, true); // 小端序

// 状态标志
let statusFlags = 0;

// 计算音频能量 (0-255)
const energy = Math.min(255, Math.floor(detectAudioLevel(audioData) * 1000));
statusFlags |= energy & 0xFF; // 存储在低8位

// 设置麦克风静音标志 (位 8)
if (isAudioSilent(audioData)) {
    statusFlags |= (1 << 8);
}

// 设置首个音频块标记 (位 9)
if (isFirstBlock) {
    statusFlags |= (1 << 9);
}

// 写入状态标志
headerView.setUint32(4, statusFlags, true); // 小端序
```

#### 3.1.2 服务器到客户端（AI语音）
- **音频格式**: 16位PCM
- **采样率**: 24kHz
- **声道数**: 单声道
- **传输协议**: WebSocket JSON消息
- **编码**: Base64编码音频数据
- **消息格式**: `{"type": "audio_data", "audio": "Base64编码PCM"}`

### 3.2 语音处理规范

#### 3.2.1 语音识别(STT)
- **模型**: Whisper (faster-whisper实现)
- **处理模式**: 流式增量处理
- **工作采样率**: 16kHz (内部重采样)
- **支持语言**: 多语言，默认英语
- **增强功能**: 句子完成预测，实时部分转录

#### 3.2.2 文本生成(LLM)
- **支持后端**: 
  - Ollama (本地部署)
  - OpenAI API
  - LMStudio (本地API兼容)
- **处理模式**: 流式返回
- **上下文管理**: 维护对话历史
- **系统提示**: 可配置的角色设定

#### 3.2.3 语音合成(TTS)
- **支持引擎**:
  - Coqui XTTS (高质量本地)
  - Kokoro (轻量级)
  - Orpheus (另一选项)
- **处理模式**: 流式生成和播放
- **延迟优化**: 提前开始合成
- **语音定制**: 可切换声音和语速

### 3.3 协议设计

#### 3.3.1 WebSocket消息协议

所有非二进制的消息使用JSON格式，包含type字段指定消息类型：

| 消息类型 | 方向 | 格式 | 用途 |
|---------|------|------|------|
| `partial_transcript` | 服务器→客户端 | `{"type": "", "content": "文本partial_transcript", "session_id": "会话ID"}` | 实时转录字幕(用户) |
| `final_transcript` | 服务器→客户端 | `{"type": "final_transcript", "content": "文本", "session_id": "会话ID"}` | 最终转录结果(用户) |
| `llm_status` | 服务器→客户端 | `{"type": "llm_status", "status": "processing", "session_id": "会话ID"}` | LLM处理状态 |
| `llm_response` | 服务器→客户端 | `{"type": "llm_response", "content": "文本", "is_complete": true/false, "session_id": "会话ID"}` | AI的文本回复 |
| `tts_sentence_start` | 服务器→客户端 | `{"type": "tts_sentence_start", "sentence_id": "句子ID", "text": "文本", "is_first": true/false, "session_id": "会话ID"}` | TTS合成开始 |
| `tts_sentence_end` | 服务器→客户端 | `{"type": "tts_sentence_end", "sentence_id": "句子ID", "text": "文本", "session_id": "会话ID"}` | TTS合成结束 |
| `status` | 服务器→客户端 | `{"type": "status", "status": "listening/stopped", "session_id": "会话ID"}` | 系统状态更新 |
| `error` | 服务器→客户端 | `{"type": "error", "message": "错误信息", "session_id": "会话ID"}` | 错误消息 |
| `server_interrupt` | 服务器→客户端 | `{"type": "server_interrupt", "message": "打断信息", "session_id": "会话ID"}` | 服务器端打断通知 |
| `stop` | 客户端→服务器 | `{"type": "stop"}` | 停止录音和处理 |
| `start` | 客户端→服务器 | `{"type": "start"}` | 开始录音 |
| `reset` | 客户端→服务器 | `{"type": "reset"}` | 重置对话状态 |
| `interrupt` | 客户端→服务器 | `{"type": "interrupt"}` | 客户端请求打断当前响应 |

#### 3.3.2 二进制音频数据协议

服务器通过WebSocket发送二进制PCM音频数据用于TTS输出：

**音频数据格式**:
```
[4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
```

- **请求ID**: 唯一标识一个TTS请求
- **块序号**: 当前音频块的序号，从0开始
- **时间戳**: 毫秒级Unix时间戳
- **PCM数据**: 原始16位PCM音频数据

此格式允许客户端正确组装和播放流式音频数据，同时跟踪每个请求的进度。

#### 3.3.3 转录字幕协议详情

**部分转录消息(`partial_transcript`)**
- 触发条件：语音识别引擎产生更新的部分转录
- 频率：约每100-300ms
- 行为：客户端应更新用户输入区域，显示"正在输入"状态
- 特性：可能包含错误，后续会自动修正
- 示例：
  ```json
  {
    "type": "partial_transcript",
    "content": "今天天气真不",
    "session_id": "sess_12345abcde"
  }
  ```

**最终转录消息(`final_transcript`)**
- 触发条件：语音识别引擎确认最终结果
- 行为：客户端将消息显示为完整的用户对话气泡
- 特性：高准确度，代表最终确认的用户输入
- 示例：
  ```json
  {
    "type": "final_transcript", 
    "content": "今天天气真不错！",
    "session_id": "sess_12345abcde"
  }
  ```

#### 3.3.4 打断机制

系统支持双向打断机制，确保对话自然流畅：

**服务器检测到用户打断**:
1. 当用户在AI响应播放过程中开始说话
2. 服务器通过语音活动检测器识别显著的语音输入
3. 发送`server_interrupt`消息通知客户端
4. 停止当前的TTS和LLM处理

**客户端主动打断**:
1. 用户点击界面上的打断按钮
2. 客户端发送`interrupt`消息
3. 服务器停止当前TTS和LLM处理
4. 服务器回复`interrupt_acknowledged`确认

#### 3.3.5 会话管理

系统使用唯一会话ID管理用户对话状态：

- 每个WebSocket连接创建一个新会话
- 会话ID包含在所有消息中，确保正确路由
- 支持超时清理不活跃会话（默认10分钟）
- 会话状态包括：正在处理的LLM请求、TTS活动状态、是否请求中断等

## 4. 核心功能实现

### 4.1 低延迟音频传输
- 使用WebSocket二进制传输减少开销
- 实现缓冲池管理减少内存分配
- 分块处理平衡实时性和网络效率

### 4.2 实时打断机制
- 客户端通过状态标志位标记AI语音播放状态
- 检测用户语音输入同时停止当前TTS播放
- 取消正在进行的LLM生成请求

### 4.3 转向检测算法
- 动态沉默阈值适应用户说话风格
- 句子完成概率预测
- 上下文相关转向判断

### 4.4 并行处理流水线
- 音频采集与STT并行处理
- LLM生成与TTS合成重叠执行
- 使用异步队列管理音频块

## 5. 技术栈选择

### 5.1 前端
- **Web Audio API**: 音频采集和播放
- **AudioWorklet**: 实时音频处理
- **WebSocket**: 实时通信
- **原生JavaScript**: 轻量级UI实现

### 5.2 后端
- **FastAPI**: 异步Web框架
- **Python 3.10+**: 核心处理逻辑
- **RealtimeSTT**: 语音识别库
- **RealtimeTTS**: 语音合成库
- **PyTorch/CUDA**: 支持GPU加速的ML框架

### 5.3 部署
- **Docker/Docker Compose**: 容器化部署
- **NVIDIA Container Toolkit**: GPU支持
- **环境变量配置**: 灵活设置参数

## 6. 环境变量配置

系统需要以下环境变量才能正常运行，可以创建一个`.env`文件在项目根目录：

### 6.1 Azure语音服务
```
AZURE_SPEECH_KEY=你的Azure语音服务密钥
AZURE_SPEECH_REGION=你的Azure语音服务区域
```

### 6.2 LLM配置
```
# OpenAI或兼容API
OPENAI_API_KEY=你的API密钥
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选：自定义OpenAI兼容的API基础URL
OPENAI_MODEL=gpt-3.5-turbo  # 默认使用的模型
```

可以使用标准OpenAI API，也可以配置为使用其他兼容OpenAI API的服务，如Azure OpenAI或本地部署的LLM服务。

## 7. 性能考量

### 7.1 延迟目标
- **麦克风到文本**: <300ms
- **文本到首个LLM输出**: <500ms
- **首个LLM输出到语音**: <200ms
- **端到端首次响应**: <1000ms

### 7.2 硬件需求
- **推荐**: NVIDIA GPU (8GB+)
- **最低**: 多核CPU (8核+)
- **内存**: 16GB+
- **网络**: 低延迟连接，稳定带宽

### 7.3 扩展性
- 模块化设计允许替换组件
- 独立的音频处理、LLM和TTS模块
- 可配置的参数支持不同场景优化

## 8. 安全与隐私

- 所有处理可本地完成，无需外部服务
- 音频数据不持久化存储
- 支持SSL/TLS加密WebSocket连接
- 配置隔离确保安全部署

## 9. 未来扩展方向

- 多语言支持增强
- 情感识别整合
- 多用户会话支持
- 视觉模态集成
- 移动端本地处理优化

## 10. 轻量级云服务实现方案

此章节描述如何使用云服务构建轻量级实现，特别针对中文短对话场景，避免复杂的本地部署。

### 10.1 简化架构

```
客户端麦克风 → PCM音频采集 → WebSocket → Azure语音识别(ASR) → OpenAI LLM
         ↑                                                       ↓
客户端扬声器 ← PCM流式播放 ← WebSocket ← Azure语音合成(TTS) ← AI文本响应
```

### 10.2 云服务配置

#### 10.2.1 Azure语音服务(ASR)
- **服务类型**: Azure语音服务 (Speech Service)
- **区域**: 东亚或其他支持中文的区域
- **模式**: 实时语音转文字 (Speech-to-Text)
- **语言设置**: 
  - 主要语言: `zh-CN`
  - 方言识别: 可启用（普通话、粤语等）
- **API配置**:
  - 采用WebSocket API进行流式传输
  - 采样率: 16kHz
  - 音频格式: 16位PCM
  - 分块大小: 1024样本/次
- **特殊配置**:
  - 启用中文专项优化
  - 启用标点符号自动添加
  - 静音检测阈值: 0.8秒

#### 10.2.2 OpenAI LLM
- **模型选择**: 
  - 主推: GPT-4 Turbo
  - 备选: GPT-3.5 Turbo（成本考虑）
- **系统提示**:
  ```
  你是一个友好的中文AI助手，擅长简短对话。请以自然、亲切的方式回应用户，保持回答简洁（通常不超过2-3句话）。
  ```
- **参数设置**:
  - temperature: 0.7
  - top_p: 0.95
  - max_tokens: 150
  - presence_penalty: 0.6
- **API配置**:
  - 使用流式响应API
  - 安全令牌轮换机制
  - 异常重试策略

#### 10.2.3 Azure TTS
- **服务类型**: Azure语音服务 (Speech Service)
- **语音选择**:
  - 主推: `zh-CN-XiaoxiaoNeural` (女声)
  - 备选: `zh-CN-YunxiNeural` (男声)
- **音频格式设置**:
  - 输出格式: **原始16位PCM**
  - 采样率: 24kHz
  - 声道: 单声道
- **流式配置**:
  - 使用Azure REST API流式合成
  - 分块PCM返回 (每块大约4KB)
  - 低延迟模式启用
- **SSML增强**:
  - 语速调整: +5%
  - 语调自然度: 高
  - 语句间停顿调整

### 10.3 详细流程设计

#### 10.3.1 通信协议扩展

**Azure ASR流式识别协议**

为支持与Azure ASR的流式通信，扩展WebSocket消息协议：

```json
// 1. 初始化ASR会话消息
{
  "type": "azure_asr_init",
  "language": "zh-CN",
  "format": {
    "encoding": "pcm",
    "sample_rate": 16000,
    "channels": 1,
    "bits_per_sample": 16
  }
}

// 2. ASR会话状态消息
{
  "type": "azure_asr_status",
  "status": "listening", // "listening", "processing", "error"
  "session_id": "asr-session-123456"
}

// 3. 音频通道状态消息
{
  "type": "audio_channel_status",
  "channel": "asr_input", // "asr_input" 或 "tts_output"
  "active": true,
  "encoding": "pcm",
  "sample_rate": 16000
}
```

**Azure TTS流式合成协议**

```json
// 1. TTS请求消息
{
  "type": "azure_tts_request",
  "text": "要合成的文本",
  "voice": "zh-CN-XiaoxiaoNeural",
  "format": {
    "encoding": "pcm",
    "sample_rate": 24000,
    "bits_per_sample": 16,
    "channels": 1
  }
}

// 2. TTS状态消息
{
  "type": "azure_tts_status",
  "status": "synthesizing", // "synthesizing", "completed", "error"
  "progress": 0.45,         // 合成进度百分比
  "request_id": "tts-req-789012"
}

// 3. PCM音频数据消息 (二进制)
// 格式: [4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
```

#### 10.3.2 端到端流程图

```
┌──────────┐       ┌────────────┐       ┌────────────┐      ┌──────────┐
│          │       │            │       │            │      │          │
│  客户端  │◄──────►   服务器   │◄──────►  Azure ASR  │      │  OpenAI  │
│          │       │            │       │            │      │          │
└────┬─────┘       └──────┬─────┘       └────────────┘      └────┬─────┘
     │                    │                                      │
     │ WebSocket连接      │                                      │
     │──────────────────►│                                      │
     │                    │                                      │
     │ 发送azure_asr_init │                                      │
     │──────────────────►│       初始化Azure ASR会话             │
     │                    │─────────────────────────────►        │
     │                    │                                      │
     │ 接收asr_status     │       ASR会话状态返回                │
     │◄──────────────────│◄─────────────────────────────        │
     │                    │                                      │
     │ 发送PCM音频数据    │                                      │
     │──────────────────►│       流式发送音频                    │
     │                    │─────────────────────────────►        │
     │                    │                                      │
     │ 接收partial_transcript  ASR部分结果                       │
     │◄──────────────────│◄─────────────────────────────        │
     │                    │                                      │
     │                    │       检测语音停止                   │
     │                    │─────────────────────────────►        │
     │                    │                                      │
     │ 接收final_transcript    ASR最终结果                       │
     │◄──────────────────│◄─────────────────────────────        │
     │                    │                                      │
     │                    │       调用OpenAI API流式生成         │
     │                    │──────────────────────────────────────►
     │                    │                                      │
     │ 接收partial_assistant_text  OpenAI流式回复               │
     │◄──────────────────│◄──────────────────────────────────────
     │                    │                                      │
┌────┴─────┐       ┌──────┴─────┐       ┌────────────┐      ┌────┴─────┐
│          │       │            │       │            │      │          │
│  客户端  │◄──────►   服务器   │◄──────►  Azure TTS  │      │  OpenAI  │
│          │       │            │       │            │      │          │
└────┬─────┘       └──────┬─────┘       └────────────┘      └────┬─────┘
     │                    │                                      │
     │                    │       初始化TTS请求                  │
     │                    │─────────────────────────────►        │
     │                    │                                      │
     │ 接收azure_tts_status    TTS状态更新                       │
     │◄──────────────────│◄─────────────────────────────        │
     │                    │                                      │
     │ 接收PCM音频数据    │       流式返回PCM音频                │
     │◄──────────────────│◄─────────────────────────────        │
     │                    │                                      │
     │ 发送tts_start      │                                      │
     │──────────────────►│                                      │
     │                    │                                      │
     │ 接收assistant_text │       OpenAI完整回复                 │
     │◄──────────────────│◄──────────────────────────────────────
     │                    │                                      │
```

### 10.3.3 流式PCM处理实现

**Azure ASR 流式处理模块**:
```python
import azure.cognitiveservices.speech as speechsdk
import asyncio
import queue
import threading

class AzureStreamingRecognizer:
    def __init__(self, subscription_key, region, language="zh-CN"):
        self.subscription_key = subscription_key
        self.region = region
        self.language = language
        self.audio_queue = queue.Queue()
        self.push_stream = None
        self.recognizer = None
        self._setup_recognizer()
        
    def _setup_recognizer(self):
        # 创建推送流
        self.push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        
        # 创建语音配置
        speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription_key, region=self.region)
        speech_config.speech_recognition_language = self.language
        
        # 流式识别器
        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, 
            audio_config=audio_config)
            
    def set_handlers(self, on_partial, on_final, on_error):
        """设置回调处理函数"""
        self.recognizer.recognizing.connect(
            lambda evt: on_partial(evt.result.text))
            
        self.recognizer.recognized.connect(
            lambda evt: on_final(evt.result.text))
            
        self.recognizer.canceled.connect(
            lambda evt: on_error(f"错误: {evt.result.cancellation_details}"))
    
    def feed_audio(self, audio_chunk):
        """处理传入的PCM音频块"""
        if self.push_stream:
            self.push_stream.write(audio_chunk)
    
    async def start_continuous_recognition(self):
        """启动连续识别"""
        return await asyncio.to_thread(self.recognizer.start_continuous_recognition)
    
    async def stop_continuous_recognition(self):
        """停止连续识别"""
        return await asyncio.to_thread(self.recognizer.stop_continuous_recognition)
```

**Azure TTS 流式PCM输出模块**:
```python
import azure.cognitiveservices.speech as speechsdk
import asyncio
import io
import struct
import time

class AzureTTSStreamingProcessor:
    def __init__(self, subscription_key, region, voice_name="zh-CN-XiaoxiaoNeural"):
        self.speech_config = speechsdk.SpeechConfig(
            subscription=subscription_key, region=region)
        self.speech_config.speech_synthesis_voice_name = voice_name
        
        # 配置PCM格式输出
        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm)
            
        # 使用PullAudioOutputStream以访问原始PCM流
        self.pull_stream = speechsdk.audio.PullAudioOutputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self.pull_stream)
        
        self.synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config, 
            audio_config=audio_config)
        
        # 请求ID计数器
        self.request_counter = 0
        
    async def synthesize_speech_streaming(self, text, callbacks=None):
        """将文本转换为流式PCM音频"""
        request_id = self._generate_request_id()
        
        # 创建SSML
        ssml = f"""
        <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
            <voice name="{self.speech_config.speech_synthesis_voice_name}">
                <prosody rate="+5%">
                    {text}
                </prosody>
            </voice>
        </speak>
        """
        
        # 开始合成 (异步执行避免阻塞)
        self.synthesizer.speak_ssml_async(ssml).get()
        
        # 使用协程处理流式PCM数据
        return await self._stream_pcm_data(request_id, callbacks)
    
    async def _stream_pcm_data(self, request_id, callbacks):
        """从PullAudioOutputStream读取PCM数据并流式发送"""
        if not callbacks or not callbacks.on_audio_data:
            return False
            
        # 创建流式处理任务
        buffer_size = 4096  # 约4KB块
        bytes_read = 0
        chunk_counter = 0
        
        # 读取PCM流并分块发送
        while True:
            # 从流中获取一块数据 
            audio_buffer = bytes(buffer_size)
            filled_size = await asyncio.to_thread(
                self.pull_stream.read, audio_buffer)
                
            if filled_size == 0:
                break  # 流结束
                
            # 构建带有元数据的二进制消息
            header = struct.pack(">III", request_id, chunk_counter, int(time.time() * 1000))
            data_to_send = header + audio_buffer[:filled_size]
            
            # 发送数据块
            await callbacks.on_audio_data(data_to_send)
            
            # 更新计数器
            bytes_read += filled_size
            chunk_counter += 1
            
            # 模拟处理时间，避免过载
            await asyncio.sleep(0.01)
        
        # 合成完成
        if callbacks.on_synthesis_complete:
            await callbacks.on_synthesis_complete(request_id, bytes_read)
            
        return True
        
    def _generate_request_id(self):
        """生成唯一请求ID"""
        self.request_counter += 1
        return self.request_counter
```

**OpenAI流式接口**:
```python
import openai
import asyncio
import time

class OpenAIStreamingProcessor:
    def __init__(self, api_key, model="gpt-4-turbo"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = "你是一个友好的中文AI助手，擅长简短对话。请以自然、亲切的方式回应用户，保持回答简洁（通常不超过2-3句话）。"
        
    async def generate_response_streaming(self, user_text, history=None, callbacks=None):
        """生成流式文本响应"""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # 添加历史记录
        if history:
            messages.extend(history)
            
        # 添加当前用户消息
        messages.append({"role": "user", "content": user_text})
        
        # 创建流式响应
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=150,
            top_p=0.95,
            presence_penalty=0.6,
            stream=True
        )
        
        # 实时流式处理响应
        collected_messages = []
        start_time = time.time()
        
        async for chunk in stream:
            delta = chunk.choices[0].delta
            
            # 提取token文本
            if delta.content:
                token = delta.content
                collected_messages.append(token)
                
                # 回调通知新token
                if callbacks and callbacks.on_llm_token:
                    token_info = {
                        "token": token,
                        "elapsed": time.time() - start_time
                    }
                    await callbacks.on_llm_token(token_info)
        
        # 完整响应
        full_reply = "".join(collected_messages)
        if callbacks and callbacks.on_llm_complete:
            await callbacks.on_llm_complete(full_reply)
            
        return full_reply
```

### 10.3.4 统一回调接口定义

为确保各组件之间协调工作，定义一套标准回调接口：

```python
class VoiceChatCallbacks:
    """语音聊天系统回调接口"""
    
    async def on_connection_established(self, session_info):
        """WebSocket连接建立时调用"""
        pass
        
    async def on_partial(self, text):
        """语音识别部分结果"""
        pass
        
    async def on_final(self, text):
        """语音识别最终结果"""
        pass
        
    async def on_llm_token(self, token_info):
        """LLM流式生成的单个token"""
        pass
        
    async def on_llm_complete(self, text):
        """LLM完整响应生成完毕"""
        pass
        
    async def on_audio_data(self, binary_data):
        """TTS生成的音频数据块"""
        pass
        
    async def on_synthesis_complete(self, request_id, total_bytes):
        """TTS合成完成"""
        pass
        
    async def on_error(self, error_info):
        """任何组件产生错误"""
        pass
        
    async def on_silence_detected(self, duration):
        """检测到静音"""
        pass
        
    async def on_session_end(self):
        """会话结束"""
        pass
```

### 10.4 前端处理流程

#### 10.4.1 PCM流式接收与播放

```javascript
// AudioProcessor.js
class AudioProcessor {
    constructor() {
        this.context = new AudioContext();
        this.pcmProcessor = null;
        this.pcmQueue = [];
        this.isPlaying = false;
        this.setupWorklet();
    }
    
    async setupWorklet() {
        await this.context.audioWorklet.addModule('/static/pcm-processor.js');
        this.pcmProcessor = new AudioWorkletNode(this.context, 'pcm-stream-processor');
        this.pcmProcessor.connect(this.context.destination);
        
        // 设置消息处理
        this.pcmProcessor.port.onmessage = (event) => {
            if (event.data.type === 'buffer_empty') {
                this.isPlaying = false;
            } else if (event.data.type === 'playing') {
                this.isPlaying = true;
            }
        };
    }
    
    // 处理接收到的二进制PCM数据
    processPCMData(binaryData) {
        // 解析头部信息
        const headerView = new DataView(binaryData.slice(0, 12));
        const requestId = headerView.getUint32(0);
        const chunkIndex = headerView.getUint32(4);
        const timestamp = headerView.getUint32(8);
        
        // 提取PCM数据
        const pcmData = binaryData.slice(12);
        
        // 转换为Float32Array (16位PCM到Float32)
        const pcmInt16 = new Int16Array(pcmData);
        const pcmFloat32 = new Float32Array(pcmInt16.length);
        
        for (let i = 0; i < pcmInt16.length; i++) {
            // 转换范围: [-32768, 32767] -> [-1.0, 1.0]
            pcmFloat32[i] = pcmInt16[i] / 32768.0;
        }
        
        // 发送到AudioWorklet处理
        this.pcmProcessor.port.postMessage({
            type: 'pcm_data',
            requestId: requestId,
            chunkIndex: chunkIndex,
            audioData: pcmFloat32.buffer,
            timestamp: timestamp
        }, [pcmFloat32.buffer]); // 使用transferable对象提高性能
    }
}
```

#### 10.4.2 WebSocket消息处理

```javascript
// WebSocketManager.js
class WebSocketManager {
    constructor(url, audioProcessor) {
        this.url = url;
        this.socket = null;
        this.audioProcessor = audioProcessor;
        this.connected = false;
        this.callbacks = {};
    }
    
    connect() {
        this.socket = new WebSocket(this.url);
        
        this.socket.onopen = (event) => {
            this.connected = true;
            this.triggerCallback('open', event);
            
            // 发送ASR初始化消息
            this.sendJSON({
                type: 'azure_asr_init',
                language: 'zh-CN',
                format: {
                    encoding: 'pcm',
                    sample_rate: 16000,
                    channels: 1,
                    bits_per_sample: 16
                }
            });
        };
        
        this.socket.onmessage = (event) => {
            // 区分文本消息和二进制消息
            if (typeof event.data === 'string') {
                try {
                    const jsonData = JSON.parse(event.data);
                    this.handleJSONMessage(jsonData);
                } catch (e) {
                    console.error('无效的JSON消息', e);
                }
            } else {
                // 二进制消息直接传递给音频处理器
                this.audioProcessor.processPCMData(event.data);
            }
        };
        
        this.socket.onclose = (event) => {
            this.connected = false;
            this.triggerCallback('close', event);
        };
        
        this.socket.onerror = (error) => {
            this.triggerCallback('error', error);
        };
    }
    
    handleJSONMessage(data) {
        const type = data.type;
        
        switch (type) {
            case 'partial_transcript':
                this.triggerCallback('partialTranscript', data.content);
                break;
                
            case 'final_transcript':
                this.triggerCallback('finalTranscript', data.content);
                break;
                
            case 'partial_assistant_text':
                this.triggerCallback('partialAssistantText', data.content);
                break;
                
            case 'assistant_text':
                this.triggerCallback('assistantText', data.content);
                break;
                
            case 'azure_asr_status':
            case 'azure_tts_status':
                this.triggerCallback('status', data);
                break;
                
            case 'error':
                this.triggerCallback('error', data);
                break;
                
            default:
                console.log('未处理的消息类型:', type, data);
        }
    }
    
    sendJSON(data) {
        if (this.connected) {
            this.socket.send(JSON.stringify(data));
        }
    }
    
    sendBinary(data) {
        if (this.connected) {
            this.socket.send(data);
        }
    }
    
    on(event, callback) {
        this.callbacks[event] = callback;
    }
    
    triggerCallback(event, data) {
        if (this.callbacks[event]) {
            this.callbacks[event](data);
        }
    }
}
```

### 10.5 优化中文体验的特别配置

#### 10.5.1 中文语音识别优化
- 关键词强化: 为特定领域添加自定义词汇表
- 方言支持: 配置识别不同中文方言的设置
- 上下文相关修正: 使用OpenAI API对ASR结果进行上下文修正

#### 10.5.2 中文语音合成调优
- 语速调整: 根据中文语音特点微调语速
- 停顿优化: 正确在句子之间添加自然停顿
- 声调平滑: 确保多音字发音正确

#### 10.5.3 针对短对话优化
- 缓存常见问答
- 简化历史记录管理
- 降低最大token限制
- 使用系统提示引导简短回复

---

此设计文档提供了实现一个类似于"RealtimeVoiceChat"的系统的技术规范和架构指南，重点关注实时性、可扩展性和用户体验。系统的核心特色是基于WebSocket的原始PCM音频传输和流式处理架构，实现了低延迟、高质量的AI语音对话体验。同时，提供了一个适合中文短对话的轻量级云服务实现方案。

# Azure ASR 字幕演示

这是一个使用 Azure 语音服务进行实时语音识别并显示字幕的演示应用。系统采用流式处理架构，能够即时显示语音识别的中间结果和最终结果。

## 功能特点

- 实时语音转文字识别
- 显示中间识别结果作为字幕
- 显示最终识别结果
- 历史记录保存
- 支持重置对话
- 简洁易用的用户界面

## 技术架构

- **前端**: HTML, CSS, JavaScript, Web Audio API
- **后端**: FastAPI, Azure 语音服务 SDK
- **通信**: WebSocket 双向实时通信

## 安装步骤

1. 克隆仓库：

```bash
git clone https://github.com/your-username/azure-asr-subtitle-demo.git
cd azure-asr-subtitle-demo
```

2. 创建并激活虚拟环境：

```bash
python -m venv venv
source venv/bin/activate  # 在 Windows 上使用: venv\Scripts\activate
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. 创建 `.env` 文件并配置 Azure 语音服务凭据：

```
AZURE_SPEECH_KEY=your_azure_speech_key_here
AZURE_SPEECH_REGION=eastasia  # 根据你的区域修改
PORT=8000
HOST=0.0.0.0
DEBUG=false
```

## 获取 Azure 语音服务凭据

1. 在 [Azure 门户](https://portal.azure.com/) 创建一个语音服务资源
2. 资源创建后，在"密钥和终结点"页面获取密钥和区域信息
3. 将这些信息填入 `.env` 文件

## 运行应用

1. 启动服务器：

```bash
python app.py
```

2. 打开浏览器访问：`http://localhost:8000`

3. 点击"开始录音"按钮，允许麦克风访问，开始语音识别

## 使用说明

- **开始录音**：点击开始按钮，允许麦克风访问
- **停止录音**：点击停止按钮结束录音
- **重置**：点击重置按钮清除当前状态和历史记录

## 已知问题

- 在某些浏览器中，Web Audio API 可能需要 HTTPS 连接才能访问麦克风
- 识别质量取决于网络连接质量和 Azure 语音服务的可用性

## 许可

MIT
