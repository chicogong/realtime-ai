/**
 * WebSocket处理模块
 * 处理与服务器的WebSocket通信
 */

// WebSocket变量
let socket = null;
let isAIResponding = false;

// 移除DOM元素的全局引用
// let partialTranscript, messages, statusDot, statusText;

/**
 * 初始化WebSocket连接
 * @param {Function} updateStatus - 更新状态的回调函数
 * @param {HTMLElement} startBtn - 开始按钮元素
 */
function initializeWebSocket(updateStatus, startBtn) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    if (socket && socket.readyState !== WebSocket.CLOSED) {
        socket.close();
    }
    
    socket = new WebSocket(wsUrl);
    
    socket.onopen = function(event) {
        console.log('WebSocket连接成功');
        updateStatus('idle', '已连接，准备就绪');
        startBtn.disabled = false;
        
        // 确保音频上下文已初始化
        window.AudioProcessor.initAudioContext();
    };
    
    socket.onmessage = function(event) {
        try {
            // 判断消息类型（文本或二进制）
            if (typeof event.data === 'string') {
                // JSON消息
                const data = JSON.parse(event.data);
                
                // 处理普通JSON消息
                handleSocketMessage(data, updateStatus);
            } else if (event.data instanceof Blob) {
                // 处理二进制音频数据
                window.AudioProcessor.handleBinaryAudioData(event.data);
            }
        } catch (e) {
            console.error('处理消息时出错:', e);
        }
    };
    
    socket.onclose = function(event) {
        console.log('WebSocket连接关闭');
        updateStatus('error', '连接已断开');
        startBtn.disabled = true;
        
        // 5秒后尝试重连
        setTimeout(function() {
            console.log('尝试重新连接...');
            initializeWebSocket(updateStatus, startBtn);
        }, 5000);
    };
    
    socket.onerror = function(error) {
        console.error('WebSocket错误:', error);
        updateStatus('error', '连接错误');
    };
}

/**
 * 处理WebSocket消息
 * @param {Object} data - 解析后的JSON消息
 * @param {Function} updateStatus - 更新状态的回调函数
 */
function handleSocketMessage(data, updateStatus) {
    // 使用DOM选择器直接获取元素而不是使用全局变量
    const partialTranscript = document.getElementById('partial-transcript');
    const messages = document.getElementById('messages');

    switch (data.type) {
        case 'partial_transcript':
            if (partialTranscript) {
                partialTranscript.textContent = data.content;
            }
            break;
        
        case 'final_transcript':
            addMessage(data.content, 'user');
            if (partialTranscript) {
                partialTranscript.textContent = '';
            }
            break;
        
        case 'llm_status':
            if (data.status === 'processing') {
                updateStatus('thinking', 'AI思考中...');
                isAIResponding = true;
                
                // 创建或重置AI消息容器
                if (messages) {
                    // 删除现有的打字指示器和消息容器
                    const existingTyping = document.getElementById('ai-typing');
                    if (existingTyping) {
                        existingTyping.remove();
                    }
                    
                    const existingContainer = document.getElementById('ai-message-container');
                    if (existingContainer) {
                        existingContainer.remove();
                    }
                    
                    // 创建消息包装容器（为了正确定位）
                    const messageWrapper = document.createElement('div');
                    messageWrapper.style.display = 'flex';
                    messageWrapper.style.justifyContent = 'flex-start';
                    messageWrapper.style.width = '100%';
                    
                    // 创建新的AI消息容器
                    const aiMessageContainer = document.createElement('div');
                    aiMessageContainer.id = 'ai-message-container';
                    aiMessageContainer.className = 'message ai-message stream-message message-short';
                    
                    // 添加打字指示器
                    const typingIndicator = document.createElement('div');
                    typingIndicator.id = 'ai-typing';
                    typingIndicator.className = 'typing-indicator';
                    typingIndicator.innerHTML = '<span></span><span></span><span></span>';
                    
                    // 组装元素
                    aiMessageContainer.appendChild(typingIndicator);
                    messageWrapper.appendChild(aiMessageContainer);
                    messages.appendChild(messageWrapper);
                    
                    // 滚动到底部
                    messages.scrollTop = messages.scrollHeight;
                }
            }
            break;
        
        case 'llm_response':
            // 获取AI消息容器
            const aiMessageContainer = document.getElementById('ai-message-container');
            
            if (aiMessageContainer) {
                // 删除打字指示器
                const typingIndicator = document.getElementById('ai-typing');
                if (typingIndicator) {
                    typingIndicator.remove();
                }
                
                if (data.is_complete) {
                    // 更新完整消息内容
                    aiMessageContainer.textContent = data.content;
                    aiMessageContainer.classList.remove('stream-message');
                    
                    // 根据内容长度设置不同的大小类
                    aiMessageContainer.classList.remove('message-short', 'message-medium', 'message-long');
                    if (data.content.length < 20) {
                        aiMessageContainer.classList.add('message-short');
                    } else if (data.content.length < 100) {
                        aiMessageContainer.classList.add('message-medium');
                    } else {
                        aiMessageContainer.classList.add('message-long');
                    }
                    
                    // 重置ID以便下一次响应
                    aiMessageContainer.id = '';
                    updateStatus('idle', '已完成');
                    isAIResponding = false;
                } else {
                    // 更新流式内容
                    aiMessageContainer.textContent = data.content;
                    
                    // 根据当前内容长度设置不同的大小类
                    aiMessageContainer.classList.remove('message-short', 'message-medium', 'message-long');
                    if (data.content.length < 20) {
                        aiMessageContainer.classList.add('message-short');
                    } else if (data.content.length < 100) {
                        aiMessageContainer.classList.add('message-medium');
                    } else {
                        aiMessageContainer.classList.add('message-long');
                    }
                    
                    // 保留打字指示器
                    const typingIndicator = document.createElement('div');
                    typingIndicator.id = 'ai-typing';
                    typingIndicator.className = 'typing-indicator';
                    typingIndicator.innerHTML = '<span></span><span></span><span></span>';
                    aiMessageContainer.appendChild(typingIndicator);
                }
                
                // 滚动到底部
                if (messages) {
                    messages.scrollTop = messages.scrollHeight;
                }
            } else if (data.is_complete) {
                // 如果没有找到容器但收到了完整响应，创建新消息
                addMessage(data.content, 'ai');
                updateStatus('idle', '已完成');
                isAIResponding = false;
            }
            break;
        
        case 'tts_sentence_start':
            console.log(`开始处理新句子: ${data.text}, ID: ${data.sentence_id}`);
            break;
        
        case 'tts_sentence_end':
            console.log(`句子处理结束: ID: ${data.sentence_id}`);
            break;
        
        case 'status':
            if (data.status === 'listening') {
                updateStatus('listening', '正在听取...');
            } else if (data.status === 'stopped') {
                updateStatus('idle', '已停止');
            }
            break;
        
        case 'error':
            console.error('Server error:', data.message);
            updateStatus('error', `错误: ${data.message}`);
            break;
        
        case 'server_interrupt':
            console.log("收到服务器打断信令:", data.message);
            window.AudioProcessor.stopAudioPlayback();
            updateStatus('listening', '已打断，正在听取...');
            isAIResponding = false;
            break;
        
        case 'stop_acknowledged':
            console.log("收到停止确认:", data.message);
            window.AudioProcessor.stopAudioPlayback();
            updateStatus('idle', '已停止');
            isAIResponding = false;
            break;
    }
}

