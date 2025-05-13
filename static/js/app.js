/**
 * 主应用脚本
 */

// 音频处理配置和状态
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
        // 请求麦克风访问权限
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            } 
        });
        
        // 初始化音频处理
        if (!window.AudioProcessor.initAudioContext()) {
            throw new Error('无法初始化音频上下文');
        }
        
        const audioContext = getAudioContext();
        originalSampleRate = audioContext.sampleRate;
        
        // 检查是否需要重采样
        resampleRequired = originalSampleRate !== window.AudioProcessor.SAMPLE_RATE;
        console.log(`原始采样率: ${originalSampleRate}Hz, 目标采样率: ${window.AudioProcessor.SAMPLE_RATE}Hz`);
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        
        // 创建处理节点
        processor = audioContext.createScriptProcessor(
            window.AudioProcessor.BUFFER_SIZE, 
            window.AudioProcessor.CHANNELS, 
            window.AudioProcessor.CHANNELS
        );
        
        processor.onaudioprocess = processAudio;
        
        // 连接音频节点
        source.connect(processor);
        processor.connect(audioContext.destination);
        
        isRecording = true;
        updateStatus('listening', '正在听取...');
        
        // 更新UI
        startBtn.disabled = true;
        stopBtn.disabled = false;
        
        // 发送开始命令
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
    
    // 获取音频数据
    const inputData = e.inputBuffer.getChannelData(0);
    
    // 检测用户是否在AI响应时开始说话
    window.WebSocketHandler.checkVoiceInterruption(inputData);
    
    // 根据需要重采样
    let audioToProcess = inputData;
    if (resampleRequired) {
        audioToProcess = window.AudioProcessor.downsampleBuffer(
            inputData, 
            originalSampleRate, 
            window.AudioProcessor.SAMPLE_RATE
        );
    }
    
    // 转换为16位PCM
    const pcmData = window.AudioProcessor.convertFloat32ToInt16(audioToProcess);
    
    // 创建带头部的数据缓冲区
    // 头部格式: [4字节时间戳][4字节状态标志]
    const headerSize = 8; // 8字节头部
    const combinedBuffer = new ArrayBuffer(headerSize + pcmData.byteLength);
    const headerView = new DataView(combinedBuffer, 0, headerSize);
    
    // 设置时间戳 (毫秒)
    const timestamp = Date.now();
    headerView.setUint32(0, timestamp, true); // 小端序
    
    // 设置状态标志
    let statusFlags = 0;
    
    // 计算音频能量 (0-255)
    const energy = Math.min(255, Math.floor(window.AudioProcessor.detectAudioLevel(inputData) * 1000));
    statusFlags |= energy & 0xFF; // 使用低8位存储能量值
    
    // 可以设置其他标志位
    // 麦克风静音状态 (位 8)
    if (inputData.every(sample => Math.abs(sample) < 0.01)) {
        statusFlags |= (1 << 8); // 静音标志
    }
    
    // 首个音频块标记 (位 9)
    // 这是一个示例，实际应用中需要跟踪首个块
    if (isFirstAudioBlock) {
        statusFlags |= (1 << 9);
        isFirstAudioBlock = false;
    }
    
    // 可以在这里设置其他标志位
    
    // 写入状态标志
    headerView.setUint32(4, statusFlags, true); // 小端序
    
    // 拷贝PCM数据
    new Uint8Array(combinedBuffer, headerSize).set(new Uint8Array(pcmData.buffer));
    
    // 发送带头部的数据
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
    
    // 重置首个音频块标志，下次开始时是第一个
    isFirstAudioBlock = true;
    
    // 停止媒体流
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    
    // 断开音频节点
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    
    // 停止所有正在播放的音频
    window.AudioProcessor.stopAudioPlayback();
    
    // 暂停音频上下文（如果没有音频播放）
    const audioContext = getAudioContext();
    if (audioContext && audioContext.state === "running" && !isAudioPlaying()) {
        audioContext.suspend().catch(console.error);
    }
    
    // 发送停止并清空队列命令
    window.WebSocketHandler.sendStopAndClearQueues();
    
    // 更新UI
    startBtn.disabled = false;
    stopBtn.disabled = true;
    updateStatus('idle', '已停止');
}

/**
 * 重置会话
 */
function resetSession() {
    // 停止录音（如果正在进行）
    if (isRecording) {
        stopRecording();
    }
    
    // 停止所有正在播放的音频
    window.AudioProcessor.stopAudioPlayback();
    
    // 清空消息
    messages.innerHTML = '';
    
    // 重置首个音频块标志
    isFirstAudioBlock = true;
    
    // 发送重置命令
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
    // 初始化WebSocket
    window.WebSocketHandler.initializeWebSocket(updateStatus, startBtn);
    
    // 设置事件监听
    startBtn.addEventListener('click', startRecording);
    stopBtn.addEventListener('click', stopRecording);
    resetBtn.addEventListener('click', resetSession);
    
    // 点击唤醒音频上下文
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

// 页面加载完成后初始化
window.addEventListener('load', init); 