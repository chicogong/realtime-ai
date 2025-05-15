/**
 * 实时语音对话主控制模块
 */

import audioProcessor from './audio-processor.js';
import websocketHandler from './websocket-handler.js';

// 状态变量
let mediaStream = null;
let audioScriptProcessor = null;
let isConversationActive = false;
let originalSampleRate = 0;
let resampleRequired = false;
let isFirstAudioBlock = true;

// DOM元素
const startBtn = document.getElementById('start-btn');
const stopBtn = document.getElementById('stop-btn');
const resetBtn = document.getElementById('reset-btn');
const messages = document.getElementById('messages');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

/**
 * 更新状态指示器
 */
function updateStatus(state, message) {
    statusDot.className = state;
    statusText.textContent = message;
}

/**
 * 开始语音对话
 */
async function startConversation() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
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
        originalSampleRate = audioContext.sampleRate;
        resampleRequired = originalSampleRate !== audioProcessor.SAMPLE_RATE;
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        audioScriptProcessor = audioContext.createScriptProcessor(
            audioProcessor.BUFFER_SIZE, 
            audioProcessor.CHANNELS, 
            audioProcessor.CHANNELS
        );
        
        audioScriptProcessor.onaudioprocess = processUserSpeech;
        source.connect(audioScriptProcessor);
        audioScriptProcessor.connect(audioContext.destination);
        
        isConversationActive = true;
        updateStatus('listening', '正在听取...');
        startBtn.disabled = true;
        stopBtn.disabled = false;
        
        websocketHandler.sendCommand('start');
    } catch (error) {
        console.error('麦克风访问错误:', error);
        updateStatus('error', '麦克风访问错误');
    }
}

/**
 * 处理用户语音输入
 */
function processUserSpeech(e) {
    if (!isConversationActive || !websocketHandler.getSocket() || 
        websocketHandler.getSocket().readyState !== WebSocket.OPEN) return;
    
    const inputData = e.inputBuffer.getChannelData(0);
    websocketHandler.checkVoiceInterruption(inputData);
    
    let audioToProcess = inputData;
    if (resampleRequired) {
        audioToProcess = audioProcessor.downsampleBuffer(
            inputData, originalSampleRate, audioProcessor.SAMPLE_RATE
        );
    }
    
    const pcmData = audioProcessor.convertFloat32ToInt16(audioToProcess);
    
    // 使用WebSocketHandler发送音频数据
    websocketHandler.sendAudioData(pcmData, isFirstAudioBlock);
    
    // 重置首块标志
    if (isFirstAudioBlock) {
        isFirstAudioBlock = false;
    }
}

/**
 * 结束语音对话
 */
function endConversation() {
    if (!isConversationActive) return;
    
    isConversationActive = false;
    isFirstAudioBlock = true;
    
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    
    if (audioScriptProcessor) {
        audioScriptProcessor.disconnect();
        audioScriptProcessor = null;
    }
    
    audioProcessor.stopAudioPlayback();
    
    const audioContext = getAudioContext();
    if (audioContext && audioContext.state === "running" && !isAudioPlaying()) {
        audioContext.suspend().catch(console.error);
    }
    
    websocketHandler.sendStopAndClearQueues();
    
    startBtn.disabled = false;
    stopBtn.disabled = true;
    updateStatus('idle', '已停止');
}

/**
 * 重置对话
 */
function resetConversation() {
    if (isConversationActive) {
        endConversation();
    }
    
    audioProcessor.stopAudioPlayback();
    messages.innerHTML = '';
    isFirstAudioBlock = true;
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
    websocketHandler.initializeWebSocket(updateStatus, startBtn);
    
    startBtn.addEventListener('click', startConversation);
    stopBtn.addEventListener('click', endConversation);
    resetBtn.addEventListener('click', resetConversation);
    
    document.addEventListener('click', () => {
        const audioContext = getAudioContext();
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume().catch(console.error);
        }
    });
    
    // 添加被动事件监听器以提高性能
    if (messages) {
        messages.addEventListener('scroll', () => {}, { passive: true });
    }
    
    // 处理页面卸载
    window.addEventListener('beforeunload', () => {
        if (isConversationActive) endConversation();
        
        const socket = websocketHandler.getSocket();
        if (socket) socket.close();
        
        const audioContext = getAudioContext();
        if (audioContext) audioContext.close().catch(console.error);
    });
}

// 启动应用
document.addEventListener('DOMContentLoaded', init); 