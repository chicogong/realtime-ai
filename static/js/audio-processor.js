/**
 * 音频处理模块
 * 处理音频采集、播放和转换
 */

// 音频配置常量
const SAMPLE_RATE = 16000;
const SAMPLE_SIZE = 16;
const CHANNELS = 1;
const BUFFER_SIZE = 4096;

// 音频相关变量 - 仅保留此模块专用的变量
let audioContext = null;
// 移除 mediaStream 和 processor，由app.js管理
let isPlayingAudio = false;
let currentAudioSource = null;
let audioBufferQueue = [];
// 移除 originalSampleRate 和 resampleRequired，由app.js管理

/**
 * 初始化音频上下文
 * @returns {boolean} - 是否成功初始化
 */
function initAudioContext() {
    if (!audioContext) {
        try {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            console.log(`音频上下文已初始化，采样率: ${audioContext.sampleRate}Hz`);
            return true;
        } catch (e) {
            console.error('初始化音频上下文失败:', e);
            return false;
        }
    } else if (audioContext.state === "suspended") {
        audioContext.resume().catch(console.error);
    }
    return true;
}

/**
 * 停止当前音频播放
 */
function stopAudioPlayback() {
    if (currentAudioSource) {
        try {
            currentAudioSource.stop();
            currentAudioSource = null;
        } catch (e) {
            console.error('停止音频错误:', e);
        }
    }
    isPlayingAudio = false;
    audioBufferQueue = [];
}

/**
 * 播放音频数据
 * @param {ArrayBuffer} audioData - PCM音频数据
 */
function playAudio(audioData) {
    if (!initAudioContext()) {
        console.error('无法初始化音频上下文');
        return;
    }
    
    try {
        if (!audioData || audioData.byteLength === 0) {
            console.warn('收到空音频数据');
            return;
        }
        
        console.log(`播放音频数据: ${audioData.byteLength} 字节`);
        
        // 如果有正在播放的音频，加入队列
        if (isPlayingAudio && currentAudioSource) {
            audioBufferQueue.push(audioData);
            console.log(`音频已加入队列，当前队列长度: ${audioBufferQueue.length}`);
            return;
        }
        
        // 创建音频缓冲区
        pcmToAudioBuffer(audioData).then(audioBuffer => {
            if (!audioBuffer) {
                console.error('创建音频缓冲区失败');
                return;
            }
            
            // 创建音频源
            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            
            // 直接连接到输出
            source.connect(audioContext.destination);
            
            // 保存当前音频源
            currentAudioSource = source;
            isPlayingAudio = true;
            
            // 添加播放结束事件处理
            source.onended = () => {
                console.log('音频播放结束');
                currentAudioSource = null;
                isPlayingAudio = false;
                
                // 播放队列中的下一个
                if (audioBufferQueue.length > 0) {
                    const nextBuffer = audioBufferQueue.shift();
                    playAudio(nextBuffer);
                }
            };
            
            // 开始播放
            source.start(0);
            console.log('开始播放音频');
        }).catch(err => {
            console.error('创建或播放音频缓冲区时出错:', err);
            isPlayingAudio = false;
            
            // 尝试处理下一个音频
            if (audioBufferQueue.length > 0) {
                const nextBuffer = audioBufferQueue.shift();
                playAudio(nextBuffer);
            }
        });
    } catch (e) {
        console.error('播放音频错误:', e);
        isPlayingAudio = false;
        
        // 错误处理后尝试播放下一个
        if (audioBufferQueue.length > 0) {
            setTimeout(() => {
                const nextBuffer = audioBufferQueue.shift();
                playAudio(nextBuffer);
            }, 500);
        }
    }
}

/**
 * 将PCM数据转换为AudioBuffer
 * @param {ArrayBuffer} pcmData - PCM音频数据
 * @returns {Promise<AudioBuffer>} - 转换后的AudioBuffer
 */
