/**
 * WebSocket处理模块
 */

// 状态变量
let socket = null;
let isAIResponding = false;

// WebSocket处理器对象
const WebSocketHandler = {
    // 获取当前WebSocket连接
    getSocket() {
        return socket;
    },

    // 初始化WebSocket连接
    initializeWebSocket(updateStatus, startBtn) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        if (socket && socket.readyState !== WebSocket.CLOSED) {
            socket.close();
        }
        
        socket = new WebSocket(wsUrl);
        
        socket.onopen = () => {
            console.log('WebSocket连接成功');
            updateStatus('idle', '已连接，准备就绪');
            startBtn.disabled = false;
            
            // 确保音频上下文已初始化
            window.AudioProcessor.initAudioContext();
        };
        
        socket.onmessage = (event) => {
            try {
                // 处理文本或二进制消息
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
        };
        
        socket.onclose = () => {
            console.log('WebSocket连接关闭');
            updateStatus('error', '连接已断开');
            startBtn.disabled = true;
            
            // 5秒后尝试重连
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.initializeWebSocket(updateStatus, startBtn);
            }, 5000);
        };
        
        socket.onerror = (error) => {
            console.error('WebSocket错误:', error);
            updateStatus('error', '连接错误');
        };
    },

    // 处理WebSocket消息
    handleMessage(data, updateStatus) {
        const messages = document.getElementById('messages');
        
        switch (data.type) {
            case 'partial_transcript':
                this.handlePartialTranscript(data, messages);
                break;
            
            case 'final_transcript':
                this.handleFinalTranscript(data, messages);
                break;
            
            case 'llm_status':
                this.handleLLMStatus(data, updateStatus, messages);
                break;
            
            case 'llm_response':
                this.handleLLMResponse(data, updateStatus, messages);
                break;
            
            case 'tts_sentence_start':
            case 'tts_sentence_end':
                console.log(`收到消息: ${data.type}`, data);
                break;
                
            case 'stop_audio':
                console.log('收到停止音频播放命令');
                // 立即停止所有音频播放
                window.AudioProcessor.stopAudioPlayback();
                break;
                
            case 'server_interrupt':
            case 'interrupt_acknowledged':
            case 'stop_acknowledged':
                console.log(`收到消息: ${data.type}`, data);
                // 立即停止所有音频播放
                window.AudioProcessor.stopAudioPlayback();
                break;
                
            case 'error':
                console.log(`收到消息: ${data.type}`, data);
                if (data.type === 'error') {
                    updateStatus('error', data.message || '发生错误');
                }
                break;
        }
    },

    // 处理部分转录结果
    handlePartialTranscript(data, messages) {
        if (!data.content.trim()) return;
        
        // 检查或创建用户消息气泡
        let userBubble = document.getElementById('current-user-bubble');
        
        if (userBubble) {
            // 更新现有气泡
            userBubble.textContent = data.content;
        } else {
            // 创建新的用户消息
            const message = document.createElement('div');
            message.className = 'message user-message';
            message.id = 'current-user-bubble';
            message.textContent = data.content;
            
            messages.appendChild(message);
            messages.scrollTop = messages.scrollHeight;
        }
    },

    // 处理最终转录结果
    handleFinalTranscript(data, messages) {
        const userBubble = document.getElementById('current-user-bubble');
        
        if (userBubble) {
            // 更新最终内容
            userBubble.textContent = data.content;
            userBubble.id = '';
        } else {
            // 创建新的用户消息
            const message = document.createElement('div');
            message.className = 'message user-message';
            message.textContent = data.content;
            
            messages.appendChild(message);
            messages.scrollTop = messages.scrollHeight;
        }
    },

    // 处理LLM状态
    handleLLMStatus(data, updateStatus, messages) {
        if (data.status === 'processing') {
            updateStatus('thinking', 'AI思考中...');
            isAIResponding = true;
            
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
    },

    // 处理LLM响应
    handleLLMResponse(data, updateStatus, messages) {
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
                isAIResponding = false;
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
            isAIResponding = false;
        }
    },

    // 发送命令
    sendCommand(type, data = {}) {
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            console.error('WebSocket未连接，无法发送命令');
            return;
        }
        
        const command = {
            type: type,
            ...data
        };
        
        socket.send(JSON.stringify(command));
        console.log(`发送命令: ${type}`);
    },

    // 发送停止并清空队列的命令
    sendStopAndClearQueues() {
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            console.error('WebSocket未连接，无法发送命令');
            return;
        }
        
        const command = {
            type: 'stop',
            clear_queues: true,  // 指示服务器清空所有发送队列
            force_stop: true     // 强制停止所有处理
        };
        
        socket.send(JSON.stringify(command));
        console.log('发送强制停止并清空队列命令');
        
        // 立即停止本地音频播放
        window.AudioProcessor.stopAudioPlayback();
    },

    // 检查用户语音中断
    checkVoiceInterruption(audioData) {
        if (!isAIResponding) return;
        
        // 简化：检测音量超过阈值时中断AI响应
        const volume = this.calculateAudioLevel(audioData);
        const THRESHOLD = 0.1;
        
        if (volume > THRESHOLD) {
            console.log('检测到用户开始说话，停止AI响应');
            this.sendCommand('interrupt');
            isAIResponding = false;
        }
    },

    // 计算音频音量级别
    calculateAudioLevel(audioData) {
        if (!audioData || audioData.length === 0) return 0;
        
        let sum = 0;
        for (let i = 0; i < audioData.length; i++) {
            sum += Math.abs(audioData[i]);
        }
        
        return sum / audioData.length;
    }
};

// 导出WebSocketHandler对象
window.WebSocketHandler = WebSocketHandler; 