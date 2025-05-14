/**
 * WebSocket处理模块
 */

window.WebSocketHandler = {
    socket: null,
    isAIResponding: false,

    // 获取当前WebSocket连接
    getSocket() {
        return this.socket;
    },

    // 初始化WebSocket连接
    initializeWebSocket(updateStatus, startBtn) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        if (this.socket && this.socket.readyState !== WebSocket.CLOSED) {
            this.socket.close();
        }
        
        this.socket = new WebSocket(wsUrl);
        
        this.socket.onopen = () => {
            console.log('WebSocket连接成功');
            updateStatus('idle', '已连接，准备就绪');
            startBtn.disabled = false;
            window.AudioProcessor.initAudioContext();
        };
        
        this.socket.onmessage = (event) => this._handleSocketMessage(event, updateStatus);
        
        this.socket.onclose = () => {
            console.log('WebSocket连接关闭');
            updateStatus('error', '连接已断开');
            startBtn.disabled = true;
            
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.initializeWebSocket(updateStatus, startBtn);
            }, 5000);
        };
        
        this.socket.onerror = (error) => {
            console.error('WebSocket错误:', error);
            updateStatus('error', '连接错误');
        };
    },

    // 处理所有WebSocket消息
    _handleSocketMessage(event, updateStatus) {
        try {
            if (typeof event.data === 'string') {
                const data = JSON.parse(event.data);
                console.log('收到WebSocket消息:', data.type, data);
                this.handleMessage(data, updateStatus);
            } else if (event.data instanceof Blob) {
                console.log('收到二进制数据:', event.data.size, '字节');
                window.AudioProcessor.handleBinaryAudioData(event.data);
            }
        } catch (e) {
            console.error('处理消息错误:', e);
        }
    },

    // 处理WebSocket消息
    handleMessage(data, updateStatus) {
        const messages = document.getElementById('messages');
        
        switch (data.type) {
            case 'partial_transcript':
                this._handleTranscript(data, messages, true);
                break;
            
            case 'final_transcript':
                this._handleTranscript(data, messages, false);
                break;
            
            case 'llm_status':
                this._handleLLMStatus(data, updateStatus, messages);
                break;
            
            case 'llm_response':
                this._handleLLMResponse(data, updateStatus, messages);
                break;
                
            case 'audio_start':
                console.log('开始播放音频, 格式:', data.format);
                break;
                
            case 'audio_end':
                console.log('音频播放结束');
                break;
            
            case 'tts_sentence_start':
            case 'tts_sentence_end':
                console.log(`收到消息: ${data.type}`, data);
                break;
                
            case 'stop_audio':
            case 'server_interrupt':
            case 'interrupt_acknowledged':
            case 'stop_acknowledged':
                console.log(`收到消息: ${data.type}`, data);
                window.AudioProcessor.stopAudioPlayback();
                break;
                
            case 'error':
                console.error(`收到错误消息:`, data);
                if (data.type === 'error') {
                    updateStatus('error', data.message || '发生错误');
                }
                break;
                
            default:
                console.log(`未处理的消息类型: ${data.type}`, data);
                break;
        }
    },

    // 处理转录结果（部分或最终）
    _handleTranscript(data, messages, isPartial) {
        if (!data.content.trim()) return;
        
        const bubbleId = isPartial ? 'current-user-bubble' : '';
        let userBubble = document.getElementById('current-user-bubble');
        
        if (userBubble) {
            userBubble.textContent = data.content;
            if (!isPartial) userBubble.id = '';
        } else {
            const message = document.createElement('div');
            message.className = 'message user-message';
            message.id = bubbleId;
            message.textContent = data.content;
            
            messages.appendChild(message);
            messages.scrollTop = messages.scrollHeight;
        }
    },

    // 处理LLM状态
    _handleLLMStatus(data, updateStatus, messages) {
        if (data.status === 'processing') {
            updateStatus('thinking', 'AI思考中...');
            this.isAIResponding = true;
            
            const existingContainer = document.getElementById('ai-message-container');
            if (existingContainer) existingContainer.remove();
            
            const aiMessage = document.createElement('div');
            aiMessage.id = 'ai-message-container';
            aiMessage.className = 'message ai-message';
            
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.innerHTML = '<span></span><span></span><span></span>';
            
            aiMessage.appendChild(typingIndicator);
            messages.appendChild(aiMessage);
            messages.scrollTop = messages.scrollHeight;
        }
    },

    // 处理LLM响应
    _handleLLMResponse(data, updateStatus, messages) {
        const aiMessage = document.getElementById('ai-message-container');
        
        if (aiMessage) {
            aiMessage.innerHTML = '';
            aiMessage.textContent = data.content;
            
            if (data.is_complete) {
                aiMessage.id = '';
                updateStatus('idle', '已完成');
                this.isAIResponding = false;
            } else {
                const typingIndicator = document.createElement('div');
                typingIndicator.className = 'typing-indicator';
                typingIndicator.innerHTML = '<span></span><span></span><span></span>';
                aiMessage.appendChild(typingIndicator);
            }
            
            messages.scrollTop = messages.scrollHeight;
        } else if (data.is_complete) {
            const message = document.createElement('div');
            message.className = 'message ai-message';
            message.textContent = data.content;
            
            messages.appendChild(message);
            messages.scrollTop = messages.scrollHeight;
            updateStatus('idle', '已完成');
            this.isAIResponding = false;
        }
    },

    // 发送命令
    sendCommand(command, data = {}) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            const message = {
                command,
                ...data
            };
            this.socket.send(JSON.stringify(message));
        }
    },

    // 发送停止并清空队列命令
    sendStopAndClearQueues() {
        this.sendCommand('stop');
        this.sendCommand('clear_queues');
    },

    // 检查用户是否在AI响应时开始说话
    checkVoiceInterruption(audioData) {
        if (this.isAIResponding && window.AudioProcessor.isPlaying()) {
            const threshold = 0.03;
            const audioLevel = this._calculateAudioLevel(audioData);
            
            if (audioLevel > threshold) {
                console.log('检测到用户打断，音频能量:', audioLevel);
                this.sendCommand('interrupt');
            }
        }
    },

    // 计算音频能量级别
    _calculateAudioLevel(audioData) {
        if (!audioData || audioData.length === 0) return 0;
        
        let sum = 0;
        for (let i = 0; i < audioData.length; i++) {
            sum += Math.abs(audioData[i]);
        }
        
        return sum / audioData.length;
    }
}; 