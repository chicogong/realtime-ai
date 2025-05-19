/**
 * UI管理模块
 * 负责处理所有UI相关的功能，包括：
 * 1. 状态显示
 * 2. 按钮状态管理
 * 3. 消息渲染
 * 4. 动画效果
 * @module ui
 */

// DOM元素缓存
const elements = {
    startButton: document.getElementById('start-btn'),      // 开始按钮
    stopButton: document.getElementById('stop-btn'),        // 停止按钮
    resetButton: document.getElementById('reset-btn'),      // 重置按钮
    textInput: document.getElementById('text-input'),       // 文本输入框
    sendButton: document.getElementById('send-button'),     // 发送按钮
    chatList: document.querySelector('.chat-list'),         // 聊天列表
    statusIcon: document.getElementById('status-icon'),     // 状态图标
    statusMessage: document.getElementById('status-message')// 状态消息
};

/**
 * 状态管理类
 * 负责管理UI状态和按钮状态
 */
class StateManager {
    /**
     * 更新状态显示
     * @param {string} state - 状态类型（idle/listening/thinking/error）
     * @param {string} message - 状态消息
     */
    static updateStatus(state, message) {
        if (!elements.statusIcon || !elements.statusMessage) return;
        
        // 移除所有状态类
        elements.statusIcon.className = 'status-icon';
        
        // 添加当前状态类
        if (state) {
            elements.statusIcon.classList.add(state);
        }
        
        // 更新状态消息
        if (message) {
            elements.statusMessage.textContent = message;
        }
    }

    /**
     * 更新按钮状态
     * @param {boolean} isActive - 是否激活（true: 启用停止按钮，禁用开始按钮）
     */
    static updateButtonStates(isActive) {
        if (!elements.startButton || !elements.stopButton) return;
        
        elements.startButton.disabled = isActive;
        elements.stopButton.disabled = !isActive;
    }
    
    /**
     * 更新发送按钮状态
     * @param {boolean} enabled - 是否启用发送按钮
     */
    static updateSendButtonState(enabled) {
        if (!elements.sendButton) return;
        
        elements.sendButton.disabled = !enabled;
    }
}

/**
 * 消息渲染类
 * 负责创建和渲染聊天消息
 */
class MessageRenderer {
    /**
     * 添加消息到聊天列表
     * @param {string} content - 消息内容
     * @param {string} sender - 发送者（'user' 或 'ai'）
     * @param {boolean} isTyping - 是否显示为正在输入状态
     * @returns {HTMLElement} 创建的消息元素
     */
    static addMessage(content, sender, isTyping = false) {
        if (!elements.chatList) return null;
        
        // 创建消息容器
        const messageItem = document.createElement('div');
        messageItem.className = `chat-item ${sender}`;
        
        // 创建消息气泡
        const messageBubble = document.createElement('div');
        messageBubble.className = 'chat-bubble';
        
        // 创建消息内容
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        
        // 如果是正在输入状态，添加输入指示器
        if (isTyping) {
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            
            for (let i = 0; i < 3; i++) {
                const dot = document.createElement('span');
                typingIndicator.appendChild(dot);
            }
            
            messageContent.appendChild(typingIndicator);
        } else {
            // 否则添加普通文本内容
            messageContent.innerHTML = content;
        }
        
        // 组装消息
        messageBubble.appendChild(messageContent);
        messageItem.appendChild(messageBubble);
        
        // 添加到聊天列表
        elements.chatList.appendChild(messageItem);
        
        // 滚动到底部
        this.scrollToBottom();
        
        return messageItem;
    }
    
    /**
     * 更新消息内容
     * @param {HTMLElement} messageElement - 要更新的消息元素
     * @param {string} content - 新的消息内容
     */
    static updateMessage(messageElement, content) {
        if (!messageElement) return;
        
        const messageContent = messageElement.querySelector('.message-content');
        if (messageContent) {
            messageContent.innerHTML = content;
        }
    }
    
    /**
     * 滚动聊天列表到底部
     */
    static scrollToBottom() {
        if (!elements.chatList) return;
        
        elements.chatList.scrollTop = elements.chatList.scrollHeight;
    }
    
    /**
     * 清空聊天列表
     */
    static clearMessages() {
        if (!elements.chatList) return;
        
        elements.chatList.innerHTML = '';
    }
}

/**
 * 事件绑定类
 * 负责处理UI相关的事件绑定
 */
class EventBinder {
    /**
     * 绑定按钮点击事件
     * @param {string} buttonId - 按钮ID
     * @param {Function} handler - 事件处理函数
     */
    static bindButtonClick(buttonId, handler) {
        const button = document.getElementById(buttonId);
        if (button) {
            button.addEventListener('click', handler);
        }
    }
    
    /**
     * 绑定文本输入事件
     * @param {Function} inputHandler - 输入事件处理函数
     * @param {Function} submitHandler - 提交事件处理函数
     */
    static bindTextInput(inputHandler, submitHandler) {
        if (elements.textInput) {
            // 监听输入变化
            elements.textInput.addEventListener('input', inputHandler);
            
            // 监听回车键提交
            elements.textInput.addEventListener('keypress', (event) => {
                if (event.key === 'Enter' && !event.shiftKey && !elements.sendButton.disabled) {
                    event.preventDefault();
                    submitHandler();
                }
            });
        }
        
        // 发送按钮点击
        if (elements.sendButton) {
            elements.sendButton.addEventListener('click', submitHandler);
        }
    }
    
    /**
     * 绑定音频上下文恢复事件
     * @param {Function} resumeHandler - 恢复处理函数
     */
    static bindAudioContextResume(resumeHandler) {
        document.addEventListener('click', resumeHandler, { once: false });
    }
    
    /**
     * 绑定页面卸载事件
     * @param {Function} cleanupHandler - 清理处理函数
     */
    static bindPageUnload(cleanupHandler) {
        window.addEventListener('beforeunload', cleanupHandler);
    }
}

// 导出模块
export default {
    elements,
    StateManager,
    MessageRenderer,
    EventBinder
}; 