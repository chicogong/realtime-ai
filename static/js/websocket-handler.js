/**
 * WebSocket处理模块
 * 管理与服务器的WebSocket通信
 * @module websocket-handler
 */

import audioProcessor from './audio-processor.js';

// WebSocket配置常量
const WS_CONFIG = {
    RECONNECT_DELAY: 5000,
    AUDIO_HEADER_SIZE: 8,
    VOLUME_THRESHOLD: 0.03,
    SILENCE_THRESHOLD: 0.01,
    DEFAULT_VOLUME: 128
};

// 消息类型常量
const MESSAGE_TYPES = {
    PARTIAL_TRANSCRIPT: 'partial_transcript',
    FINAL_TRANSCRIPT: 'final_transcript',
    LLM_STATUS: 'llm_status',
    LLM_RESPONSE: 'llm_response',
    AUDIO_START: 'audio_start',
    AUDIO_END: 'audio_end',
    TTS_START: 'tts_start',
    TTS_END: 'tts_end',
    TTS_STOP: 'tts_stop',
    SUBTITLE: 'subtitle',
    SERVER_INTERRUPT: 'server_interrupt',
    INTERRUPT_ACKNOWLEDGED: 'interrupt_acknowledged',
    STOP_ACKNOWLEDGED: 'stop_acknowledged',
    ERROR: 'error'
};

// 状态标志位
const STATUS_FLAGS = {
    SILENCE: 1 << 8,
    FIRST_BLOCK: 1 << 9
};

/**
 * WebSocket处理器对象
 * @type {Object}
 */