async function pcmToAudioBuffer(pcmData) {
    if (!initAudioContext()) {
        return null;
    }
    
    try {
        // 检查PCM数据是否有效
        if (!pcmData || pcmData.byteLength === 0) {
            console.warn('PCM数据无效');
            return null;
        }
        
        // 获取实际上下文采样率，可能需要重采样
        const contextRate = audioContext.sampleRate;
        const sourceRate = 16000; // Azure TTS是16kHz
        const needsResampling = contextRate !== sourceRate;
        
        // 创建临时AudioBuffer用于初始PCM数据
        const tempBuffer = audioContext.createBuffer(
            1,                        // 单声道
            pcmData.byteLength / 2,   // 16位=2字节每样本，所以字节数/2=样本数
            sourceRate                // 源采样率16kHz
        );
        
        // 获取音频通道数据
        const tempChannelData = tempBuffer.getChannelData(0);
        
        // 将PCM数据转换为Float32Array，确保处理小端字节序
        const dataView = new DataView(pcmData);
        for (let i = 0; i < tempChannelData.length; i++) {
            // 使用getInt16显式指定小端字节序(true)，避免字节序问题
            const int16Value = dataView.getInt16(i * 2, true);
            // 16位PCM范围是-32768到32767，转换到-1.0到1.0
            tempChannelData[i] = int16Value / 32768.0;
        }
        
        // 如果需要重采样
        if (needsResampling) {
            console.log(`重采样从 ${sourceRate}Hz 到 ${contextRate}Hz`);
            
            // 创建目标AudioBuffer
            const targetSampleCount = Math.round(tempChannelData.length * contextRate / sourceRate);
            const targetBuffer = audioContext.createBuffer(1, targetSampleCount, contextRate);
            const targetChannelData = targetBuffer.getChannelData(0);
            
            // 简单线性内插重采样
            for (let i = 0; i < targetSampleCount; i++) {
                const sourcePos = i * sourceRate / contextRate;
                const sourcePosFloor = Math.floor(sourcePos);
                const fraction = sourcePos - sourcePosFloor;
                
                // 确保不越界
                if (sourcePosFloor < tempChannelData.length - 1) {
                    const a = tempChannelData[sourcePosFloor];
                    const b = tempChannelData[sourcePosFloor + 1];
                    // 线性插值
                    targetChannelData[i] = a + fraction * (b - a);
                } else if (sourcePosFloor < tempChannelData.length) {
                    targetChannelData[i] = tempChannelData[sourcePosFloor];
                }
            }
            
            return targetBuffer;
        }
        
        // 如果不需要重采样，直接返回原始buffer
        return tempBuffer;
    } catch (e) {
        console.error('PCM转换失败:', e);
        return null;
    }
}

/**
 * 重采样函数
 * @param {Float32Array} buffer - 输入音频数据
 * @param {number} inputSampleRate - 输入采样率
 * @param {number} outputSampleRate - 输出采样率
 * @returns {Float32Array} - 重采样后的数据
 */
function downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
    if (inputSampleRate === outputSampleRate) {
        return buffer;
    }
    
    const sampleRateRatio = inputSampleRate / outputSampleRate;
    const newLength = Math.round(buffer.length / sampleRateRatio);
    const result = new Float32Array(newLength);
    
    let offsetResult = 0;
    let offsetBuffer = 0;
    
    while (offsetResult < result.length) {
        const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
        let accum = 0, count = 0;
        
        for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
            accum += buffer[i];
            count++;
        }
        
        result[offsetResult] = accum / count;
        offsetResult++;
        offsetBuffer = nextOffsetBuffer;
    }
    
    return result;
}

/**
 * 从Float32转换为Int16 (PCM)
 * @param {Float32Array} buffer - 浮点数据
 * @returns {Int16Array} - 16位PCM数据
 */
function convertFloat32ToInt16(buffer) {
    const l = buffer.length;
    const buf = new Int16Array(l);
    
    for (let i = 0; i < l; i++) {
        const s = Math.max(-1, Math.min(1, buffer[i]));
        buf[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    return buf;
}

/**
 * 检测音频电平
 * @param {Float32Array} audioBuffer - 音频数据
 * @returns {number} - 音频电平 (0-1)
 */
function detectAudioLevel(audioBuffer) {
    let sum = 0;
    for (let i = 0; i < audioBuffer.length; i++) {
        sum += Math.abs(audioBuffer[i]);
    }
    return sum / audioBuffer.length;
}

/**
 * 处理二进制音频数据
 * @param {Blob} blob - 二进制音频数据
 */
async function handleBinaryAudioData(blob) {
    try {
        // 确保音频上下文已初始化
        initAudioContext();
        
        // 解析二进制数据
        const arrayBuffer = await blob.arrayBuffer();
        
        // 检查数据大小
        if (arrayBuffer.byteLength < 12) {
            console.error('收到的二进制数据太小，无法解析头部');
            return;
        }
        
        // 解析头部信息
        // 格式: [4字节请求ID][4字节块序号][4字节时间戳][PCM数据]
        const headerView = new DataView(arrayBuffer, 0, 12);
        const requestId = headerView.getUint32(0, true);  // 使用小端字节序
        const chunkNumber = headerView.getUint32(4, true);
        const timestamp = headerView.getUint32(8, true);
        
        // 提取PCM数据
        const pcmData = arrayBuffer.slice(12);
        
        // 打印日志
        console.log(`处理音频块: ID=${requestId}, 块号=${chunkNumber}, 时间戳=${timestamp}, PCM大小=${pcmData.byteLength}字节`);
        
        // 播放PCM数据
        playAudio(pcmData);
    } catch (e) {
        console.error('处理二进制音频数据出错:', e);
    }
}

// 导出功能
window.AudioProcessor = {
    initAudioContext,
    handleBinaryAudioData,
    stopAudioPlayback,
    playAudio,
    downsampleBuffer,
    convertFloat32ToInt16,
    detectAudioLevel,
    pcmToAudioBuffer,
    SAMPLE_RATE,
    SAMPLE_SIZE,
    CHANNELS,
    BUFFER_SIZE,
    getAudioContext: () => audioContext,
    isPlaying: () => isPlayingAudio
}; 