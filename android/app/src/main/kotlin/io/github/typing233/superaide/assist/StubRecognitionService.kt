package io.github.typing233.superaide.assist

import android.content.Intent
import android.speech.RecognitionService
import android.speech.SpeechRecognizer

/** 占位：系统要求默认助手带一个语音识别服务才让选。我们不做语音识别（输入法自带语音输入）。 */
class StubRecognitionService : RecognitionService() {
    override fun onStartListening(recognizerIntent: Intent?, listener: Callback?) {
        runCatching { listener?.error(SpeechRecognizer.ERROR_CLIENT) }
    }

    override fun onCancel(listener: Callback?) {}

    override fun onStopListening(listener: Callback?) {}
}