const websocketHandler = {
    socket: null,
    isAIResponding: false,

    /**
     * 获取当前WebSocket连接
     * @returns {WebSocket|null} 当前WebSocket连接
     */
    getSocket() {
        return this.socket;
    },

    /**
     * 初始化WebSocket连接
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLButtonElement} startButton - 开始按钮元素
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
     * @private
     * @param {MessageEvent} event - WebSocket消息事件
     * @param {Function} updateStatus - 状态更新函数
     */
    _handleSocketMessage(event, updateStatus) {
        try {
            if (typeof event.data === 'string') {
                const messageData = JSON.parse(event.data);
                this._handleMessage(messageData, updateStatus);
            } else if (event.data instanceof Blob) {
                this._handleReceivedAudioData(event.data);
            }
        } catch (error) {
            console.error('处理消息错误:', error);
        }
    },

    /**
     * 处理接收到的音频数据
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
                audioData = arrayBuffer.slice(12);
            } else {
                audioData = arrayBuffer;
            }
            
            // 确保音频数据大小正确
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
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     */
    _handleMessage(messageData, updateStatus) {
        const messagesContainer = document.getElementById('messages');
        
        switch (messageData.type) {
            case MESSAGE_TYPES.PARTIAL_TRANSCRIPT:
                this._handleTranscript(messageData, messagesContainer, true);
                break;
            
            case MESSAGE_TYPES.FINAL_TRANSCRIPT:
                this._handleTranscript(messageData, messagesContainer, false);
                break;
            
            case MESSAGE_TYPES.LLM_STATUS:
                this._handleLLMStatus(messageData, updateStatus, messagesContainer);
                break;
            
            case MESSAGE_TYPES.LLM_RESPONSE:
                this._handleLLMResponse(messageData, updateStatus, messagesContainer);
                break;
                
            case MESSAGE_TYPES.AUDIO_START:
                console.log('开始播放音频, 格式:', messageData.format);
                break;
                
            case MESSAGE_TYPES.AUDIO_END:
                console.log('音频播放结束');
                break;
            
            case MESSAGE_TYPES.TTS_START:
                console.log('开始播放TTS音频, 格式:', messageData.format);
                break;
            
            case MESSAGE_TYPES.TTS_END:
                console.log('TTS音频播放结束');
                break;
            
            case MESSAGE_TYPES.TTS_STOP:
                console.log('停止TTS音频播放');
                audioProcessor.stopAudioPlayback();
                break;
                
            case MESSAGE_TYPES.SUBTITLE:
                console.log(`收到字幕: ${messageData.content}, 是否完成: ${messageData.is_complete}`);
                break;
            
            case MESSAGE_TYPES.SERVER_INTERRUPT:
            case MESSAGE_TYPES.INTERRUPT_ACKNOWLEDGED:
            case MESSAGE_TYPES.STOP_ACKNOWLEDGED:
                console.log(`收到消息: ${messageData.type}`, messageData);
                audioProcessor.stopAudioPlayback();
                break;
                
            case MESSAGE_TYPES.ERROR:
                console.error('收到错误消息:', messageData);
                updateStatus('error', messageData.message || '发生错误');
                break;
                
            default:
                console.log(`未处理的消息类型: ${messageData.type}`, messageData);
                break;
        }
    },

    /**
     * 处理转录结果
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
            userBubble.textContent = messageData.content;
            if (!isPartial) userBubble.id = '';
        } else {
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
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLElement} messagesContainer - 消息容器
     */
    _handleLLMStatus(messageData, updateStatus, messagesContainer) {
        if (messageData.status === 'processing') {
            updateStatus('thinking', 'AI思考中...');
            this.isAIResponding = true;
            
            const existingContainer = document.getElementById('ai-message-container');
            if (existingContainer) existingContainer.remove();
            
            const aiMessageElement = document.createElement('div');
            aiMessageElement.id = 'ai-message-container';
            aiMessageElement.className = 'message ai-message';
            
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
     * @private
     * @param {Object} messageData - 消息数据
     * @param {Function} updateStatus - 状态更新函数
     * @param {HTMLElement} messagesContainer - 消息容器
     */
    _handleLLMResponse(messageData, updateStatus, messagesContainer) {
        const aiMessageElement = document.getElementById('ai-message-container');
        
        if (aiMessageElement) {
            aiMessageElement.innerHTML = '';
            aiMessageElement.textContent = messageData.content;
            
            if (messageData.is_complete) {
                aiMessageElement.id = '';
                updateStatus('idle', '已完成');
                this.isAIResponding = false;
            } else {
                const typingIndicator = document.createElement('div');
                typingIndicator.className = 'typing-indicator';
                typingIndicator.innerHTML = '<span></span><span></span><span></span>';
                aiMessageElement.appendChild(typingIndicator);
            }
            
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        } else if (messageData.is_complete) {
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
     */
    sendStopAndClearQueues() {
        this.sendCommand('stop');
        this.sendCommand('clear_queues');
    },
    
    /**
     * 发送音频数据到服务器
     * @param {Int16Array|Float32Array} pcmData - PCM音频数据
     * @param {boolean} isFirstBlock - 是否是第一个音频块
     * @returns {boolean} 发送是否成功
     */
    sendAudioData(pcmData, isFirstBlock = false) {
        if (!this.socket?.readyState === WebSocket.OPEN) return false;
        
        try {
            const combinedBuffer = new ArrayBuffer(WS_CONFIG.AUDIO_HEADER_SIZE + pcmData.byteLength);
            const headerView = new DataView(combinedBuffer, 0, WS_CONFIG.AUDIO_HEADER_SIZE);
            
            // 设置时间戳
            headerView.setUint32(0, Date.now(), true);
            
            // 设置状态标志
            let statusFlags = 0;
            
            if (pcmData instanceof Float32Array) {
                const audioEnergy = Math.min(255, Math.floor(this._calculateAudioLevel(pcmData) * 1000));
                statusFlags |= audioEnergy & 0xFF;
                
                if (pcmData.every(sample => Math.abs(sample) < WS_CONFIG.SILENCE_THRESHOLD)) {
                    statusFlags |= STATUS_FLAGS.SILENCE;
                }
            } else {
                statusFlags |= WS_CONFIG.DEFAULT_VOLUME;
            }
            
            if (isFirstBlock) {
                statusFlags |= STATUS_FLAGS.FIRST_BLOCK;
            }
            
            headerView.setUint32(4, statusFlags, true);
            
            // 复制PCM数据
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