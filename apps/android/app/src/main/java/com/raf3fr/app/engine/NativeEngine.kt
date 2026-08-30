package com.raf3fr.app.engine

object NativeEngine {
    init {
        System.loadLibrary("raf3fr_jni")
    }

    @JvmStatic
    external fun convert(
        source: String,
        donor: String,
        output: String,
        optionsJson: String,
        jobId: String,
    ): String

    @JvmStatic
    external fun cancel(jobId: String): Boolean

    @JvmStatic
    external fun verify(donor: String, candidate: String, source: String): String
}
