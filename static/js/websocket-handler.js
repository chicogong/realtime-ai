/**
 * WebSocket处理模块
 */

class WebSocketHandler {
    constructor() {
        this.socket = null;
        this.isAIResponding = false;
    }

    // 获取当前WebSocket连接
    getSocket() {
        return this.socket;
    }

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
            
            // 5秒后尝试重连
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.initializeWebSocket(updateStatus, startBtn);
            }, 5000);
        };
        
        this.socket.onerror = (error) => {
            console.error('WebSocket错误:', error);
            updateStatus('error', '连接错误');
        };
    }

    // 处理所有WebSocket消息
    _handleSocketMessage(event, updateStatus) {
        try {
            if (typeof event.data === 'string') {
                // 处理JSON消息
                const data = JSON.parse(event.data);
                this.handleMessage(data, updateStatus);
            } else if (event.data instanceof Blob) {
                // 处理二进制音频数据
                window.AudioProcessor.handleBinaryAudioData(event.data);
            }
        } catch (e) {
            console.error('处理消息错误:', e);
        }
    }

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
                console.log(`收到消息: ${data.type}`, data);
                if (data.type === 'error') {
                    updateStatus('error', data.message || '发生错误');
                }
                break;
        }
    }

    // 处理转录结果（部分或最终）
    _handleTranscript(data, messages, isPartial) {
        if (!data.content.trim()) return;
        
        const bubbleId = isPartial ? 'current-user-bubble' : '';
        let userBubble = document.getElementById('current-user-bubble');
        
        if (userBubble) {
            // 更新现有气泡
            userBubble.textContent = data.content;
            if (!isPartial) userBubble.id = '';
        } else {
            // 创建新的用户消息
            const message = document.createElement('div');
            message.className = 'message user-message';
            message.id = bubbleId;
            message.textContent = data.content;
            
            messages.appendChild(message);
            messages.scrollTop = messages.scrollHeight;
        }
    }

    // 处理LLM状态
    _handleLLMStatus(data, updateStatus, messages) {
        if (data.status === 'processing') {
            updateStatus('thinking', 'AI思考中...');
            this.isAIResponding = true;
            
            // 移除现有的AI消息容器
            const existingContainer = document.getElementById('ai-message-container');
            if (existingContainer) existingContainer.remove();
            
            // 创建新的AI消息容器
            const aiMessage = document.createElement('div');
            aiMessage.id = 'ai-message-container';
            aiMessage.className = 'message ai-message';
            
            // 添加打字指示器
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.innerHTML = '<span></span><span></span><span></span>';
            
            aiMessage.appendChild(typingIndicator);
            messages.appendChild(aiMessage);
            messages.scrollTop = messages.scrollHeight;
        }
    }

    // 处理LLM响应
    _handleLLMResponse(data, updateStatus, messages) {
        const aiMessage = document.getElementById('ai-message-container');
        
        if (aiMessage) {
            // 清除内容，包括打字指示器
            aiMessage.innerHTML = '';
            
            // 添加新内容
            aiMessage.textContent = data.content;
            
            if (data.is_complete) {
                // 消息完成，移除ID
                aiMessage.id = '';
                updateStatus('idle', '已完成');
                this.isAIResponding = false;
            } else {
                // 继续流式响应，添加打字指示器
                const typingIndicator = document.createElement('div');
                typingIndicator.className = 'typing-indicator';
                typingIndicator.innerHTML = '<span></span><span></span><span></span>';
                aiMessage.appendChild(typingIndicator);
            }
            
            messages.scrollTop = messages.scrollHeight;
        } else if (data.is_complete) {
            // 创建新消息
            const message = document.createElement('div');
            message.className = 'message ai-message';
            message.textContent = data.content;
            
            messages.appendChild(message);
            messages.scrollTop = messages.scrollHeight;
            updateStatus('idle', '已完成');
            this.isAIResponding = false;
        }
    }

    // 发送命令
    sendCommand(type, data = {}) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            console.error('WebSocket未连接，无法发送命令');
            return;
        }
        
        const command = {
            type: type,
            ...data
        };
        
        this.socket.send(JSON.stringify(command));
        console.log(`发送命令: ${type}`);
    }

    // 发送停止并清空队列的命令
    sendStopAndClearQueues() {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            console.error('WebSocket未连接，无法发送命令');
            return;
        }
        
        const command = {
            type: 'stop',
            clear_queues: true,
            force_stop: true
        };
        
        this.socket.send(JSON.stringify(command));
        console.log('发送强制停止并清空队列命令');
        
        // 立即停止本地音频播放
        window.AudioProcessor.stopAudioPlayback();
    }

    // 检查用户语音中断
    checkVoiceInterruption(audioData) {
        if (!this.isAIResponding) return;
        
        // 简化：检测音量超过阈值时中断AI响应
        const volume = this._calculateAudioLevel(audioData);
        const THRESHOLD = 0.1;
        
        if (volume > THRESHOLD) {
            console.log('检测到用户开始说话，停止AI响应');
            this.sendCommand('interrupt');
            this.isAIResponding = false;
        }
    }

    // 计算音频音量级别
    _calculateAudioLevel(audioData) {
        if (!audioData || audioData.length === 0) return 0;
        
        let sum = 0;
        for (let i = 0; i < audioData.length; i++) {
            sum += Math.abs(audioData[i]);
        }
        
        return sum / audioData.length;
    }
}

// 创建并导出全局实例
window.WebSocketHandler = new WebSocketHandler(); 