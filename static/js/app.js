/**
 * 实时语音对话主控制模块
 */

import audioProcessor from './audio-processor.js';
import websocketHandler from './websocket-handler.js';

// 状态变量
let activeMediaStream = null;
let audioProcessorNode = null;
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
 * @param {string} state - 状态类名
 * @param {string} message - 状态消息
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
        // 获取麦克风访问权限
        activeMediaStream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            } 
        });
        
        // 初始化音频上下文
        if (!audioProcessor.initAudioContext()) {
            throw new Error('无法初始化音频上下文');
        }
        
        // 设置音频处理
        const audioContext = getAudioContext();
        deviceSampleRate = audioContext.sampleRate;
        needsResampling = deviceSampleRate !== audioProcessor.SAMPLE_RATE;
        
        const audioSource = audioContext.createMediaStreamSource(activeMediaStream);
        audioProcessorNode = audioContext.createScriptProcessor(
            audioProcessor.BUFFER_SIZE, 
            audioProcessor.CHANNELS, 
            audioProcessor.CHANNELS
        );
        
        // 设置音频处理回调
        audioProcessorNode.onaudioprocess = processUserSpeech;
        audioSource.connect(audioProcessorNode);
        audioProcessorNode.connect(audioContext.destination);
        
        // 更新状态
        isSessionActive = true;
        updateStatus('listening', '正在听取...');
        startButton.disabled = true;
        stopButton.disabled = false;
        
        // 通知服务器开始会话
        websocketHandler.sendCommand('start');
    } catch (error) {
        console.error('麦克风访问错误:', error);
        updateStatus('error', '麦克风访问错误');
    }
}

/**
 * 处理用户语音输入
 * @param {AudioProcessingEvent} event - 音频处理事件
 */
function processUserSpeech(event) {
    // 检查会话和连接状态
    if (!isSessionActive || !websocketHandler.getSocket() || 
        websocketHandler.getSocket().readyState !== WebSocket.OPEN) return;
    
    // 获取麦克风数据
    const microphoneData = event.inputBuffer.getChannelData(0);
    
    // 检查是否需要中断AI响应
    websocketHandler.checkVoiceInterruption(microphoneData);
    
    // 处理采样率转换
    let audioToProcess = microphoneData;
    if (needsResampling) {
        audioToProcess = audioProcessor.downsampleBuffer(
            microphoneData, deviceSampleRate, audioProcessor.SAMPLE_RATE
        );
    }
    
    // 转换为PCM格式
    const pcmAudioData = audioProcessor.convertFloat32ToInt16(audioToProcess);
    
    // 发送音频数据
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
    
    // 重置状态
    isSessionActive = false;
    isInitialAudioBlock = true;
    
    // 停止音频播放
    audioProcessor.stopAudioPlayback();
    
    // 关闭麦克风
    if (activeMediaStream) {
        activeMediaStream.getTracks().forEach(track => track.stop());
    }
    
    // 断开音频处理节点
    if (audioProcessorNode) {
        audioProcessorNode.disconnect();
        audioProcessorNode = null;
    }
    
    // 暂停音频上下文
    const audioContext = getAudioContext();
    if (audioContext && audioContext.state === "running" && !isAudioPlaying()) {
        audioContext.suspend().catch(console.error);
    }
    
    // 通知服务器停止会话
    websocketHandler.sendStopAndClearQueues();
    
    // 更新UI状态
    startButton.disabled = false;
    stopButton.disabled = true;
    updateStatus('idle', '已停止');
}

/**
 * 重置对话
 */
function resetConversation() {
    // 如果会话活跃，先结束会话
    if (isSessionActive) {
        endConversation();
    }
    
    // 停止所有音频播放
    audioProcessor.stopAudioPlayback();
    
    // 清空消息容器
    messagesContainer.innerHTML = '';
    
    // 重置状态
    isInitialAudioBlock = true;
    
    // 通知服务器重置
    websocketHandler.sendCommand('reset');
    updateStatus('idle', '已重置');
}

/**
 * 获取音频上下文
 * @returns {AudioContext|null}
 */
function getAudioContext() {
    return audioProcessor ? audioProcessor.getAudioContext() : null;
}

/**
 * 检查是否正在播放音频
 * @returns {boolean}
 */
function isAudioPlaying() {
    return audioProcessor ? audioProcessor.isPlaying() : false;
}

/**
 * 初始化应用
 */
function init() {
    // 初始化WebSocket连接
    websocketHandler.initializeWebSocket(updateStatus, startButton);
    
    // 绑定按钮事件
    startButton.addEventListener('click', startConversation);
    stopButton.addEventListener('click', endConversation);
    resetButton.addEventListener('click', resetConversation);
    
    // 添加点击事件以恢复音频上下文
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