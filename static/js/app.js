/**
 * 实时语音对话主控制模块
 */

import audioProcessor from './audio-processor.js';
import websocketHandler from './websocket-handler.js';

// 状态变量
let activeMediaStream = null;
let audioProcessor_node = null;
let isSessionActive = false;
let deviceSampleRate = 0;
let needsResampling = false;
let isInitialAudioBlock = true;

// DOM元素
const startButton = document.getElementById('start-btn');
const stopButton = document.getElementById('stop-btn');
const resetButton = document.getElementById('reset-btn');
const messagesContainer = document.getElementById('messages');
const statusIndicatorDot = document.getElementById('status-dot');
const statusIndicatorText = document.getElementById('status-text');

/**
 * 更新状态指示器
 */
function updateStatus(state, message) {
    statusIndicatorDot.className = state;
    statusIndicatorText.textContent = message;
}

/**
 * 开始语音对话
 */
async function startConversation() {
    try {
        activeMediaStream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            } 
        });
        
        if (!audioProcessor.initAudioContext()) {
            throw new Error('无法初始化音频上下文');
        }
        
        const audioContext = getAudioContext();
        deviceSampleRate = audioContext.sampleRate;
        needsResampling = deviceSampleRate !== audioProcessor.SAMPLE_RATE;
        
        const audioSource = audioContext.createMediaStreamSource(activeMediaStream);
        audioProcessor_node = audioContext.createScriptProcessor(
            audioProcessor.BUFFER_SIZE, 
            audioProcessor.CHANNELS, 
            audioProcessor.CHANNELS
        );
        
        audioProcessor_node.onaudioprocess = processUserSpeech;
        audioSource.connect(audioProcessor_node);
        audioProcessor_node.connect(audioContext.destination);
        
        isSessionActive = true;
        updateStatus('listening', '正在听取...');
        startButton.disabled = true;
        stopButton.disabled = false;
        
        websocketHandler.sendCommand('start');
    } catch (error) {
        console.error('麦克风访问错误:', error);
        updateStatus('error', '麦克风访问错误');
    }
}

/**
 * 处理用户语音输入
 */
function processUserSpeech(event) {
    if (!isSessionActive || !websocketHandler.getSocket() || 
        websocketHandler.getSocket().readyState !== WebSocket.OPEN) return;
    
    const microphoneData = event.inputBuffer.getChannelData(0);
    websocketHandler.checkVoiceInterruption(microphoneData);
    
    let audioToProcess = microphoneData;
    if (needsResampling) {
        audioToProcess = audioProcessor.downsampleBuffer(
            microphoneData, deviceSampleRate, audioProcessor.SAMPLE_RATE
        );
    }
    
    const pcmAudioData = audioProcessor.convertFloat32ToInt16(audioToProcess);
    
    // 使用WebSocketHandler发送音频数据
    websocketHandler.sendAudioData(pcmAudioData, isInitialAudioBlock);
    
    // 重置首块标志
    if (isInitialAudioBlock) {
        isInitialAudioBlock = false;
    }
}

/**
 * 结束语音对话
 */
function endConversation() {
    if (!isSessionActive) return;
    
    isSessionActive = false;
    isInitialAudioBlock = true;
    
    if (activeMediaStream) {
        activeMediaStream.getTracks().forEach(track => track.stop());
    }
    
    if (audioProcessor_node) {
        audioProcessor_node.disconnect();
        audioProcessor_node = null;
    }
    
    audioProcessor.stopAudioPlayback();
    
    const audioContext = getAudioContext();
    if (audioContext && audioContext.state === "running" && !isAudioPlaying()) {
        audioContext.suspend().catch(console.error);
    }
    
    websocketHandler.sendStopAndClearQueues();
    
    startButton.disabled = false;
    stopButton.disabled = true;
    updateStatus('idle', '已停止');
}

/**
 * 重置对话
 */
function resetConversation() {
    if (isSessionActive) {
        endConversation();
    }
    
    audioProcessor.stopAudioPlayback();
    messagesContainer.innerHTML = '';
    isInitialAudioBlock = true;
    websocketHandler.sendCommand('reset');
    updateStatus('idle', '已重置');
}

/**
 * 获取音频上下文
 */
function getAudioContext() {
    return audioProcessor ? audioProcessor.getAudioContext() : null;
}

/**
 * 检查是否正在播放音频
 */
function isAudioPlaying() {
    return audioProcessor ? audioProcessor.isPlaying() : false;
}

/**
 * 初始化应用
 */
function init() {
    websocketHandler.initializeWebSocket(updateStatus, startButton);
    
    startButton.addEventListener('click', startConversation);
    stopButton.addEventListener('click', endConversation);
    resetButton.addEventListener('click', resetConversation);
    
    document.addEventListener('click', () => {
        const audioContext = getAudioContext();
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume().catch(console.error);
        }
    });
    
    // 添加被动事件监听器以提高性能
    if (messagesContainer) {
        messagesContainer.addEventListener('scroll', () => {}, { passive: true });
    }
    
    // 处理页面卸载
    window.addEventListener('beforeunload', () => {
        if (isSessionActive) endConversation();
        
        const socket = websocketHandler.getSocket();
        if (socket) socket.close();
        
        const audioContext = getAudioContext();
        if (audioContext) audioContext.close().catch(console.error);
    });
}

// 启动应用
document.addEventListener('DOMContentLoaded', init); 