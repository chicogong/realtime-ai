/**
 * 主应用脚本
 */

// 状态变量
let mediaStream = null;
let processor = null;
let isRecording = false;
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
 * 开始录音
 */
async function startRecording() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            } 
        });
        
        if (!window.AudioProcessor.initAudioContext()) {
            throw new Error('无法初始化音频上下文');
        }
        
        const audioContext = getAudioContext();
        originalSampleRate = audioContext.sampleRate;
        resampleRequired = originalSampleRate !== window.AudioProcessor.SAMPLE_RATE;
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(
            window.AudioProcessor.BUFFER_SIZE, 
            window.AudioProcessor.CHANNELS, 
            window.AudioProcessor.CHANNELS
        );
        
        processor.onaudioprocess = processAudio;
        source.connect(processor);
        processor.connect(audioContext.destination);
        
        isRecording = true;
        updateStatus('listening', '正在听取...');
        startBtn.disabled = true;
        stopBtn.disabled = false;
        
        window.WebSocketHandler.sendCommand('start');
    } catch (error) {
        console.error('麦克风访问错误:', error);
        updateStatus('error', '麦克风访问错误');
    }
}

/**
 * 处理音频数据
 */
function processAudio(e) {
    if (!isRecording || !window.WebSocketHandler.getSocket() || 
        window.WebSocketHandler.getSocket().readyState !== WebSocket.OPEN) return;
    
    const inputData = e.inputBuffer.getChannelData(0);
    window.WebSocketHandler.checkVoiceInterruption(inputData);
    
    let audioToProcess = inputData;
    if (resampleRequired) {
        audioToProcess = window.AudioProcessor.downsampleBuffer(
            inputData, originalSampleRate, window.AudioProcessor.SAMPLE_RATE
        );
    }
    
    const pcmData = window.AudioProcessor.convertFloat32ToInt16(audioToProcess);
    
    // 创建带头部的数据缓冲区 [4字节时间戳][4字节状态标志]
    const headerSize = 8;
    const combinedBuffer = new ArrayBuffer(headerSize + pcmData.byteLength);
    const headerView = new DataView(combinedBuffer, 0, headerSize);
    
    // 设置时间戳 (毫秒)
    headerView.setUint32(0, Date.now(), true);
    
    // 设置状态标志
    let statusFlags = 0;
    const energy = Math.min(255, Math.floor(window.AudioProcessor.detectAudioLevel(inputData) * 1000));
    statusFlags |= energy & 0xFF;
    
    if (inputData.every(sample => Math.abs(sample) < 0.01)) {
        statusFlags |= (1 << 8);
    }
    
    if (isFirstAudioBlock) {
        statusFlags |= (1 << 9);
        isFirstAudioBlock = false;
    }
    
    headerView.setUint32(4, statusFlags, true);
    new Uint8Array(combinedBuffer, headerSize).set(new Uint8Array(pcmData.buffer));
    
    if (window.WebSocketHandler.getSocket().readyState === WebSocket.OPEN) {
        window.WebSocketHandler.getSocket().send(combinedBuffer);
    }
}

/**
 * 停止录音
 */
function stopRecording() {
    if (!isRecording) return;
    
    isRecording = false;
    isFirstAudioBlock = true;
    
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    
    window.AudioProcessor.stopAudioPlayback();
    
    const audioContext = getAudioContext();
    if (audioContext && audioContext.state === "running" && !isAudioPlaying()) {
        audioContext.suspend().catch(console.error);
    }
    
    window.WebSocketHandler.sendStopAndClearQueues();
    
    startBtn.disabled = false;
    stopBtn.disabled = true;
    updateStatus('idle', '已停止');
}

/**
 * 重置会话
 */
function resetSession() {
    if (isRecording) {
        stopRecording();
    }
    
    window.AudioProcessor.stopAudioPlayback();
    messages.innerHTML = '';
    isFirstAudioBlock = true;
    window.WebSocketHandler.sendCommand('reset');
    updateStatus('idle', '已重置');
}

/**
 * 获取音频上下文
 */
function getAudioContext() {
    return window.AudioProcessor ? window.AudioProcessor.getAudioContext() : null;
}

/**
 * 检查是否正在播放音频
 */
function isAudioPlaying() {
    return window.AudioProcessor ? window.AudioProcessor.isPlaying() : false;
}

/**
 * 初始化应用
 */
function init() {
    window.WebSocketHandler.initializeWebSocket(updateStatus, startBtn);
    
    startBtn.addEventListener('click', startRecording);
    stopBtn.addEventListener('click', stopRecording);
    resetBtn.addEventListener('click', resetSession);
    
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
        if (isRecording) stopRecording();
        
        const socket = window.WebSocketHandler.getSocket();
        if (socket) socket.close();
        
        const audioContext = getAudioContext();
        if (audioContext) audioContext.close().catch(console.error);
    });
}

// 启动应用
document.addEventListener('DOMContentLoaded', init); 