/**
 * 添加消息到对话框
 * @param {string} text - 消息文本
 * @param {string} type - 消息类型 (user/ai)
 */
function addMessage(text, type) {
    const messages = document.getElementById('messages');
    if (!messages) return;
    
    // 创建消息包装容器（为了正确定位）
    const messageWrapper = document.createElement('div');
    messageWrapper.style.display = 'flex';
    messageWrapper.style.justifyContent = type === 'user' ? 'flex-end' : 'flex-start';
    messageWrapper.style.width = '100%';
    
    // 创建消息元素
    const message = document.createElement('div');
    message.className = `message ${type}-message`;
    
    // 使用textContent避免XSS风险
    message.textContent = text;
    
    // 根据内容长度设置不同的大小类
    if (text.length < 20) {
        message.classList.add('message-short');
    } else if (text.length < 100) {
        message.classList.add('message-medium');
    } else {
        message.classList.add('message-long');
    }
    
    // 添加进入动画
    message.style.opacity = '0';
    message.style.transform = 'translateY(10px)';
    
    // 组装元素
    messageWrapper.appendChild(message);
    messages.appendChild(messageWrapper);
    
    // 强制回流，然后应用动画
    void message.offsetWidth;
    message.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    message.style.opacity = '1';
    message.style.transform = 'translateY(0)';
    
    // 滚动到底部
    messages.scrollTop = messages.scrollHeight;
}

/**
 * 发送命令到服务器
 * @param {string} type - 命令类型
 * @param {Object} [data] - 可选的附加数据
 */
function sendCommand(type, data = {}) {
    if (socket && socket.readyState === WebSocket.OPEN) {
        const message = { type, ...data };
        socket.send(JSON.stringify(message));
    }
}

/**
 * 检查用户语音是否打断AI响应
 * @param {Float32Array} audioData - 音频数据
 */
function checkVoiceInterruption(audioData) {
    if (isAIResponding) {
        const audioLevel = window.AudioProcessor.detectAudioLevel(audioData);
        if (audioLevel > 0.05) {
            sendCommand('interrupt');
            isAIResponding = false;
            return true;
        }
    }
    return false;
}

// 导出功能
window.WebSocketHandler = {
    initializeWebSocket,
    handleSocketMessage,
    addMessage,
    sendCommand,
    checkVoiceInterruption,
    getSocket: () => socket,
    isAIResponding: () => isAIResponding
}; 