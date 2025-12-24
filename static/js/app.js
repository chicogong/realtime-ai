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
        echoCancellation: true,     // 回声消除
        noiseSuppression: true,     // 噪声抑制
        autoGainControl: true,      // 自动增益控制
        PROCESSING_INTERVAL: 40     // 音频处理间隔 每40毫秒处理一次音频数据，近似于常见的音频块大小
    }
};

// 状态管理
const state = {
    activeMediaStream: null,       // 当前活动的媒体流
    audioProcessorNode: null,      // 音频处理节点
    isSessionActive: false,        // 会话是否激活
    deviceSampleRate: 0,           // 设备采样率
    needsResampling: false,        // 是否需要重采样
    isInitialAudioBlock: true,     // 是否是首个音频块
    inputContext: null,            // 输入音频上下文
    audioBuffer: [],               // 音频缓冲区
    processingInterval: null       // 处理间隔ID
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

            // 创建专用于输入的音频上下文
            state.inputContext = new (window.AudioContext || window.webkitAudioContext)();
            state.deviceSampleRate = state.inputContext.sampleRate;
            state.needsResampling = state.deviceSampleRate !== audioProcessor.SAMPLE_RATE;

            // 初始化音频处理节点，仅用于播放的音频上下文
            if (!audioProcessor.initAudioContext()) {
                throw new Error('无法初始化音频上下文');
            }

            // 设置音频处理 - 使用AnalyserNode而非ScriptProcessor
            const source = state.inputContext.createMediaStreamSource(state.activeMediaStream);
            const analyser = state.inputContext.createAnalyser();
            analyser.fftSize = 2048;
            source.connect(analyser);
            
            // 创建一个时间间隔来定期处理音频数据，而不是使用ScriptProcessor
            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Float32Array(bufferLength);
            
            // 每40毫秒处理一次音频数据，近似于常见的音频块大小
            state.processingInterval = setInterval(() => {
                if (!state.isSessionActive) return;
                
                analyser.getFloatTimeDomainData(dataArray);
                this.processMicrophoneData(dataArray);
            }, audioProcessor.AUDIO_CONFIG.PROCESSING_INTERVAL);

            return true;
        } catch (error) {
            console.error('音频初始化错误:', error);
            ui.StateManager.updateStatus('error', '麦克风访问错误');
            return false;
        }
    }

    /**
     * 处理麦克风数据
     * @param {Float32Array} microphoneData 麦克风数据
     */
    static processMicrophoneData(microphoneData) {
        if (!state.isSessionActive || !websocketHandler.getSocket() ||
            websocketHandler.getSocket().readyState !== WebSocket.OPEN) return;

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
        // 停止处理间隔
        if (state.processingInterval) {
            clearInterval(state.processingInterval);
            state.processingInterval = null;
        }

        // 停止媒体流
        if (state.activeMediaStream) {
            state.activeMediaStream.getTracks().forEach(track => track.stop());
            state.activeMediaStream = null;
        }

        // 关闭输入音频上下文
        if (state.inputContext && state.inputContext.state !== 'closed') {
            state.inputContext.close().catch(console.error);
            state.inputContext = null;
        }

        // 暂停播放音频上下文
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
        
        // 绑定文本输入事件
        ui.EventBinder.bindTextInput(
            // 输入变化处理 - 根据输入内容和连接状态更新发送按钮
            () => {
                const hasText = ui.elements.textInput?.value.trim().length > 0;
                const isConnected = websocketHandler.getSocket()?.readyState === WebSocket.OPEN;
                ui.StateManager.updateSendButtonState(hasText && isConnected);
            },
            // 提交处理 - 发送文本消息
            () => {
                const text = ui.elements.textInput?.value.trim();
                if (text && websocketHandler.getSocket()?.readyState === WebSocket.OPEN) {
                    // 发送文本输入命令
                    websocketHandler.sendCommand('text_input', { text });
                    // 清空输入框
                    ui.elements.textInput.value = '';
                    // 禁用发送按钮
                    ui.StateManager.updateSendButtonState(false);
                }
            }
        );
        
        // 音频上下文恢复
        ui.EventBinder.bindAudioContextResume(() => {
            const audioContext = audioProcessor.getAudioContext();
            if (audioContext?.state === 'suspended') {
                audioContext.resume().catch(console.error);
            }
            if (state.inputContext?.state === 'suspended') {
                state.inputContext.resume().catch(console.error);
            }
        });
        
        // 页面卸载清理
        ui.EventBinder.bindPageUnload(() => {
            if (state.isSessionActive) {
                SessionManager.endConversation();
            }
            const socket = websocketHandler.getSocket();
            if (socket) socket.close();
            
            // 关闭所有音频上下文
            const audioContext = audioProcessor.getAudioContext();
            if (audioContext && audioContext.state !== 'closed') {
                audioContext.close().catch(console.error);
            }
            if (state.inputContext && state.inputContext.state !== 'closed') {
                state.inputContext.close().catch(console.error);
            }
        });
    }
}

/**
 * 应用初始化
 * 初始化WebSocket连接和事件监听
 */
function init() {
    try {
        // 连接成功回调 - 根据输入框内容更新发送按钮状态
        const onConnected = () => {
            const hasText = ui.elements.textInput?.value.trim().length > 0;
            ui.StateManager.updateSendButtonState(hasText);
        };
        
        websocketHandler.initializeWebSocket(
            ui.StateManager.updateStatus,
            ui.elements.startButton,
            onConnected
        );
        EventManager.initialize();
    } catch (error) {
        console.error('应用初始化错误:', error);
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', init);