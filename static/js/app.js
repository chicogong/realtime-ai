/**
 * 实时语音对话主控制模块
 * 负责协调整个应用的各个组件，包括：
 * 1. 音频采集和处理
 * 2. WebSocket通信
 * 3. 用户界面状态管理
 * 4. 会话流程控制
 * @module app
 */

import audioProcessor from './audio-processor.js';
import websocketHandler from './websocket-handler.js';
import ui from './ui.js';

// 常量定义
const CONSTANTS = {
    AUDIO_CONFIG: {
        echoCancellation: true,    // 回声消除
        noiseSuppression: true,    // 噪声抑制
        autoGainControl: true      // 自动增益控制
    }
};

// 状态管理
const state = {
    activeMediaStream: null,       // 当前活动的媒体流
    audioProcessorNode: null,      // 音频处理节点
    isSessionActive: false,        // 会话是否激活
    deviceSampleRate: 0,           // 设备采样率
    needsResampling: false,        // 是否需要重采样
    isInitialAudioBlock: true      // 是否是首个音频块
};

/**
 * 音频管理类
 * 负责音频系统的初始化和处理
 * @class AudioManager
 */
class AudioManager {
    /**
     * 初始化音频系统
     * 设置音频采集、处理和重采样
     * @returns {Promise<boolean>} 初始化是否成功
     */
    static async initializeAudio() {
        try {
            // 获取用户媒体流
            state.activeMediaStream = await navigator.mediaDevices.getUserMedia({
                audio: CONSTANTS.AUDIO_CONFIG
            });

            // 初始化音频上下文
            if (!audioProcessor.initAudioContext()) {
                throw new Error('无法初始化音频上下文');
            }

            // 设置音频处理
            const audioContext = audioProcessor.getAudioContext();
            state.deviceSampleRate = audioContext.sampleRate;
            state.needsResampling = state.deviceSampleRate !== audioProcessor.SAMPLE_RATE;

            // 创建音频处理节点
            const audioSource = audioContext.createMediaStreamSource(state.activeMediaStream);
            state.audioProcessorNode = audioContext.createScriptProcessor(
                audioProcessor.BUFFER_SIZE,
                audioProcessor.CHANNELS,
                audioProcessor.CHANNELS
            );

            // 设置音频处理回调
            state.audioProcessorNode.onaudioprocess = this.processUserSpeech.bind(this);
            audioSource.connect(state.audioProcessorNode);
            state.audioProcessorNode.connect(audioContext.destination);

            return true;
        } catch (error) {
            console.error('音频初始化错误:', error);
            ui.StateManager.updateStatus('error', '麦克风访问错误');
            return false;
        }
    }

    /**
     * 处理用户语音数据
     * 处理音频数据并发送到服务器
     * @param {AudioProcessingEvent} event - 音频处理事件
     */
    static processUserSpeech(event) {
        if (!state.isSessionActive || !websocketHandler.getSocket() ||
            websocketHandler.getSocket().readyState !== WebSocket.OPEN) return;

        // 获取麦克风数据
        const microphoneData = event.inputBuffer.getChannelData(0);
        websocketHandler.checkVoiceInterruption(microphoneData);

        // 处理音频数据
        let audioToProcess = microphoneData;
        if (state.needsResampling) {
            audioToProcess = audioProcessor.downsampleBuffer(
                microphoneData,
                state.deviceSampleRate,
                audioProcessor.SAMPLE_RATE
            );
        }

        // 转换为PCM格式并发送
        const pcmAudioData = audioProcessor.convertFloat32ToInt16(audioToProcess);
        websocketHandler.sendAudioData(pcmAudioData, state.isInitialAudioBlock);

        if (state.isInitialAudioBlock) {
            state.isInitialAudioBlock = false;
        }
    }

    /**
     * 清理音频资源
     * 停止所有音频流并释放资源
     */
    static cleanup() {
        // 停止媒体流
        if (state.activeMediaStream) {
            state.activeMediaStream.getTracks().forEach(track => track.stop());
            state.activeMediaStream = null;
        }

        // 断开音频处理节点
        if (state.audioProcessorNode) {
            state.audioProcessorNode.disconnect();
            state.audioProcessorNode = null;
        }

        // 暂停音频上下文
        const audioContext = audioProcessor.getAudioContext();
        if (audioContext?.state === "running" && !audioProcessor.isPlaying()) {
            audioContext.suspend().catch(console.error);
        }
    }
}

/**
 * 会话管理类
 * 负责控制对话的开始、结束和重置
 * @class SessionManager
 */
class SessionManager {
    /**
     * 开始对话
     * 初始化音频并启动WebSocket通信
     */
    static async startConversation() {
        if (await AudioManager.initializeAudio()) {
            state.isSessionActive = true;
            ui.StateManager.updateButtonStates(true);
            websocketHandler.sendCommand('start');
        }
    }

    /**
     * 结束对话
     * 停止音频处理并清理资源
     */
    static endConversation() {
        if (!state.isSessionActive) return;

        state.isSessionActive = false;
        state.isInitialAudioBlock = true;

        audioProcessor.stopAudioPlayback();
        AudioManager.cleanup();
        websocketHandler.sendStopAndClearQueues();

        ui.StateManager.updateButtonStates(false);
        ui.StateManager.updateStatus('idle', '已停止');
    }

    /**
     * 重置对话
     * 清空消息并重置所有状态
     */
    static resetConversation() {
        if (state.isSessionActive) {
            this.endConversation();
        }

        audioProcessor.stopAudioPlayback();
        ui.MessageRenderer.clearMessages();
        state.isInitialAudioBlock = true;

        websocketHandler.sendCommand('reset');
        ui.StateManager.updateStatus('idle', '已重置');
    }
}

/**
 * 事件管理类
 * 负责初始化和处理所有事件监听
 * @class EventManager
 */
class EventManager {
    /**
     * 初始化事件监听
     * 设置按钮点击、音频上下文恢复等事件处理
     */
    static initialize() {
        ui.EventBinder.bindButtonClick('start-btn', SessionManager.startConversation);
        ui.EventBinder.bindButtonClick('stop-btn', SessionManager.endConversation);
        ui.EventBinder.bindButtonClick('reset-btn', SessionManager.resetConversation);
        // 音频上下文恢复
        ui.EventBinder.bindAudioContextResume(() => {
            const audioContext = audioProcessor.getAudioContext();
            if (audioContext?.state === 'suspended') {
                audioContext.resume().catch(console.error);
            }
        });
        // 页面卸载清理
        ui.EventBinder.bindPageUnload(() => {
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
 * 初始化WebSocket连接和事件监听
 */
function init() {
    try {
        websocketHandler.initializeWebSocket(ui.StateManager.updateStatus, ui.elements.startButton);
        EventManager.initialize();
    } catch (error) {
        console.error('应用初始化错误:', error);
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', init); 