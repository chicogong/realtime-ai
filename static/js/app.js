/**
 * 主应用脚本
 * 初始化和协调所有功能
 */

// 媒体和录音相关变量
let mediaStream = null;
let processor = null;
let isRecording = false;
let originalSampleRate = 0;
let resampleRequired = false;

// DOM元素
const startBtn = document.getElementById('start-btn');
const stopBtn = document.getElementById('stop-btn');
const resetBtn = document.getElementById('reset-btn');
const partialTranscript = document.getElementById('partial-transcript');
const messages = document.getElementById('messages');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

/**
 * 更新状态指示器
 * @param {string} state - 状态类型 (idle, listening, thinking, error)
 * @param {string} message - 状态消息
 */
function updateStatus(state, message) {
    statusDot.className = `status-dot ${state}`;
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
        
        // 创建音频上下文
        if (!window.AudioProcessor.initAudioContext()) {
            throw new Error('无法初始化音频上下文');
        }
        
        // 获取音频上下文
        const audioContext = getAudioContext();
        originalSampleRate = audioContext.sampleRate;
        
        // 检查是否需要重采样
        resampleRequired = originalSampleRate !== window.AudioProcessor.SAMPLE_RATE;
        console.log(`原始采样率: ${originalSampleRate}Hz, 目标采样率: ${window.AudioProcessor.SAMPLE_RATE}Hz, 需要重采样: ${resampleRequired}`);
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        
        // 创建处理节点
        processor = audioContext.createScriptProcessor(
            window.AudioProcessor.BUFFER_SIZE, 
            window.AudioProcessor.CHANNELS, 
            window.AudioProcessor.CHANNELS
        );
        
        processor.onaudioprocess = function(e) {
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
            
            // 发送到服务器
            if (window.WebSocketHandler.getSocket().readyState === WebSocket.OPEN) {
                window.WebSocketHandler.getSocket().send(pcmData.buffer);
            }
        };
        
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
        console.error('Error starting recording:', error);
        updateStatus('error', '麦克风访问错误');
    }
}

/**
 * 停止录音
 */
function stopRecording() {
    if (!isRecording) return;
    
    isRecording = false;
    
    // 停止媒体流
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    
    // 断开音频节点
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    
    // 不关闭音频上下文，以便继续播放TTS
    const audioContext = getAudioContext();
    if (audioContext && audioContext.state === "running" && !isAudioPlaying()) {
        audioContext.suspend().catch(console.error);
    }
    
    // 发送停止命令
    window.WebSocketHandler.sendCommand('stop');
    
    // 更新UI
    startBtn.disabled = false;
    stopBtn.disabled = true;
    updateStatus('idle', '已停止');
}

/**
 * 重置所有内容
 */
function resetSession() {
    // 停止录音（如果正在进行）
    if (isRecording) {
        stopRecording();
    }
    
    // 停止所有正在播放的音频
    window.AudioProcessor.stopAudioPlayback();
    
    // 清空显示
    partialTranscript.textContent = '';
    messages.innerHTML = '';
    
    // 发送重置命令
    window.WebSocketHandler.sendCommand('reset');
    
    updateStatus('idle', '已重置');
}

/**
 * 获取音频上下文的辅助函数
 */
function getAudioContext() {
    return window.AudioProcessor ? window.AudioProcessor.getAudioContext() : null;
}

/**
 * 检查是否正在播放音频的辅助函数
 */
function isAudioPlaying() {
    return window.AudioProcessor ? window.AudioProcessor.isPlaying() : false;
}

// 设置事件监听器
function setupEventListeners() {
    startBtn.addEventListener('click', startRecording);
    stopBtn.addEventListener('click', stopRecording);
    resetBtn.addEventListener('click', resetSession);
    
    // 单击文档时唤醒音频上下文
    document.addEventListener('click', function() {
        const audioContext = getAudioContext();
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume().catch(console.error);
        }
    });
    
    // 添加被动事件监听器以提高性能
    if (messages) {
        messages.addEventListener('scroll', function() {
            // 处理滚动事件
        }, { passive: true });
    }
    
    // 处理页面卸载
    window.addEventListener('beforeunload', () => {
        if (isRecording) {
            stopRecording();
        }
        
        const socket = window.WebSocketHandler.getSocket();
        if (socket) {
            socket.close();
        }
        
        const audioContext = getAudioContext();
        if (audioContext) {
            audioContext.close().catch(console.error);
        }
    });
}

// 初始化应用
function initApp() {
    // 初始化WebSocket连接
    window.WebSocketHandler.initializeWebSocket(updateStatus, startBtn);
    
    // 设置事件监听器
    setupEventListeners();
}

// 页面加载完成后初始化
window.addEventListener('load', initApp); 