/**
 * WebSocket处理模块
 * 管理与服务器的WebSocket通信
 */

import audioProcessor from './audio-processor.js';

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
            
            // 5秒后尝试重连
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.initializeWebSocket(updateStatus, startButton);
            }, 5000);
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
                this.handleMessage(messageData, updateStatus);
            } else if (event.data instanceof Blob) {
                this.handleReceivedAudioData(event.data);
            }
        } catch (e) {
            console.error('处理消息错误:', e);
        }
    },

    /**
     * 处理接收到的音频数据
     * @param {Blob} audioBlob - 接收到的音频数据Blob
     */
    async handleReceivedAudioData(audioBlob) {
        try {
            const arrayBuffer = await audioBlob.arrayBuffer();
            
            // 检查数据大小
            if (arrayBuffer.byteLength <= 0) {
                console.warn('收到的音频数据为空，无法处理');
                return;
            }
            
            // 检查是否有头部信息
            if (arrayBuffer.byteLength >= 12) {
                // 带头部的格式: [4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
                const headerView = new DataView(arrayBuffer, 0, 12);
                
                // 提取PCM音频数据，从12字节开始
                let audioData = arrayBuffer.slice(12);
                
                // 确保音频数据的大小是偶数字节（16位PCM需要）
                if (audioData.byteLength % 2 !== 0) {
                    audioData = audioData.slice(0, audioData.byteLength - (audioData.byteLength % 2));
                }
                
                // 如果有有效数据，则发送到音频处理器播放
                if (audioData.byteLength > 0) {
                    audioProcessor.playAudio(audioData);
                }
            } else {
                // 直接的PCM格式（没有头部信息）
                let audioData = arrayBuffer;
                
                // 确保音频数据的大小是偶数字节
                if (audioData.byteLength % 2 !== 0) {
                    console.warn('直接PCM音频数据大小不正确（非偶数字节）:', audioData.byteLength, '字节，将进行调整');
                    audioData = audioData.slice(0, audioData.byteLength - (audioData.byteLength % 2));
                }
                
                // 播放音频
                if (audioData.byteLength > 0) {
                    audioProcessor.playAudio(audioData);
                } else {
                    console.warn('处理后直接PCM音频数据为空，跳过播放');
                }
            }
        } catch (e) {
            console.error('处理接收的音频数据错误:', e);
        }
    },

    // 处理WebSocket消息
    handleMessage(messageData, updateStatus) {
        const messagesContainer = document.getElementById('messages');
        
        switch (messageData.type) {
            case 'partial_transcript':
                this._handleTranscript(messageData, messagesContainer, true);
                break;
            
            case 'final_transcript':
                this._handleTranscript(messageData, messagesContainer, false);
                break;
            
            case 'llm_status':
                this._handleLLMStatus(messageData, updateStatus, messagesContainer);
                break;
            
            case 'llm_response':
                this._handleLLMResponse(messageData, updateStatus, messagesContainer);
                break;
                
            case 'audio_start':
                console.log('开始播放音频, 格式:', messageData.format);
                break;
                
            case 'audio_end':
                console.log('音频播放结束');
                break;
            
            case 'tts_start':
                console.log('开始播放TTS音频, 格式:', messageData.format);
                break;
            
            case 'tts_end':
                console.log('TTS音频播放结束');
                break;
            
            case 'tts_stop':
                console.log('停止TTS音频播放');
                if (audioProcessor) {
                    audioProcessor.stopAudioPlayback();
                }
                break;
            
            case 'server_interrupt':
            case 'interrupt_acknowledged':
            case 'stop_acknowledged':
                console.log(`收到消息: ${messageData.type}`, messageData);
                audioProcessor.stopAudioPlayback();
                break;
                
            case 'error':
                console.error(`收到错误消息:`, messageData);
                if (messageData.type === 'error') {
                    updateStatus('error', messageData.message || '发生错误');
                }
                break;
                
            default:
                console.log(`未处理的消息类型: ${messageData.type}`, messageData);
                break;
        }
    },

    // 处理转录结果（部分或最终）
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

    // 处理LLM状态
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

    // 处理LLM响应
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
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
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
     * @param {Int16Array} pcmData - PCM音频数据
     * @param {boolean} isFirstBlock - 是否是第一个音频块
     * @returns {boolean} 发送是否成功
     */
    sendAudioData(pcmData, isFirstBlock = false) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
        
        try {
            // 创建带头部的数据缓冲区 [4字节时间戳][4字节状态标志]
            const headerSize = 8;
            const combinedBuffer = new ArrayBuffer(headerSize + pcmData.byteLength);
            const headerView = new DataView(combinedBuffer, 0, headerSize);
            
            // 设置时间戳 (毫秒)
            headerView.setUint32(0, Date.now(), true);
            
            // 设置状态标志
            let statusFlags = 0;
            
            // 计算音频能量值
            if (pcmData instanceof Float32Array) {
                const audioEnergy = Math.min(255, Math.floor(this._calculateAudioLevel(pcmData) * 1000));
                statusFlags |= audioEnergy & 0xFF;
                
                // 检测静音
                if (pcmData.every(sample => Math.abs(sample) < 0.01)) {
                    statusFlags |= (1 << 8);
                }
            } else {
                // 对于Int16Array数据，设置默认音量
                statusFlags |= 128;  // 中等音量
            }
            
            // 设置首个音频块标志
            if (isFirstBlock) {
                statusFlags |= (1 << 9);
            }
            
            headerView.setUint32(4, statusFlags, true);
            
            // 将PCM数据复制到组合缓冲区
            new Uint8Array(combinedBuffer, headerSize).set(
                new Uint8Array(pcmData.buffer || pcmData)
            );
            
            // 发送数据
            this.socket.send(combinedBuffer);
            return true;
        } catch (e) {
            console.error('发送音频数据错误:', e);
            return false;
        }
    },

    /**
     * 检查用户是否在AI响应时开始说话，实现打断功能
     * @param {Float32Array} audioData - 音频数据
     */
    checkVoiceInterruption(audioData) {
        if (this.isAIResponding && audioProcessor.isPlaying()) {
            const volumeThreshold = 0.03;
            const audioLevel = this._calculateAudioLevel(audioData);
            
            if (audioLevel > volumeThreshold) {
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
        if (!audioData || audioData.length === 0) return 0;
        
        let totalAmplitude = 0;
        for (let i = 0; i < audioData.length; i++) {
            totalAmplitude += Math.abs(audioData[i]);
        }
        
        return totalAmplitude / audioData.length;
    }
};

// 使用ES模块导出
export default websocketHandler; 