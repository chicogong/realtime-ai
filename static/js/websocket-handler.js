/**
 * WebSocket处理模块
 * 管理与服务器的WebSocket通信，处理音频数据的发送和接收，
 * 以及处理各种类型的消息（转录、LLM响应、音频控制等）
 * @module websocket-handler
 */

import audioProcessor from './audio-processor.js';

// WebSocket配置常量
const WS_CONFIG = {
    RECONNECT_DELAY: 5000,        // 重连延迟时间（毫秒）
    AUDIO_HEADER_SIZE: 8,         // 音频数据头部大小（字节）
    VOLUME_THRESHOLD: 0.03,       // 音量检测阈值，用于打断检测
    SILENCE_THRESHOLD: 0.01,      // 静音检测阈值
    DEFAULT_VOLUME: 128           // 默认音量值（中等音量）
};

// 消息类型常量
const MESSAGE_TYPES = {
    PARTIAL_TRANSCRIPT: 'partial_transcript',     // 部分语音识别结果
    FINAL_TRANSCRIPT: 'final_transcript',         // 最终语音识别结果
    LLM_STATUS: 'llm_status',                     // LLM处理状态
    LLM_RESPONSE: 'llm_response',                 // LLM响应内容
    AUDIO_START: 'audio_start',                   // 开始播放音频
    AUDIO_END: 'audio_end',                       // 音频播放结束
    TTS_START: 'tts_start',                       // 开始TTS合成
    TTS_END: 'tts_end',                           // TTS合成结束
    TTS_STOP: 'tts_stop',                         // 停止TTS播放
    SUBTITLE: 'subtitle',                         // 字幕信息
    SERVER_INTERRUPT: 'server_interrupt',         // 服务器中断信号
    INTERRUPT_ACKNOWLEDGED: 'interrupt_acknowledged', // 中断确认
    STOP_ACKNOWLEDGED: 'stop_acknowledged',       // 停止确认
    ERROR: 'error'                                // 错误信息
};

// 状态标志位
const STATUS_FLAGS = {
    SILENCE: 1 << 8,      // 静音标志位（第9位）
    FIRST_BLOCK: 1 << 9   // 首个音频块标志位（第10位）
};

/**
 * WebSocket处理器对象
 * 负责处理与服务器的WebSocket通信，包括：
 * 1. 音频数据的发送和接收
 * 2. 语音识别结果的处理
 * 3. LLM响应的处理
 * 4. 音频播放控制
 * @type {Object}
 */
