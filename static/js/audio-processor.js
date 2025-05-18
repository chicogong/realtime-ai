/**
 * 音频处理模块
 * 处理音频采集、播放和转换
 * @module audio-processor
 */

// 音频配置常量
const AUDIO_CONFIG = {
    TARGET_SAMPLE_RATE: 16000,
    CHANNELS: 1,
    BUFFER_SIZE: 4096,
    PCM_BITS_PER_SAMPLE: 16,
    PCM_BYTES_PER_SAMPLE: 2,
    PCM_MAX_VALUE: 32768.0,
    PCM_MIN_VALUE: -32768.0
};

// 音频相关状态
const audioState = {
    context: null,
    isPlaying: false,
    currentSource: null,
    pendingQueue: []
};

/**
 * 音频处理器对象
 * @type {Object}
 */
const audioProcessor = {
    // 公开配置常量
    SAMPLE_RATE: AUDIO_CONFIG.TARGET_SAMPLE_RATE,
    CHANNELS: AUDIO_CONFIG.CHANNELS,
    BUFFER_SIZE: AUDIO_CONFIG.BUFFER_SIZE,

    /**
     * 初始化音频上下文
     * @returns {boolean} 初始化是否成功
     */
    initAudioContext() {
        if (!audioState.context) {
            try {
                audioState.context = new (window.AudioContext || window.webkitAudioContext)();
                console.log(`音频上下文已初始化，采样率: ${audioState.context.sampleRate}Hz`);
                return true;
            } catch (error) {
                console.error('初始化音频上下文失败:', error);
                return false;
            }
        } else if (audioState.context.state === "suspended") {
            audioState.context.resume().catch(console.error);
        }
        return true;
    },

    /**
     * 获取音频上下文
     * @returns {AudioContext|null} 音频上下文实例
     */
    getAudioContext() {
        return audioState.context;
    },

    /**
     * 停止音频播放
     */
    stopAudioPlayback() {
        if (audioState.currentSource) {
            try {
                audioState.currentSource.stop();
                audioState.currentSource = null;
            } catch (error) {
                console.error('停止音频错误:', error);
            }
        }
        audioState.isPlaying = false;
        audioState.pendingQueue = [];
    },

    /**
     * 检查是否正在播放音频
     * @returns {boolean} 是否正在播放
     */
    isPlaying() {
        return audioState.isPlaying;
    },

    /**
     * 播放音频数据
     * @param {ArrayBuffer} audioData - 要播放的PCM音频数据
     * @returns {Promise<void>}
     */
    async playAudio(audioData) {
        if (!this.initAudioContext() || !audioData || audioData.byteLength === 0) {
            return;
        }
        
        try {
            // 如果有正在播放的音频，加入队列
            if (audioState.isPlaying && audioState.currentSource) {
                audioState.pendingQueue.push(audioData);
                return;
            }
            
            // 转换PCM数据为AudioBuffer
            const audioBuffer = await this.pcmToAudioBuffer(audioData);
            if (!audioBuffer) return;
            
            // 创建音频源并播放
            const audioSource = audioState.context.createBufferSource();
            audioSource.buffer = audioBuffer;
            audioSource.connect(audioState.context.destination);
            
            // 保存当前音频源和状态
            audioState.currentSource = audioSource;
            audioState.isPlaying = true;
            
            // 添加播放结束事件
            audioSource.onended = () => {
                audioState.currentSource = null;
                
                // 播放队列中的下一个，使用短延迟避免衔接问题
                if (audioState.isPlaying && audioState.pendingQueue.length > 0) {
                    setTimeout(() => {
                        if (audioState.isPlaying && audioState.pendingQueue.length > 0) {
                            const nextBuffer = audioState.pendingQueue.shift();
                            this.playAudio(nextBuffer);
                        }
                    }, 5);  // 5ms延迟，有助于音频平滑衔接
                } else {
                    audioState.isPlaying = false;
                }
            };
            
            // 开始播放
            audioSource.start(0);
        } catch (error) {
            console.error('播放音频错误:', error);
            audioState.isPlaying = false;
            
            // 处理队列中的下一个音频
            if (audioState.pendingQueue.length > 0) {
                setTimeout(() => {
                    const nextBuffer = audioState.pendingQueue.shift();
                    this.playAudio(nextBuffer);
                }, 50);  // 错误恢复延迟
            }
        }
    },

    /**
     * 将PCM数据转换为AudioBuffer
     * @param {ArrayBuffer} pcmData - PCM音频数据
     * @returns {Promise<AudioBuffer|null>} 转换后的AudioBuffer
     */
    async pcmToAudioBuffer(pcmData) {
        if (!this.initAudioContext() || !pcmData || pcmData.byteLength === 0) {
            console.warn('无效的PCM数据或音频上下文未初始化');
            return null;
        }
        
        try {
            // 检查是否为有效的PCM数据大小（必须是偶数字节）
            if (pcmData.byteLength % AUDIO_CONFIG.PCM_BYTES_PER_SAMPLE !== 0) {
                // 截断为偶数字节
                pcmData = pcmData.slice(0, pcmData.byteLength - 1);
                if (pcmData.byteLength === 0) {
                    return null;
                }
            }
            
            // 获取采样率信息
            const deviceSampleRate = audioState.context.sampleRate;
            const needsResampling = deviceSampleRate !== AUDIO_CONFIG.TARGET_SAMPLE_RATE;
            
            // 创建临时AudioBuffer
            const sampleCount = pcmData.byteLength / AUDIO_CONFIG.PCM_BYTES_PER_SAMPLE;
            const tempBuffer = audioState.context.createBuffer(
                AUDIO_CONFIG.CHANNELS,
                sampleCount,
                AUDIO_CONFIG.TARGET_SAMPLE_RATE
            );
            
            // 获取通道数据并将PCM转换为Float32Array
            const channelData = tempBuffer.getChannelData(0);
            const dataView = new DataView(pcmData);
            
            for (let i = 0; i < sampleCount; i++) {
                try {
                    // 使用小端序，因为服务器使用小端序（true）
                    const int16Value = dataView.getInt16(i * AUDIO_CONFIG.PCM_BYTES_PER_SAMPLE, true);
                    // 标准化到 -1.0 到 1.0 范围
                    channelData[i] = int16Value / AUDIO_CONFIG.PCM_MAX_VALUE;
                } catch (error) {
                    console.error(`PCM数据处理错误，索引: ${i}`, error);
                    break;
                }
            }
            
            // 如果需要重采样
            if (needsResampling) {
                return await this.resampleAudioBuffer(tempBuffer, deviceSampleRate);
            }
            
            return tempBuffer;
        } catch (error) {
            console.error('PCM转换失败:', error);
            return null;
        }
    },

    /**
     * 重采样音频缓冲区
     * @param {AudioBuffer} buffer - 原始音频缓冲区
     * @param {number} deviceSampleRate - 设备采样率
     * @returns {Promise<AudioBuffer>} 重采样后的音频缓冲区
     */
    async resampleAudioBuffer(buffer, deviceSampleRate) {
        try {
            // 创建OfflineAudioContext做重采样
            const offlineContext = new OfflineAudioContext(
                AUDIO_CONFIG.CHANNELS,
                Math.ceil(buffer.length * deviceSampleRate / AUDIO_CONFIG.TARGET_SAMPLE_RATE),
                deviceSampleRate
            );
            
            // 创建BufferSource
            const bufferSource = offlineContext.createBufferSource();
            bufferSource.buffer = buffer;
            bufferSource.connect(offlineContext.destination);
            bufferSource.start();
            
            // 执行重采样
            return await offlineContext.startRendering();
        } catch (error) {
            console.error('重采样失败, 使用原始缓冲区', error);
            return buffer;
        }
    },

    /**
     * 重采样函数
     * @param {Float32Array} buffer - 输入缓冲区
     * @param {number} inputSampleRate - 输入采样率
     * @param {number} outputSampleRate - 输出采样率
     * @returns {Float32Array} 重采样后的缓冲区
     */
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

    /**
     * 从Float32转换为Int16 (PCM)
     * @param {Float32Array} buffer - 输入缓冲区
     * @returns {Int16Array} 转换后的PCM数据
     */
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

    /**
     * 计算音频音量
     * @param {Float32Array} buffer - 音频缓冲区
     * @returns {number} 音量级别 (0-1)
     */
    detectAudioLevel(buffer) {
        if (!buffer || buffer.length === 0) return 0;
        
        let sum = 0;
        for (let i = 0; i < buffer.length; i++) {
            sum += Math.abs(buffer[i]);
        }
        
        return sum / buffer.length;
    }
};

// 使用ES模块导出
export default audioProcessor; 