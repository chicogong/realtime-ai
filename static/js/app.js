/**
 * 实时语音对话主控制模块
 */

import audioProcessor from './audio-processor.js';
import websocketHandler from './websocket-handler.js';

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
 */
class StateManager {
    static updateStatus(state, message) {
        elements.statusDot.className = state;
        elements.statusText.textContent = message;
    }

    static updateButtonStates(isActive) {
        elements.startButton.disabled = isActive;
        elements.stopButton.disabled = !isActive;
    }
}

/**
 * 音频处理类
 */
class AudioManager {
    static async initializeAudio() {
        try {
            state.activeMediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
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

            state.audioProcessorNode.onaudioprocess = this.processUserSpeech;
            audioSource.connect(state.audioProcessorNode);
            state.audioProcessorNode.connect(audioContext.destination);

            return true;
        } catch (error) {
            console.error('音频初始化错误:', error);
            return false;
        }
    }

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

    static cleanup() {
        if (state.activeMediaStream) {
            state.activeMediaStream.getTracks().forEach(track => track.stop());
        }

        if (state.audioProcessorNode) {
            state.audioProcessorNode.disconnect();
            state.audioProcessorNode = null;
        }

        const audioContext = audioProcessor.getAudioContext();
        if (audioContext && audioContext.state === "running" && !audioProcessor.isPlaying()) {
            audioContext.suspend().catch(console.error);
        }
    }
}

/**
 * 会话管理类
 */
class SessionManager {
    static async startConversation() {
        if (await AudioManager.initializeAudio()) {
            state.isSessionActive = true;
            StateManager.updateStatus('listening', '正在听取...');
            StateManager.updateButtonStates(true);
            websocketHandler.sendCommand('start');
        } else {
            StateManager.updateStatus('error', '麦克风访问错误');
        }
    }

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
 * 事件处理类
 */
class EventManager {
    static initialize() {
        elements.startButton.addEventListener('click', SessionManager.startConversation);
        elements.stopButton.addEventListener('click', SessionManager.endConversation);
        elements.resetButton.addEventListener('click', SessionManager.resetConversation);

        document.addEventListener('click', () => {
            const audioContext = audioProcessor.getAudioContext();
            if (audioContext?.state === 'suspended') {
                audioContext.resume().catch(console.error);
            }
        });

        if (elements.messagesContainer) {
            elements.messagesContainer.addEventListener('scroll', () => {}, { passive: true });
        }

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
    websocketHandler.initializeWebSocket(StateManager.updateStatus, elements.startButton);
    EventManager.initialize();
}

// 启动应用
document.addEventListener('DOMContentLoaded', init); 