const websocketHandler = {
    socket: null,          // WebSocket连接实例
    isAIResponding: false, // AI是否正在响应

    /**
     * 获取当前WebSocket连接
     * @returns {WebSocket|null} 当前WebSocket连接
     */
    getSocket() {
        return this.socket;
    },

    /**
     * 初始化WebSocket连接
     * 建立与服务器的WebSocket连接，并设置各种事件处理器
     * @param {Function} updateStatus - 状态更新函数，用于更新UI状态
     * @param {HTMLButtonElement} startButton - 开始按钮元素，用于控制按钮状态
     */
    initializeWebSocket(updateStatus, startButton) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        // 关闭现有连接
        if (this.socket && this.socket.readyState !== WebSocket.CLOSED) {
            this.socket.close();
        }
        
        // 创建新连接
        this.socket = new WebSocket(wsUrl);
        
        // 连接成功处理
        this.socket.onopen = () => {
            console.log('WebSocket连接成功');
            updateStatus('idle', '已连接，准备就绪');
            startButton.disabled = false;
            audioProcessor.initAudioContext();
        };
        
        // 消息处理
        this.socket.onmessage = (event) => this._handleSocketMessage(event, updateStatus);
        
        // 连接关闭处理
        this.socket.onclose = () => {
            console.log('WebSocket连接关闭');
            updateStatus('error', '连接已断开');
            startButton.disabled = true;
            
            // 延迟重连
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.initializeWebSocket(updateStatus, startButton);
            }, WS_CONFIG.RECONNECT_DELAY);
        };
        
        // 错误处理
        this.socket.onerror = (error) => {
            console.error('WebSocket错误:', error);
            updateStatus('error', '连接错误');
        };
    },

    /**
     * 处理所有WebSocket消息
     * 根据消息类型分发到不同的处理函数
     * @private
     * @param {MessageEvent} event - WebSocket消息事件
     * @param {Function} updateStatus - 状态更新函数
     */
    _handleSocketMessage(event, updateStatus) {
        try {
            if (typeof event.data === 'string') {
                // 处理JSON格式的消息
                const messageData = JSON.parse(event.data);
                this._handleMessage(messageData, updateStatus);
            } else if (event.data instanceof Blob) {
                // 处理二进制音频数据
                this._handleReceivedAudioData(event.data);
            }
        } catch (error) {
            console.error('处理消息错误:', error);
        }
    },

    /**
     * 处理接收到的音频数据
     * 支持两种格式：
     * 1. 带头部的格式：[4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
     * 2. 直接的PCM格式
     * @private
     * @param {Blob} audioBlob - 接收到的音频数据Blob
     */
    async _handleReceivedAudioData(audioBlob) {
        try {
            const arrayBuffer = await audioBlob.arrayBuffer();
            
            if (arrayBuffer.byteLength <= 0) {
                console.warn('收到的音频数据为空，无法处理');
                return;
            }
            
            let audioData;
            
            // 处理带头部的音频数据
            if (arrayBuffer.byteLength >= 12) {
                // 带头部的格式: [4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
                audioData = arrayBuffer.slice(12);
            } else {
                // 直接的PCM格式（没有头部信息）
                audioData = arrayBuffer;
            }
            
            // 确保音频数据大小正确（16位PCM需要偶数字节）
            if (audioData.byteLength % 2 !== 0) {
                audioData = audioData.slice(0, audioData.byteLength - 1);
            }
            
            // 播放有效音频数据
            if (audioData.byteLength > 0) {
                audioProcessor.playAudio(audioData);
            }
        } catch (error) {
            console.error('处理接收的音频数据错误:', error);
        }
    },

    /**
     * 处理WebSocket消息
     * 根据消息类型分发到不同的处理函数
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     */
    _handleMessage(messageData, updateStatus) {
        const chatList = document.querySelector('.chat-list');
        
        switch (messageData.type) {
            case 'status':
                // 处理会话状态信息
                console.log(`会话状态: ${messageData.status}, 会话ID: ${messageData.session_id}`);
                
                // 根据状态更新UI
                if (messageData.status === 'listening') {
                    this._updateStatusBox('listening', '正在听取...');
                    updateStatus('listening', '正在听取...');
                } else if (messageData.status === 'thinking') {
                    this._updateStatusBox('thinking', 'AI思考中...');
                    updateStatus('thinking', 'AI思考中...');
                } else if (messageData.status === 'idle') {
                    this._updateStatusBox('idle', '已完成');
                    updateStatus('idle', '已完成');
                } else if (messageData.status === 'error') {
                    const errorMsg = messageData.message || '发生错误';
                    this._updateStatusBox('error', errorMsg);
                    updateStatus('error', errorMsg);
                }
                break;
            
            case MESSAGE_TYPES.PARTIAL_TRANSCRIPT:
                // 处理部分语音识别结果
                this._updateStatusBox('listening', '正在听取...');
                this._handleTranscript(messageData, chatList, true);
                break;
            
            case MESSAGE_TYPES.FINAL_TRANSCRIPT:
                // 处理最终语音识别结果
                this._handleTranscript(messageData, chatList, false);
                break;
            
            case MESSAGE_TYPES.LLM_STATUS:
                // 处理LLM处理状态
                this._updateStatusBox('thinking', 'AI思考中...');
                this._handleLLMStatus(messageData, updateStatus, chatList);
                break;
            
            case MESSAGE_TYPES.LLM_RESPONSE:
                // 处理LLM响应内容
                if (messageData.is_complete) {
                    this._updateStatusBox('idle', '已完成');
                }
                this._handleLLMResponse(messageData, updateStatus, chatList);
                break;
                
            case MESSAGE_TYPES.AUDIO_START:
                // 开始播放音频
                this._updateStatusBox('thinking', '正在回复...');
                console.log('开始播放音频, 格式:', messageData.format);
                break;
                
            case MESSAGE_TYPES.AUDIO_END:
                // 音频播放结束
                this._updateStatusBox('idle', '已完成');
                console.log('音频播放结束');
                break;
            
            case MESSAGE_TYPES.TTS_START:
                // 开始TTS合成
                this._updateStatusBox('thinking', '正在生成语音...');
                console.log('开始播放TTS音频, 格式:', messageData.format);
                break;
            
            case MESSAGE_TYPES.TTS_END:
                // TTS合成结束
                this._updateStatusBox('idle', '已完成');
                console.log('TTS音频播放结束');
                break;
            
            case MESSAGE_TYPES.TTS_STOP:
                // 停止TTS播放
                this._updateStatusBox('idle', '已停止');
                console.log('停止TTS音频播放');
                audioProcessor.stopAudioPlayback();
                break;
                
            case MESSAGE_TYPES.SUBTITLE:
                // 处理字幕信息
                console.log(`收到字幕: ${messageData.content}, 是否完成: ${messageData.is_complete}`);
                break;
            
            case MESSAGE_TYPES.SERVER_INTERRUPT:
            case MESSAGE_TYPES.INTERRUPT_ACKNOWLEDGED:
            case MESSAGE_TYPES.STOP_ACKNOWLEDGED:
                // 处理中断和停止确认
                console.log(`收到消息: ${messageData.type}`, messageData);
                audioProcessor.stopAudioPlayback();
                break;
                
            case MESSAGE_TYPES.ERROR:
                // 处理错误信息
                console.error('收到错误消息:', messageData);
                updateStatus('error', messageData.message || '发生错误');
                break;
                
            default:
                // 处理未知消息类型
                console.log(`未处理的消息类型: ${messageData.type}`, messageData);
                break;
        }
    },

    /**
     * 渲染消息气泡
     * @param {string} content - 消息内容
     * @param {boolean} isUser - 是否为用户消息
     * @param {boolean} isPartial - 是否为部分转录
     * @param {string} bubbleId - 可选，气泡ID
     * @param {HTMLElement} chatList - 聊天列表元素
     */
    _renderChatBubble(content, isUser, isPartial, bubbleId, chatList) {
        if (!chatList || !content.trim()) return;
        
        // 部分转录时复用气泡
        if (isPartial && bubbleId) {
            const existingBubble = document.getElementById(bubbleId);
            if (existingBubble) {
                const bubbleContent = existingBubble.querySelector('.chat-bubble');
                if (bubbleContent) {
                    bubbleContent.textContent = content;
                    return;
                }
            }
        }
        
        // 创建新气泡
        const chatItem = document.createElement('div');
        chatItem.className = `chat-item ${isUser ? 'user' : 'ai'}`;
        if (bubbleId) chatItem.id = bubbleId;
        
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.textContent = content;
        
        chatItem.appendChild(bubble);
        chatList.appendChild(chatItem);
        
        // 滚动到底部
        chatList.scrollTo({
            top: chatList.scrollHeight,
            behavior: 'smooth'
        });
    },

    /**
     * 处理转录结果
     * 支持部分转录和最终转录两种模式
     * @private
     * @param {Object} messageData - 消息数据
     * @param {HTMLElement} chatList - 聊天列表元素
     * @param {boolean} isPartial - 是否为部分转录
     */
    _handleTranscript(messageData, chatList, isPartial) {
        if (!chatList || !messageData.content.trim()) return;
        
        const bubbleId = isPartial ? 'current-user-bubble' : '';
        
        // 最终转录时，先移除对应的部分转录气泡
        if (!isPartial) {
            const oldBubble = document.getElementById('current-user-bubble');
            if (oldBubble) {
                oldBubble.remove(); // 完全移除旧的部分转录气泡
            }
        }
        
        this._renderChatBubble(messageData.content, true, isPartial, bubbleId, chatList);
    },

    /**
     * 处理LLM状态
     * 显示AI思考状态和输入指示器
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLElement} chatList - 聊天列表元素
     */
    _handleLLMStatus(messageData, updateStatus, chatList) {
        if (!chatList) return;
        
        if (messageData.status === 'processing') {
            updateStatus('thinking', 'AI思考中...');
            this.isAIResponding = true;
            
            // 移除现有的AI消息容器
            const existingContainer = document.getElementById('ai-message-container');
            if (existingContainer) existingContainer.remove();
            
            // 创建新的AI消息容器
            const chatItem = document.createElement('div');
            chatItem.id = 'ai-message-container';
            chatItem.className = 'chat-item ai';
            
            // 创建气泡
            const bubble = document.createElement('div');
            bubble.className = 'chat-bubble';
            
            // 添加输入指示器
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.innerHTML = '<span></span><span></span><span></span>';
            
            bubble.appendChild(typingIndicator);
            chatItem.appendChild(bubble);
            chatList.appendChild(chatItem);
            
            // 滚动到底部
            chatList.scrollTo({
                top: chatList.scrollHeight,
                behavior: 'smooth'
            });
        }
    },

    /**
     * 处理LLM响应
     * 显示AI的响应内容，支持流式响应
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLElement} chatList - 聊天列表元素
     */
    _handleLLMResponse(messageData, updateStatus, chatList) {
        if (!chatList) return;
        
        // 流式响应时复用最后一个AI气泡
        const aiMessageContainer = document.getElementById('ai-message-container');
        
        if (aiMessageContainer) {
            const bubble = aiMessageContainer.querySelector('.chat-bubble');
            if (bubble) {
                // 清除输入指示器
                bubble.innerHTML = '';
                bubble.textContent = messageData.content;
                
                if (messageData.is_complete) {
                    aiMessageContainer.id = '';
                    updateStatus('idle', '已完成');
                    this.isAIResponding = false;
                }
                
                // 滚动到底部
                chatList.scrollTo({
                    top: chatList.scrollHeight,
                    behavior: 'smooth'
                });
            }
        } else {
            // 创建新气泡
            this._renderChatBubble(
                messageData.content,
                false,
                false,
                messageData.is_complete ? '' : 'ai-message-container',
                chatList
            );
            
            if (messageData.is_complete) {
                updateStatus('idle', '已完成');
                this.isAIResponding = false;
            }
        }
    },

    /**
     * 发送命令到服务器
     * @param {string} command - 命令名称
     * @param {Object} commandData - 命令附加数据
     */
    sendCommand(command, commandData = {}) {
        if (this.socket?.readyState === WebSocket.OPEN) {
            const message = {
                command,
                ...commandData
            };
            this.socket.send(JSON.stringify(message));
        }
    },

    /**
     * 发送停止并清空队列命令
     * 用于停止当前处理并清空所有待处理队列
     */
    sendStopAndClearQueues() {
        this.sendCommand('stop');
        this.sendCommand('clear_queues');
    },
    
    /**
     * 发送音频数据到服务器
     * 音频数据格式：[8字节头部][PCM数据]
     * 头部格式：[4字节时间戳][4字节状态标志]
     * 状态标志：[0-7位:音量][8位:静音标志][9位:首块标志]
     * @param {Int16Array|Float32Array} pcmData - PCM音频数据
     * @param {boolean} isFirstBlock - 是否是第一个音频块
     * @returns {boolean} 发送是否成功
     */
    sendAudioData(pcmData, isFirstBlock = false) {
        if (!this.socket?.readyState === WebSocket.OPEN) return false;
        
        try {
            // 创建带头部的数据缓冲区
            const combinedBuffer = new ArrayBuffer(WS_CONFIG.AUDIO_HEADER_SIZE + pcmData.byteLength);
            const headerView = new DataView(combinedBuffer, 0, WS_CONFIG.AUDIO_HEADER_SIZE);
            
            // 设置时间戳（毫秒）
            headerView.setUint32(0, Date.now(), true);
            
            // 设置状态标志
            let statusFlags = 0;
            
            if (pcmData instanceof Float32Array) {
                // 计算音频能量值（0-255）
                const audioEnergy = Math.min(255, Math.floor(this._calculateAudioLevel(pcmData) * 1000));
                statusFlags |= audioEnergy & 0xFF;
                
                // 检测静音
                if (pcmData.every(sample => Math.abs(sample) < WS_CONFIG.SILENCE_THRESHOLD)) {
                    statusFlags |= STATUS_FLAGS.SILENCE;
                }
            } else {
                // 对于Int16Array数据，设置默认音量
                statusFlags |= WS_CONFIG.DEFAULT_VOLUME;
            }
            
            // 设置首个音频块标志
            if (isFirstBlock) {
                statusFlags |= STATUS_FLAGS.FIRST_BLOCK;
            }
            
            headerView.setUint32(4, statusFlags, true);
            
            // 复制PCM数据到缓冲区
            new Uint8Array(combinedBuffer, WS_CONFIG.AUDIO_HEADER_SIZE).set(
                new Uint8Array(pcmData.buffer || pcmData)
            );
            
            this.socket.send(combinedBuffer);
            return true;
        } catch (error) {
            console.error('发送音频数据错误:', error);
            return false;
        }
    },

    /**
     * 检查用户是否在AI响应时开始说话
     * 实现打断功能，当检测到用户说话时发送中断命令
     * @param {Float32Array} audioData - 音频数据
     */
    checkVoiceInterruption(audioData) {
        if (this.isAIResponding && audioProcessor.isPlaying()) {
            const audioLevel = this._calculateAudioLevel(audioData);
            
            if (audioLevel > WS_CONFIG.VOLUME_THRESHOLD) {
                console.log('检测到用户打断，音频能量:', audioLevel);
                this.sendCommand('interrupt');
            }
        }
    },

    /**
     * 计算音频能量级别
     * 计算音频数据的平均振幅，用于音量检测
     * @private
     * @param {Float32Array} audioData - 音频数据
     * @returns {number} 音频能量级别 (0-1)
     */
    _calculateAudioLevel(audioData) {
        if (!audioData?.length) return 0;
        
        let totalAmplitude = 0;
        for (let i = 0; i < audioData.length; i++) {
            totalAmplitude += Math.abs(audioData[i]);
        }
        
        return totalAmplitude / audioData.length;
    },

    /**
     * 更新状态框
     * @private
     * @param {string} status - 状态类型（listening/thinking/idle/error）
     * @param {string} message - 状态消息
     */
    _updateStatusBox(status, message) {
        const statusBox = document.getElementById('status-box');
        const statusIcon = document.getElementById('status-icon');
        const statusMessage = document.getElementById('status-message');
        
        if (!statusBox || !statusIcon || !statusMessage) return;
        
        // 移除所有状态类
        statusIcon.classList.remove('listening', 'thinking', 'error');
        
        // 添加当前状态类
        if (['listening', 'thinking', 'error'].includes(status)) {
            statusIcon.classList.add(status);
        }
        
        // 更新消息文本
        statusMessage.textContent = message;
        
        // 如果是idle状态，可以把透明度降低但不需要完全隐藏
        if (status === 'idle') {
            statusBox.classList.add('hidden');
        } else {
            statusBox.classList.remove('hidden');
        }
    }
};

// 使用ES模块导出
export default websocketHandler; 