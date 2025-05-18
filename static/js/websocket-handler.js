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
        const messagesContainer = document.getElementById('messages');
        
        switch (messageData.type) {
            case MESSAGE_TYPES.PARTIAL_TRANSCRIPT:
                // 处理部分语音识别结果
                this._handleTranscript(messageData, messagesContainer, true);
                break;
            
            case MESSAGE_TYPES.FINAL_TRANSCRIPT:
                // 处理最终语音识别结果
                this._handleTranscript(messageData, messagesContainer, false);
                break;
            
            case MESSAGE_TYPES.LLM_STATUS:
                // 处理LLM处理状态
                this._handleLLMStatus(messageData, updateStatus, messagesContainer);
                break;
            
            case MESSAGE_TYPES.LLM_RESPONSE:
                // 处理LLM响应内容
                this._handleLLMResponse(messageData, updateStatus, messagesContainer);
                break;
                
            case MESSAGE_TYPES.AUDIO_START:
                // 开始播放音频
                console.log('开始播放音频, 格式:', messageData.format);
                break;
                
            case MESSAGE_TYPES.AUDIO_END:
                // 音频播放结束
                console.log('音频播放结束');
                break;
            
            case MESSAGE_TYPES.TTS_START:
                // 开始TTS合成
                console.log('开始播放TTS音频, 格式:', messageData.format);
                break;
            
            case MESSAGE_TYPES.TTS_END:
                // TTS合成结束
                console.log('TTS音频播放结束');
                break;
            
            case MESSAGE_TYPES.TTS_STOP:
                // 停止TTS播放
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
     * 处理转录结果
     * 支持部分转录和最终转录两种模式
     * @private
     * @param {Object} messageData - 消息数据
     * @param {HTMLElement} messagesContainer - 消息容器
     * @param {boolean} isPartial - 是否为部分转录
     */
    _handleTranscript(messageData, messagesContainer, isPartial) {
        if (!messageData.content.trim()) return;
        
        const bubbleId = isPartial ? 'current-user-bubble' : '';
        let userBubble = document.getElementById('current-user-bubble');
        
        if (userBubble) {
            // 更新现有气泡内容
            userBubble.textContent = messageData.content;
            if (!isPartial) userBubble.id = '';
        } else {
            // 创建新的消息气泡
            const messageElement = document.createElement('div');
            messageElement.className = 'message user-message';
            messageElement.id = bubbleId;
            messageElement.textContent = messageData.content;
            
            messagesContainer.appendChild(messageElement);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    },

    /**
     * 处理LLM状态
     * 显示AI思考状态和输入指示器
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLElement} messagesContainer - 消息容器
     */
    _handleLLMStatus(messageData, updateStatus, messagesContainer) {
        if (messageData.status === 'processing') {
            updateStatus('thinking', 'AI思考中...');
            this.isAIResponding = true;
            
            // 移除现有的AI消息容器
            const existingContainer = document.getElementById('ai-message-container');
            if (existingContainer) existingContainer.remove();
            
            // 创建新的AI消息容器
            const aiMessageElement = document.createElement('div');
            aiMessageElement.id = 'ai-message-container';
            aiMessageElement.className = 'message ai-message';
            
            // 添加输入指示器
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.innerHTML = '<span></span><span></span><span></span>';
            
            aiMessageElement.appendChild(typingIndicator);
            messagesContainer.appendChild(aiMessageElement);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    },

    /**
     * 处理LLM响应
     * 显示AI的响应内容，支持流式响应
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLElement} messagesContainer - 消息容器
     */
    _handleLLMResponse(messageData, updateStatus, messagesContainer) {
        const aiMessageElement = document.getElementById('ai-message-container');
        
        if (aiMessageElement) {
            // 更新现有消息内容
            aiMessageElement.innerHTML = '';
            aiMessageElement.textContent = messageData.content;
            
            if (messageData.is_complete) {
                // 完成响应，移除容器ID
                aiMessageElement.id = '';
                updateStatus('idle', '已完成');
                this.isAIResponding = false;
            } else {
                // 继续显示输入指示器
                const typingIndicator = document.createElement('div');
                typingIndicator.className = 'typing-indicator';
                typingIndicator.innerHTML = '<span></span><span></span><span></span>';
                aiMessageElement.appendChild(typingIndicator);
            }
            
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        } else if (messageData.is_complete) {
            // 创建新的消息元素
            const messageElement = document.createElement('div');
            messageElement.className = 'message ai-message';
            messageElement.textContent = messageData.content;
            
            messagesContainer.appendChild(messageElement);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
            updateStatus('idle', '已完成');
            this.isAIResponding = false;
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
    }
};

// 使用ES模块导出
export default websocketHandler; 