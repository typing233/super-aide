import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// 版本号跟桌面版同一个来源：仓库根目录的 pyproject.toml（发版时 CI 可用 -PversionName 覆盖）
val appVersion: String = (findProperty("versionName") as String?)
    ?: Regex("""(?m)^version\s*=\s*"([^"]+)"""")
        .find(rootProject.file("../pyproject.toml").readText())!!.groupValues[1]
val appVersionCode: Int = appVersion.split(".").map { it.takeWhile(Char::isDigit).toInt() }
    .let { (major, minor, patch) -> major * 1_000_000 + minor * 1_000 + patch }

// 发布签名：CI 从 secrets 写出 keystore.properties；本地没有就用调试签名
val signing = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) file.inputStream().use(::load)
}

android {
    namespace = "io.github.typing233.superaide"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.github.typing233.superaide"
        minSdk = 30
        targetSdk = 37
        versionCode = appVersionCode
        versionName = appVersion
        // 截图认字（ML Kit）带原生库：只放手机用的 ARM 两种（x86 的模拟器、Chromebook 能转译 ARM），每种十来 MB
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }

    signingConfigs {
        if (signing.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(signing.getProperty("storeFile"))
                storePassword = signing.getProperty("storePassword")
                keyAlias = signing.getProperty("keyAlias")
                keyPassword = signing.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
        // 和 release 一样经过 R8 混淆压缩，但可调试、带调试命令：在手机上验证正式包的行为
        create("staging") {
            initWith(getByName("release"))
            applicationIdSuffix = ".staging"
            versionNameSuffix = "-staging"
            isDebuggable = true
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += "release"
        }
    }

    sourceSets.getByName("staging") {
        kotlin.directories += "src/debug/kotlin"
        manifest.srcFile("src/debug/AndroidManifest.xml")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "/META-INF/versions/9/OSGI-INF/MANIFEST.MF")
        // APK 是从 GitHub 下载装的：dex 和原生库都压缩存放，下载小一半多（安装时多解压一下）
        dex.useLegacyPackaging = true
        jniLibs.useLegacyPackaging = true
    }
}

dependencies {
    implementation(project(":core"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.savedstate)
    implementation(libs.kotlinx.coroutines.android)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.markdown.m3)
    // 截图认字（中文模型打包在 App 里，不联网、不要谷歌服务）：给不让无障碍读界面的 App（微信）用
    implementation(libs.mlkit.text.chinese)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
}
