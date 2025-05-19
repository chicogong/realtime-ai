# Realtime AI 通信协议文档

## 1. 概述

本文档描述了Realtime AI应用程序中前端与后端之间的WebSocket通信协议。通过WebSocket实现实时语音交互、语音识别、语言模型响应和语音合成。

## 2. 连接建立

### 前端连接
前端通过以下URL建立WebSocket连接：
```javascript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/ws`;
```

### 连接状态
连接建立后，后端会创建一个新的会话，并分配一个唯一的`session_id`。

## 3. 前端发送消息类型

### 3.1 音频数据
前端发送的音频数据包含以下结构：
```
[4字节时间戳][4字节状态标志][PCM数据]
```

- **时间戳**：当前的毫秒级时间戳（32位无符号整数，小端序）
- **状态标志**：包含音频能量和控制信息的32位整数（小端序）
  - 低8位：音频能量值(0-255)
  - 第9位（1<<8）：静音标志位
  - 第10位（1<<9）：首个音频块标志位

### 3.2 控制命令
前端通过JSON消息发送以下控制命令：

#### 开始命令
```json
{
  "command": "start"
}
```

#### 停止命令
```json
{
  "command": "stop"
}
```

#### 重置命令
```json
{
  "command": "reset"
}
```

#### 中断命令
```json
{
  "command": "interrupt"
}
```

#### 清空队列命令
```json
{
  "command": "clear_queues"
}
```

## 4. 后端发送消息类型

### 4.1 语音识别结果

#### 部分识别结果
```json
{
  "type": "partial_transcript",
  "content": "用户语音的部分识别结果",
  "session_id": "会话ID"
}
```

#### 最终识别结果
```json
{
  "type": "final_transcript",
  "content": "用户语音的最终识别结果",
  "session_id": "会话ID"
}
```

### 4.2 语言模型状态和响应

#### 语言模型处理状态
```json
{
  "type": "llm_status",
  "status": "processing",
  "session_id": "会话ID"
}
```

#### 语言模型响应（流式）
```json
{
  "type": "llm_response",
  "content": "AI响应内容",
  "is_complete": false,
  "session_id": "会话ID"
}
```

#### 语言模型响应（完成）
```json
{
  "type": "llm_response",
  "content": "完整的AI响应内容",
  "is_complete": true,
  "session_id": "会话ID"
}
```

### 4.3 字幕消息

#### 字幕流式更新
```json
{
  "type": "subtitle",
  "content": "当前句子内容",
  "is_complete": false,
  "session_id": "会话ID"
}
```

#### 字幕完整句子
```json
{
  "type": "subtitle",
  "content": "完整句子",
  "is_complete": true,
  "session_id": "会话ID"
}
```

### 4.4 语音合成控制

#### 开始播放TTS音频
```json
{
  "type": "tts_start",
  "format": "pcm",
  "session_id": "会话ID"
}
```

#### TTS音频结束
```json
{
  "type": "tts_end",
  "session_id": "会话ID"
}
```

#### 停止TTS音频
```json
{
  "type": "tts_stop",
  "session_id": "会话ID"
}
```

### 4.5 控制响应消息

#### 中断确认
```json
{
  "type": "interrupt_acknowledged",
  "session_id": "会话ID"
}
```

#### 停止确认
```json
{
  "type": "stop_acknowledged",
  "message": "所有处理已停止",
  "queues_cleared": true,
  "session_id": "会话ID"
}
```

### 4.6 服务器中断通知
```json
{
  "type": "server_interrupt",
  "session_id": "会话ID"
}
```

### 4.7 错误消息
```json
{
  "type": "error",
  "message": "错误描述",
  "session_id": "会话ID"
}
```

## 5. 音频数据格式

### 发送到服务器
- 格式：PCM
- 采样率：16000Hz
- 通道数：1（单声道）
- 每样本位数：16位

### 从服务器接收
- 格式：PCM
- 采样率：取决于客户端设备（通常为44100或48000Hz）
- 通道数：1（单声道）
- 每样本位数：16位


## 7. 通信流程

### 主要流程
1. 前端建立WebSocket连接
2. 后端创建会话ID并初始化服务
3. 用户点击"开始"按钮，前端发送`start`命令
4. 前端开始向后端发送音频数据
5. 后端进行语音识别并返回`partial_transcript`和`final_transcript`消息
6. 当有完整识别结果时，后端启动语言模型处理
7. 后端发送`llm_status`消息表示处理开始
8. 语言模型生成内容时，后端发送`llm_response`和`subtitle`消息
9. 当生成完整句子时，后端将句子发送到TTS处理队列
10. TTS开始时，后端发送`tts_start`消息，然后发送音频数据
11. TTS完成时，后端发送`tts_end`消息

### 中断流程
1. 当用户在AI响应时开始说话，前端检测到语音能量超过阈值
2. 前端发送`interrupt`命令
3. 后端发送`interrupt_acknowledged`确认，停止当前处理，清理队列
4. 后端发送`tts_stop`消息停止当前音频播放
