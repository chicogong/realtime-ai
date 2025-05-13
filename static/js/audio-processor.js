/**
 * 音频处理模块
 * 处理音频采集、播放和转换
 */

// 音频配置常量
const SAMPLE_RATE = 16000;
const CHANNELS = 1;
const BUFFER_SIZE = 4096;

// 音频相关变量
let audioContext = null;
let isPlayingAudio = false;
let currentAudioSource = null;
let audioBufferQueue = [];

// 音频处理器对象
const AudioProcessor = {
    // 导出配置常量
    SAMPLE_RATE,
    CHANNELS,
    BUFFER_SIZE,

    // 初始化音频上下文
    initAudioContext() {
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
    },

    // 获取音频上下文
    getAudioContext() {
        return audioContext;
    },

    // 停止音频播放
    stopAudioPlayback() {
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
    },

    // 是否正在播放
    isPlaying() {
        return isPlayingAudio;
    },

    // 播放音频数据
    async playAudio(audioData) {
        if (!this.initAudioContext() || !audioData || audioData.byteLength === 0) {
            return;
        }
        
        try {
            // 如果有正在播放的音频，加入队列
            if (isPlayingAudio && currentAudioSource) {
                audioBufferQueue.push(audioData);
                return;
            }
            
            // 转换PCM数据为AudioBuffer
            const audioBuffer = await this.pcmToAudioBuffer(audioData);
            if (!audioBuffer) return;
            
            // 创建音频源并播放
            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioContext.destination);
            
            // 保存当前音频源
            currentAudioSource = source;
            isPlayingAudio = true;
            
            // 添加播放结束事件
            source.onended = () => {
                currentAudioSource = null;
                isPlayingAudio = false;
                
                // 播放队列中的下一个
                if (audioBufferQueue.length > 0) {
                    const nextBuffer = audioBufferQueue.shift();
                    this.playAudio(nextBuffer);
                }
            };
            
            // 开始播放
            source.start(0);
        } catch (e) {
            console.error('播放音频错误:', e);
            isPlayingAudio = false;
            
            // 处理下一个音频
            if (audioBufferQueue.length > 0) {
                setTimeout(() => {
                    const nextBuffer = audioBufferQueue.shift();
                    this.playAudio(nextBuffer);
                }, 500);
            }
        }
    },

    // 将PCM数据转换为AudioBuffer
    async pcmToAudioBuffer(pcmData) {
        if (!this.initAudioContext() || !pcmData || pcmData.byteLength === 0) {
            return null;
        }
        
        try {
            // 获取采样率信息
            const contextRate = audioContext.sampleRate;
            const sourceRate = SAMPLE_RATE;
            const needsResampling = contextRate !== sourceRate;
            
            // 创建临时AudioBuffer
            const tempBuffer = audioContext.createBuffer(
                1,                      // 单声道
                pcmData.byteLength / 2, // 16位PCM，每样本2字节
                sourceRate              // 源采样率
            );
            
            // 获取通道数据
            const tempChannelData = tempBuffer.getChannelData(0);
            
            // 将PCM数据转换为Float32Array
            const dataView = new DataView(pcmData);
            for (let i = 0; i < tempChannelData.length; i++) {
                const int16Value = dataView.getInt16(i * 2, true);
                tempChannelData[i] = int16Value / 32768.0;
            }
            
            // 如果需要重采样
            if (needsResampling) {
                // 创建目标AudioBuffer
                const targetSampleCount = Math.round(tempChannelData.length * contextRate / sourceRate);
                const targetBuffer = audioContext.createBuffer(1, targetSampleCount, contextRate);
                const targetChannelData = targetBuffer.getChannelData(0);
                
                // 线性内插重采样
                for (let i = 0; i < targetSampleCount; i++) {
                    const sourcePos = i * sourceRate / contextRate;
                    const sourcePosFloor = Math.floor(sourcePos);
                    const fraction = sourcePos - sourcePosFloor;
                    
                    if (sourcePosFloor < tempChannelData.length - 1) {
                        const a = tempChannelData[sourcePosFloor];
                        const b = tempChannelData[sourcePosFloor + 1];
                        targetChannelData[i] = a + fraction * (b - a);
                    } else if (sourcePosFloor < tempChannelData.length) {
                        targetChannelData[i] = tempChannelData[sourcePosFloor];
                    }
                }
                
                return targetBuffer;
            }
            
            return tempBuffer;
        } catch (e) {
            console.error('PCM转换失败:', e);
            return null;
        }
    },

    // 重采样函数
    downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
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
    },

    // 从Float32转换为Int16 (PCM)
    convertFloat32ToInt16(buffer) {
        const l = buffer.length;
        const output = new Int16Array(l);
        
        for (let i = 0; i < l; i++) {
            // 限制在-1.0 - 1.0范围
            const s = Math.max(-1, Math.min(1, buffer[i]));
            // 转换为16位整数
            output[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        return output;
    },

    // 计算音频音量
    detectAudioLevel(buffer) {
        if (!buffer || buffer.length === 0) return 0;
        
        let sum = 0;
        for (let i = 0; i < buffer.length; i++) {
            sum += Math.abs(buffer[i]);
        }
        
        return sum / buffer.length;
    },

    // 处理二进制音频数据
    async handleBinaryAudioData(blob) {
        try {
            const arrayBuffer = await blob.arrayBuffer();
            
            // 跳过12字节的头部信息 (请求ID 4字节 + 块序号 4字节 + 时间戳 4字节)
            const headerSize = 12;
            if (arrayBuffer.byteLength <= headerSize) {
                console.warn('收到的音频数据过小，无法处理');
                return;
            }
            
            // 解析头部信息（可选，用于调试）
            const headerView = new DataView(arrayBuffer, 0, headerSize);
            const requestId = headerView.getUint32(0, true); // 小端序
            const chunkNumber = headerView.getUint32(4, true);
            const timestamp = headerView.getUint32(8, true);
            
            if (chunkNumber === 1) {
                console.log(`收到音频: 请求ID=${requestId}, 块=${chunkNumber}, 时间戳=${timestamp}`);
            }
            
            // 提取仅PCM音频数据
            const audioData = arrayBuffer.slice(headerSize);
            this.playAudio(audioData);
        } catch (e) {
            console.error('处理音频数据错误:', e);
        }
    }
};

// 导出AudioProcessor对象
window.AudioProcessor = AudioProcessor; 