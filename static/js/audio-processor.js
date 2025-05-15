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
window.AudioProcessor = {
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
                
                // 播放队列中的下一个，使用微小延迟避免衔接问题
                // 只有在isPlayingAudio为true时才继续播放队列中的下一项
                if (isPlayingAudio && audioBufferQueue.length > 0) {
                    setTimeout(() => {
                        if (isPlayingAudio && audioBufferQueue.length > 0) {
                            const nextBuffer = audioBufferQueue.shift();
                            this.playAudio(nextBuffer);
                        }
                    }, 5);  // 5ms延迟，足够短但有助于音频平滑衔接
                } else {
                    isPlayingAudio = false;
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
                }, 50);  // 增加错误恢复延迟
            }
        }
    },

    // 将PCM数据转换为AudioBuffer
    async pcmToAudioBuffer(pcmData) {
        if (!this.initAudioContext() || !pcmData || pcmData.byteLength === 0) {
            console.warn('无效的PCM数据或音频上下文未初始化');
            return null;
        }
        
        console.log(`开始PCM转换: 数据大小=${pcmData.byteLength}字节`);
        
        try {
            // 检查是否为有效的PCM数据大小（必须是偶数字节）
            if (pcmData.byteLength % 2 !== 0) {
                console.warn(`PCM数据大小不正确（非偶数字节）: ${pcmData.byteLength}字节`);
                // 截断为偶数字节
                pcmData = pcmData.slice(0, pcmData.byteLength - 1);
                console.log(`调整后PCM数据大小: ${pcmData.byteLength}字节`);
                if (pcmData.byteLength === 0) {
                    console.error('调整后PCM数据为空');
                    return null;
                }
            }
            
            // 获取采样率信息
            const contextRate = audioContext.sampleRate;
            const sourceRate = SAMPLE_RATE; // 16000Hz
            const needsResampling = contextRate !== sourceRate;
            
            console.log(`PCM转换: 原始采样率=${sourceRate}Hz, 目标采样率=${contextRate}Hz, 数据大小=${pcmData.byteLength}字节, 需要重采样=${needsResampling}, 样本数=${pcmData.byteLength/2}`);
            
            // 创建临时AudioBuffer
            const sampleCount = pcmData.byteLength / 2;  // 16位PCM，每样本2字节
            const tempBuffer = audioContext.createBuffer(
                1,                  // 单声道
                sampleCount,        // 样本数量
                sourceRate          // 源采样率
            );
            
            // 获取通道数据
            const tempChannelData = tempBuffer.getChannelData(0);
            
            // 将PCM数据转换为Float32Array
            const dataView = new DataView(pcmData);
            let maxAmp = 0;
            let minAmp = 0;
            
            for (let i = 0; i < sampleCount; i++) {
                try {
                    // 使用小端序，因为服务器使用小端序（true）
                    const int16Value = dataView.getInt16(i * 2, true);
                    // 标准化到 -1.0 到 1.0 范围
                    const normVal = int16Value / 32768.0;
                    tempChannelData[i] = normVal;
                    
                    // 跟踪音频电平
                    maxAmp = Math.max(maxAmp, normVal);
                    minAmp = Math.min(minAmp, normVal);
                } catch (e) {
                    console.error(`PCM数据处理错误，索引: ${i}, 总长度: ${pcmData.byteLength}`, e);
                    break;
                }
            }
            
            console.log(`PCM数据解析完成: 最大振幅=${maxAmp.toFixed(4)}, 最小振幅=${minAmp.toFixed(4)}`);
            
            // 如果需要重采样
            if (needsResampling) {
                console.log(`执行PCM重采样: ${sourceRate}Hz -> ${contextRate}Hz, 样本数: ${sampleCount} -> 约${Math.round(sampleCount * contextRate / sourceRate)}`);
                
                // 创建OfflineAudioContext做重采样
                const offlineContext = new OfflineAudioContext(1, Math.ceil(tempChannelData.length * contextRate / sourceRate), contextRate);
                
                // 创建BufferSource
                const source = offlineContext.createBufferSource();
                source.buffer = tempBuffer;
                source.connect(offlineContext.destination);
                source.start();
                
                // 执行重采样
                try {
                    console.time('重采样耗时');
                    const renderedBuffer = await offlineContext.startRendering();
                    console.timeEnd('重采样耗时');
                    console.log(`重采样完成: 新样本数=${renderedBuffer.length}, 持续时间=${renderedBuffer.duration.toFixed(2)}秒`);
                    return renderedBuffer;
                } catch (e) {
                    console.error('重采样失败, 使用原始缓冲区', e);
                    return tempBuffer;
                }
            }
            
            console.log(`PCM转换完成: 样本数=${tempBuffer.length}, 持续时间=${tempBuffer.duration.toFixed(2)}秒`);
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
}; 