package io.github.typing233.superaide.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.core.agent.Mode

/** 设计变量，和桌面版 ui/web/style.css 的 :root 一致（只有 surface 几乎不透明：手机上没有毛玻璃，底下的字会透上来）。 */
@Immutable
data class Tokens(
    val surface: Color,
    val stroke: Color,
    val divider: Color,
    val text: Color,
    val text2: Color,
    val text3: Color,
    val hover: Color,
    val inlineCode: Color,
    val codeBg: Color,
    val codeText: Color,
    val dark: Boolean,
) {
    val askA = Color(0xFF5B8CFF)
    val askB = Color(0xFF9B6BFF)
    val actA = Color(0xFFFFB547)
    val actB = Color(0xFFFF7A45)
    val ok = Color(0xFF3CCB7F)
    val err = Color(0xFFFF5D5D)

    fun accent(mode: Mode) = if (mode == Mode.ACT) actB else askA
    fun gradient(mode: Mode) = if (mode == Mode.ACT) Brush.linearGradient(listOf(actA, actB)) else Brush.linearGradient(listOf(askA, askB))
}

private val Light = Tokens(
    surface = Color(0xFCFFFFFF), stroke = Color(0x14000000), divider = Color(0x0F000000),
    text = Color(0xE0000000), text2 = Color(0x8F000000), text3 = Color(0x5C000000),
    hover = Color(0x0D000000), inlineCode = Color(0x0E000000), codeBg = Color(0xFF1E2127), codeText = Color(0xFFE6E8EC),
    dark = false,
)
private val Dark = Tokens(
    surface = Color(0xFA1E1E20), stroke = Color(0x17FFFFFF), divider = Color(0x12FFFFFF),
    text = Color(0xEBFFFFFF), text2 = Color(0x94FFFFFF), text3 = Color(0x61FFFFFF),
    hover = Color(0x12FFFFFF), inlineCode = Color(0x14FFFFFF), codeBg = Color(0xFF141518), codeText = Color(0xFFE6E8EC),
    dark = true,
)

object Radius {
    val input = 14.dp
    val card = 16.dp
    val pill = 20.dp
    val code = 10.dp
}

val LocalTokens = staticCompositionLocalOf { Light }

@Composable
fun AideTheme(content: @Composable () -> Unit) {
    val dark = when (AideApp.instance.settings.value.theme) {
        "light" -> false
        "dark" -> true
        else -> isSystemInDarkTheme()
    }
    val t = if (dark) Dark else Light
    val scheme = if (dark) darkColorScheme(primary = t.askA, onSurface = t.text) else lightColorScheme(primary = t.askA, onSurface = t.text)
    CompositionLocalProvider(LocalTokens provides t) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
