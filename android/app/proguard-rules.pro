# kotlinx.serialization：保留生成的序列化器
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class io.github.typing233.superaide.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class io.github.typing233.superaide.**$$serializer { *; }

# anthropic-java 自带 R8 规则（META-INF/proguard）；Jackson 的可选依赖在安卓上没有
-dontwarn com.fasterxml.jackson.databind.ext.**
-dontwarn java.beans.**
-dontwarn org.slf4j.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
-dontwarn com.google.auto.value.**

# anthropic-java 用 Jackson + Kotlin 反射解析响应：R8 去掉类或 Kotlin 元数据后会报
# "Unresolved class: Usage$ServiceTier"，流读完了却解析不了（2026-10-19 在手机上的 staging 包里遇到）
-keepattributes Signature, RuntimeVisibleAnnotations, AnnotationDefault, EnclosingMethod
-keep class kotlin.Metadata { *; }
-keep class com.anthropic.core.** { *; }
-keep class com.anthropic.errors.** { *; }
-keep class com.anthropic.models.messages.* { *; }
-keep class com.fasterxml.jackson.module.kotlin.** { *; }
# 全保留后，SDK 里结构化输出（StructuredOutputs、victools 生成 JSON Schema）引用的反射类型安卓上没有；我们不用这部分
-dontwarn java.lang.reflect.AnnotatedType
-dontwarn java.lang.reflect.AnnotatedParameterizedType
-dontwarn com.github.victools.**

# ML Kit 截图认字：识别器和原生识别管线靠反射、JNI 按名字找类和方法（组件注册类的构造函数、bundled 管线的回调），
# R8 删改以后建识别器时 NullPointerException（2026-10-20 在手机上的 staging 包里遇到）：整个保留
-keep class com.google.mlkit.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_text_bundled_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_text_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_common.** { *; }
-keep class * implements com.google.firebase.components.ComponentRegistrar { <init>(); *; }
