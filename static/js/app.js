/**
 * 实时语音对话主控制模块
 * @module app
 */

import audioProcessor from './audio-processor.js';
import websocketHandler from './websocket-handler.js';

// 常量定义
const CONSTANTS = {
    AUDIO_CONFIG: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
    }
};

// 状态管理
const state = {
    activeMediaStream: null,
    audioProcessorNode: null,
    isSessionActive: false,
    deviceSampleRate: 0,
    needsResampling: false,
    isInitialAudioBlock: true
};

// DOM元素缓存
const elements = {
    startButton: document.getElementById('start-btn'),
    stopButton: document.getElementById('stop-btn'),
    resetButton: document.getElementById('reset-btn'),
    messagesContainer: document.getElementById('messages'),
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text')
};

/**
 * 状态管理类
 * @class StateManager
 */
class StateManager {
    /**
     * 更新状态显示
     * @param {string} state - 状态类型
     * @param {string} message - 状态消息
     */
    static updateStatus(state, message) {
        if (!elements.statusDot || !elements.statusText) return;
        
        elements.statusDot.className = state;
        elements.statusText.textContent = message;
    }

    /**
     * 更新按钮状态
     * @param {boolean} isActive - 是否激活
     */
    static updateButtonStates(isActive) {
        if (!elements.startButton || !elements.stopButton) return;
        
        elements.startButton.disabled = isActive;
        elements.stopButton.disabled = !isActive;
    }
}

/**
 * 音频处理类
 * @class AudioManager
 */
class AudioManager {
    /**
     * 初始化音频系统
     * @returns {Promise<boolean>} 初始化是否成功
     */
    static async initializeAudio() {
        try {
            state.activeMediaStream = await navigator.mediaDevices.getUserMedia({
                audio: CONSTANTS.AUDIO_CONFIG
            });

            if (!audioProcessor.initAudioContext()) {
                throw new Error('无法初始化音频上下文');
            }

            const audioContext = audioProcessor.getAudioContext();
            state.deviceSampleRate = audioContext.sampleRate;
            state.needsResampling = state.deviceSampleRate !== audioProcessor.SAMPLE_RATE;

            const audioSource = audioContext.createMediaStreamSource(state.activeMediaStream);
            state.audioProcessorNode = audioContext.createScriptProcessor(
                audioProcessor.BUFFER_SIZE,
                audioProcessor.CHANNELS,
                audioProcessor.CHANNELS
            );

            state.audioProcessorNode.onaudioprocess = this.processUserSpeech.bind(this);
            audioSource.connect(state.audioProcessorNode);
            state.audioProcessorNode.connect(audioContext.destination);

            return true;
        } catch (error) {
            console.error('音频初始化错误:', error);
            StateManager.updateStatus('error', '麦克风访问错误');
            return false;
        }
    }

    /**
     * 处理用户语音数据
     * @param {AudioProcessingEvent} event - 音频处理事件
     */
    static processUserSpeech(event) {
        if (!state.isSessionActive || !websocketHandler.getSocket() ||
            websocketHandler.getSocket().readyState !== WebSocket.OPEN) return;

        const microphoneData = event.inputBuffer.getChannelData(0);
        websocketHandler.checkVoiceInterruption(microphoneData);

        let audioToProcess = microphoneData;
        if (state.needsResampling) {
            audioToProcess = audioProcessor.downsampleBuffer(
                microphoneData,
                state.deviceSampleRate,
                audioProcessor.SAMPLE_RATE
            );
        }

        const pcmAudioData = audioProcessor.convertFloat32ToInt16(audioToProcess);
        websocketHandler.sendAudioData(pcmAudioData, state.isInitialAudioBlock);

        if (state.isInitialAudioBlock) {
            state.isInitialAudioBlock = false;
        }
    }

    /**
     * 清理音频资源
     */
    static cleanup() {
        if (state.activeMediaStream) {
            state.activeMediaStream.getTracks().forEach(track => track.stop());
            state.activeMediaStream = null;
        }

        if (state.audioProcessorNode) {
            state.audioProcessorNode.disconnect();
            state.audioProcessorNode = null;
        }

        const audioContext = audioProcessor.getAudioContext();
        if (audioContext?.state === "running" && !audioProcessor.isPlaying()) {
            audioContext.suspend().catch(console.error);
        }
    }
}

/**
 * 会话管理类
 * @class SessionManager
 */
class SessionManager {
    /**
     * 开始对话
     */
    static async startConversation() {
        if (await AudioManager.initializeAudio()) {
            state.isSessionActive = true;
            StateManager.updateStatus('listening', '正在听取...');
            StateManager.updateButtonStates(true);
            websocketHandler.sendCommand('start');
        }
    }

    /**
     * 结束对话
     */
    static endConversation() {
        if (!state.isSessionActive) return;

        state.isSessionActive = false;
        state.isInitialAudioBlock = true;

        audioProcessor.stopAudioPlayback();
        AudioManager.cleanup();
        websocketHandler.sendStopAndClearQueues();

        StateManager.updateButtonStates(false);
        StateManager.updateStatus('idle', '已停止');
    }

    /**
     * 重置对话
     */
    static resetConversation() {
        if (state.isSessionActive) {
            this.endConversation();
        }

        audioProcessor.stopAudioPlayback();
        elements.messagesContainer.innerHTML = '';
        state.isInitialAudioBlock = true;

        websocketHandler.sendCommand('reset');
        StateManager.updateStatus('idle', '已重置');
    }
}

/**
 * 事件管理类
 * @class EventManager
 */
class EventManager {
    /**
     * 初始化事件监听
     */
    static initialize() {
        // 按钮事件
        elements.startButton?.addEventListener('click', SessionManager.startConversation);
        elements.stopButton?.addEventListener('click', SessionManager.endConversation);
        elements.resetButton?.addEventListener('click', SessionManager.resetConversation);

        // 音频上下文恢复
        document.addEventListener('click', () => {
            const audioContext = audioProcessor.getAudioContext();
            if (audioContext?.state === 'suspended') {
                audioContext.resume().catch(console.error);
            }
        });

        // 消息容器滚动优化
        elements.messagesContainer?.addEventListener('scroll', () => {}, { passive: true });

        // 页面卸载清理
        window.addEventListener('beforeunload', () => {
            if (state.isSessionActive) {
                SessionManager.endConversation();
            }

            const socket = websocketHandler.getSocket();
            if (socket) socket.close();

            const audioContext = audioProcessor.getAudioContext();
            if (audioContext) audioContext.close().catch(console.error);
        });
    }
}

/**
 * 应用初始化
 */
function init() {
    try {
        websocketHandler.initializeWebSocket(StateManager.updateStatus, elements.startButton);
        EventManager.initialize();
    } catch (error) {
        console.error('应用初始化错误:', error);
        StateManager.updateStatus('error', '初始化失败');
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', init); 