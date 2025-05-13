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
                
                // 显示AI正在输入
                if (messages) {
                    const typingMessage = document.createElement('div');
                    typingMessage.id = 'ai-typing';
                    typingMessage.className = 'message ai-message';
                    typingMessage.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
                    messages.appendChild(typingMessage);
                    messages.scrollTop = messages.scrollHeight;
                }
            }
            break;
        
        case 'llm_response':
            // 删除输入指示器
            const typingIndicator = document.getElementById('ai-typing');
            if (typingIndicator) {
                typingIndicator.remove();
            }
            
            // 处理响应
            if (data.is_complete) {
                // 完整响应
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
    
    const message = document.createElement('div');
    message.className = `message ${type}-message`;
    message.textContent = text;
    messages.appendChild(message);
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