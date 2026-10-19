package io.github.typing233.superaide.core.router

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.sqrt

/**
 * 误差函数，照搬 CPython 的 math.erf（Modules/mathmodule.c：小于 1.5 用级数，否则用 erfc 的连分式）。
 * 路由的 90% / 70% 门槛就靠它，精度差了门槛附近会判反，所以不用常见的低精度近似。
 */
object Erf {
    private const val SERIES_CUTOFF = 1.5
    private const val SERIES_TERMS = 25
    private const val CONTFRAC_CUTOFF = 30.0
    private const val CONTFRAC_TERMS = 50
    private val SQRT_PI = sqrt(Math.PI)

    private fun series(x: Double): Double {
        val x2 = x * x
        var acc = 0.0
        var fk = SERIES_TERMS + 0.5
        repeat(SERIES_TERMS) {
            acc = 2.0 + x2 * acc / fk
            fk -= 1.0
        }
        return acc * x * exp(-x2) / SQRT_PI
    }

    private fun contfrac(x: Double): Double {
        if (x >= CONTFRAC_CUTOFF) return 0.0
        val x2 = x * x
        var a = 0.0
        var da = 0.5
        var p = 1.0
        var pLast = 0.0
        var q = da + x2
        var qLast = 1.0
        repeat(CONTFRAC_TERMS) {
            a += da
            da += 2.0
            val b = da + x2
            var temp = p
            p = b * p - a * pLast
            pLast = temp
            temp = q
            q = b * q - a * qLast
            qLast = temp
        }
        return p / q * x * exp(-x2) / SQRT_PI
    }

    fun erf(x: Double): Double {
        if (x.isNaN()) return x
        val ax = abs(x)
        if (ax < SERIES_CUTOFF) return series(x)
        val cf = contfrac(ax)
        return if (x > 0.0) 1.0 - cf else cf - 1.0
    }
}
