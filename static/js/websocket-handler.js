/**
 * WebSocket处理模块
 * 管理与服务器的WebSocket通信，处理音频数据的发送和接收，
 * 以及处理各种类型的消息（转录、LLM响应、音频控制等）
 * @module websocket-handler
 */

import audioProcessor from './audio-processor.js';
import ui from './ui.js';

// WebSocket配置常量
const WS_CONFIG = {
    RECONNECT_DELAY: 5000,        // 重连延迟时间（毫秒）
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
    statusCallback: null,  // 状态更新回调函数
    audioConfig: null,     // 音频配置

    /**
     * 获取音频配置
     * @private
     * @returns {Object} 音频配置对象
     */
    _getAudioConfig() {
        if (!this.audioConfig) {
            this.audioConfig = {
                AUDIO_HEADER_SIZE: audioProcessor.AUDIO_CONFIG.AUDIO_HEADER_SIZE,
                VOLUME_THRESHOLD: audioProcessor.AUDIO_CONFIG.VOLUME_THRESHOLD,
                SILENCE_THRESHOLD: audioProcessor.AUDIO_CONFIG.SILENCE_THRESHOLD,
                DEFAULT_VOLUME: audioProcessor.AUDIO_CONFIG.DEFAULT_VOLUME
            };
        }
        return this.audioConfig;
    },

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
        this.statusCallback = updateStatus;
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
            this._updateStatus('idle', '已连接，准备就绪');
            startButton.disabled = false;
            audioProcessor.initAudioContext();
        };
        
        // 消息处理
        this.socket.onmessage = (event) => this._handleSocketMessage(event);
        
        // 连接关闭处理
        this.socket.onclose = () => {
            console.log('WebSocket连接关闭');
            this._updateStatus('error', '连接已断开');
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
            this._updateStatus('error', '连接错误');
        };
    },

    /**
     * 更新状态（集中处理状态更新）
     * @private
     * @param {string} state - 状态类型
     * @param {string} message - 状态消息
     */
    _updateStatus(state, message) {
        // 更新UI状态
        ui.StateManager.updateStatus(state, message);
        
        // 回调外部状态更新函数（如果存在）
        if (this.statusCallback) {
            this.statusCallback(state, message);
        }
        
        // 更新状态框
        this._updateStatusBox(state, message);
    },

    /**
     * 处理所有WebSocket消息
     * 根据消息类型分发到不同的处理函数
     * @private
     * @param {MessageEvent} event - WebSocket消息事件
     */
    _handleSocketMessage(event) {
        try {
            if (typeof event.data === 'string') {
                // 处理JSON格式的消息
                const messageData = JSON.parse(event.data);
                this._handleMessage(messageData);
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
     */
    _handleMessage(messageData) {
        switch (messageData.type) {
            case 'status':
                // 处理会话状态信息
                if (messageData.status === 'listening') {
                    this._updateStatus('listening', '正在听取...');
                } else if (messageData.status === 'thinking') {
                    this._updateStatus('thinking', 'AI思考中...');
                } else if (messageData.status === 'idle') {
                    this._updateStatus('idle', '已完成');
                } else if (messageData.status === 'error') {
                    const errorMsg = messageData.message || '发生错误';
                    this._updateStatus('error', errorMsg);
                }
                break;
            
            case MESSAGE_TYPES.PARTIAL_TRANSCRIPT:
                this._updateStatus('listening', '正在听取...');
                this._handleTranscript(messageData, true);
                break;
            
            case MESSAGE_TYPES.FINAL_TRANSCRIPT:
                this._handleTranscript(messageData, false);
                break;
            
            case MESSAGE_TYPES.LLM_STATUS:
                this._updateStatus('thinking', 'AI思考中...');
                this._handleLLMStatus(messageData);
                break;
            
            case MESSAGE_TYPES.LLM_RESPONSE:
                if (messageData.is_complete) {
                    this._updateStatus('idle', '已完成');
                }
                this._handleLLMResponse(messageData);
                break;
                
            case MESSAGE_TYPES.AUDIO_START:
                this._updateStatus('thinking', '正在回复...');
                break;
                
            case MESSAGE_TYPES.AUDIO_END:
                this._updateStatus('idle', '已完成');
                break;
            
            case MESSAGE_TYPES.TTS_START:
                this._updateStatus('thinking', '正在生成语音...');
                break;
            
            case MESSAGE_TYPES.TTS_END:
                this._updateStatus('idle', '已完成');
                break;
            
            case MESSAGE_TYPES.TTS_STOP:
                this._updateStatus('idle', '已停止');
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
                // 处理错误消息
                console.error(`服务器错误: ${messageData.message}`);
                this._updateStatus('error', messageData.message || '发生错误');
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
     * @param {boolean} isPartial - 是否为部分转录
     */
    _handleTranscript(messageData, isPartial) {
        if (!messageData.content.trim()) return;
        // 部分转录时复用气泡
        if (isPartial) {
            // 先移除旧的部分转录气泡
            if (this._partialUserMsg) {
                ui.MessageRenderer.updateMessage(this._partialUserMsg, messageData.content);
            } else {
                this._partialUserMsg = ui.MessageRenderer.addMessage(messageData.content, 'user', true);
            }
        } else {
            // 最终转录，移除部分转录气泡，添加最终气泡
            if (this._partialUserMsg) {
                this._partialUserMsg.remove();
                this._partialUserMsg = null;
            }
            ui.MessageRenderer.addMessage(messageData.content, 'user', false);
        }
    },

    /**
     * 处理LLM状态
     * 显示AI思考状态和输入指示器
     * @private
     * @param {Object} messageData - 消息数据
     */
    _handleLLMStatus(messageData) {
        if (messageData.status === 'processing') {
            this.isAIResponding = true;
            // 移除现有的AI消息容器
            if (this._aiMsg) {
                this._aiMsg.remove();
                this._aiMsg = null;
            }
            // 添加AI输入指示器
            this._aiMsg = ui.MessageRenderer.addMessage('', 'ai', true);
        }
    },

    /**
     * 处理LLM响应
     * 显示AI的响应内容，支持流式响应
     * @private
     * @param {Object} messageData - 消息数据
     */
    _handleLLMResponse(messageData) {
        // 流式响应时复用最后一个AI气泡
        if (this._aiMsg) {
            ui.MessageRenderer.updateMessage(this._aiMsg, messageData.content);
            if (messageData.is_complete) {
                this._aiMsg = null;
                this.isAIResponding = false;
            }
        } else {
            this._aiMsg = ui.MessageRenderer.addMessage(messageData.content, 'ai', false);
            if (messageData.is_complete) {
                this._aiMsg = null;
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
            
            // 发送start命令时立即更新状态为"listening"
            if (command === 'start') {
                this._updateStatus('listening', '正在听取...');
            }
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
            const audioConfig = this._getAudioConfig();
            // 创建带头部的数据缓冲区
            const combinedBuffer = new ArrayBuffer(audioConfig.AUDIO_HEADER_SIZE + pcmData.byteLength);
            const headerView = new DataView(combinedBuffer, 0, audioConfig.AUDIO_HEADER_SIZE);
            
            // 设置时间戳（毫秒）
            headerView.setUint32(0, Date.now(), true);
            
            // 设置状态标志
            let statusFlags = 0;
            
            if (pcmData instanceof Float32Array) {
                // 计算音频能量值（0-255）
                const audioEnergy = Math.min(255, Math.floor(this._calculateAudioLevel(pcmData) * 1000));
                statusFlags |= audioEnergy & 0xFF;
                
                // 检测静音
                if (pcmData.every(sample => Math.abs(sample) < audioConfig.SILENCE_THRESHOLD)) {
                    statusFlags |= STATUS_FLAGS.SILENCE;
                }
            } else {
                // 对于Int16Array数据，设置默认音量
                statusFlags |= audioConfig.DEFAULT_VOLUME;
            }
            
            // 设置首个音频块标志
            if (isFirstBlock) {
                statusFlags |= STATUS_FLAGS.FIRST_BLOCK;
            }
            
            headerView.setUint32(4, statusFlags, true);
            
            // 复制PCM数据到缓冲区
            new Uint8Array(combinedBuffer, audioConfig.AUDIO_HEADER_SIZE).set(
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
            const audioConfig = this._getAudioConfig();
            
            if (audioLevel > audioConfig.VOLUME_THRESHOLD) {
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
        
        // 如果是idle状态，但是是"已连接，准备就绪"消息，则显示状态框
        if (status === 'idle' && message === '已连接，准备就绪') {
            statusBox.classList.remove('hidden');
        } 
        // 其他idle状态，可以把透明度降低但不需要完全隐藏
        else if (status === 'idle') {
            statusBox.classList.add('hidden');
        } else {
            statusBox.classList.remove('hidden');
        }
    }
};

// 使用ES模块导出
export default websocketHandler; 