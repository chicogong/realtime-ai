/**
 * 音频处理模块
 * 处理音频采集、播放和转换
 */

// 音频配置常量
const TARGET_SAMPLE_RATE = 16000;
const AUDIO_CHANNELS = 1;
const PROCESSING_BUFFER_SIZE = 4096;

// 音频相关变量
let audioContext = null;
let isPlayingAudio = false;
let currentAudioSource = null;
let pendingAudioQueue = [];

// 音频处理器对象
const audioProcessor = {
    // 导出配置常量
    SAMPLE_RATE: TARGET_SAMPLE_RATE,
    CHANNELS: AUDIO_CHANNELS,
    BUFFER_SIZE: PROCESSING_BUFFER_SIZE,

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
        pendingAudioQueue = [];
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
                pendingAudioQueue.push(audioData);
                return;
            }
            
            // 转换PCM数据为AudioBuffer
            const audioBuffer = await this.pcmToAudioBuffer(audioData);
            if (!audioBuffer) return;
            
            // 创建音频源并播放
            const audioSource = audioContext.createBufferSource();
            audioSource.buffer = audioBuffer;
            audioSource.connect(audioContext.destination);
            
            // 保存当前音频源
            currentAudioSource = audioSource;
            isPlayingAudio = true;
            
            // 添加播放结束事件
            audioSource.onended = () => {
                currentAudioSource = null;
                
                // 播放队列中的下一个，使用微小延迟避免衔接问题
                // 只有在isPlayingAudio为true时才继续播放队列中的下一项
                if (isPlayingAudio && pendingAudioQueue.length > 0) {
                    setTimeout(() => {
                        if (isPlayingAudio && pendingAudioQueue.length > 0) {
                            const nextBuffer = pendingAudioQueue.shift();
                            this.playAudio(nextBuffer);
                        }
                    }, 5);  // 5ms延迟，足够短但有助于音频平滑衔接
                } else {
                    isPlayingAudio = false;
                }
            };
            
            // 开始播放
            audioSource.start(0);
        } catch (e) {
            console.error('播放音频错误:', e);
            isPlayingAudio = false;
            
            // 处理下一个音频
            if (pendingAudioQueue.length > 0) {
                setTimeout(() => {
                    const nextBuffer = pendingAudioQueue.shift();
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
            const deviceSampleRate = audioContext.sampleRate;
            const targetSampleRate = TARGET_SAMPLE_RATE; // 16000Hz
            const needsResampling = deviceSampleRate !== targetSampleRate;
            
            console.log(`PCM转换: 原始采样率=${targetSampleRate}Hz, 目标采样率=${deviceSampleRate}Hz, 数据大小=${pcmData.byteLength}字节, 需要重采样=${needsResampling}, 样本数=${pcmData.byteLength/2}`);
            
            // 创建临时AudioBuffer
            const sampleCount = pcmData.byteLength / 2;  // 16位PCM，每样本2字节
            const tempBuffer = audioContext.createBuffer(
                1,                  // 单声道
                sampleCount,        // 样本数量
                targetSampleRate    // 源采样率
            );
            
            // 获取通道数据
            const channelData = tempBuffer.getChannelData(0);
            
            // 将PCM数据转换为Float32Array
            const dataView = new DataView(pcmData);
            let maxAmplitude = 0;
            let minAmplitude = 0;
            
            for (let i = 0; i < sampleCount; i++) {
                try {
                    // 使用小端序，因为服务器使用小端序（true）
                    const int16Value = dataView.getInt16(i * 2, true);
                    // 标准化到 -1.0 到 1.0 范围
                    const normalizedValue = int16Value / 32768.0;
                    channelData[i] = normalizedValue;
                    
                    // 跟踪音频电平
                    maxAmplitude = Math.max(maxAmplitude, normalizedValue);
                    minAmplitude = Math.min(minAmplitude, normalizedValue);
                } catch (e) {
                    console.error(`PCM数据处理错误，索引: ${i}, 总长度: ${pcmData.byteLength}`, e);
                    break;
                }
            }
            
            console.log(`PCM数据解析完成: 最大振幅=${maxAmplitude.toFixed(4)}, 最小振幅=${minAmplitude.toFixed(4)}`);
            
            // 如果需要重采样
            if (needsResampling) {
                console.log(`执行PCM重采样: ${targetSampleRate}Hz -> ${deviceSampleRate}Hz, 样本数: ${sampleCount} -> 约${Math.round(sampleCount * deviceSampleRate / targetSampleRate)}`);
                
                // 创建OfflineAudioContext做重采样
                const offlineContext = new OfflineAudioContext(1, Math.ceil(channelData.length * deviceSampleRate / targetSampleRate), deviceSampleRate);
                
                // 创建BufferSource
                const bufferSource = offlineContext.createBufferSource();
                bufferSource.buffer = tempBuffer;
                bufferSource.connect(offlineContext.destination);
                bufferSource.start();
                
                // 执行重采样
                try {
                    console.time('重采样耗时');
                    const resampledBuffer = await offlineContext.startRendering();
                    console.timeEnd('重采样耗时');
                    console.log(`重采样完成: 新样本数=${resampledBuffer.length}, 持续时间=${resampledBuffer.duration.toFixed(2)}秒`);
                    return resampledBuffer;
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
        const resultBuffer = new Float32Array(newLength);
        
        let resultIndex = 0;
        let inputIndex = 0;
        
        while (resultIndex < resultBuffer.length) {
            const nextInputIndex = Math.round((resultIndex + 1) * sampleRateRatio);
            let accumulator = 0, count = 0;
            
            for (let i = inputIndex; i < nextInputIndex && i < buffer.length; i++) {
                accumulator += buffer[i];
                count++;
            }
            
            resultBuffer[resultIndex] = accumulator / count;
            resultIndex++;
            inputIndex = nextInputIndex;
        }
        
        return resultBuffer;
    },

    // 从Float32转换为Int16 (PCM)
    convertFloat32ToInt16(buffer) {
        const bufferLength = buffer.length;
        const outputBuffer = new Int16Array(bufferLength);
        
        for (let i = 0; i < bufferLength; i++) {
            // 限制在-1.0 - 1.0范围
            const sample = Math.max(-1, Math.min(1, buffer[i]));
            // 转换为16位整数
            outputBuffer[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }
        
        return outputBuffer;
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

// 使用ES模块导出
export default audioProcessor; 