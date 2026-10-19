package io.github.typing233.superaide.core.router

import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Wire
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.math.abs
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * 和桌面版 Python 实现逐条比对（数据由 scripts/android/gen_fixtures.py 用桌面版代码算出来）。
 * 浮点允许 1e-12 的误差（erf 的实现不同：Python 可能用系统的 libm）。
 */
class RouterParityTest {
    private val data: JsonObject = Json.parseToJsonElement(
        javaClass.getResourceAsStream("/parity/router.json")!!.bufferedReader(Charsets.UTF_8).readText()
    ).jsonObject

    private fun close(expected: Double, actual: Double, what: String, tol: Double = 1e-12) =
        assertTrue(abs(expected - actual) <= tol, "$what：期望 $expected，实际 $actual")

    private fun effort(s: String) = Effort.entries.first { it.wire == s }

    private fun scored(o: JsonObject): Scored {
        val p = Profile(o.s("engine"), Wire.ANTHROPIC, o.s("model"), o.i("tier"), Effort.entries, 0.8, 1.0 to 1.0, o.i("order"))
        return Scored(p, effort(o.s("effort")), o.d("alpha"), o.d("beta"), o.d("real"), o.d("cost"), o.d("prior"))
    }

    @Test fun erf() {
        for (row in data["erf"]!!.jsonArray) {
            val (x, y) = row.jsonArray.map { it.jsonPrimitive.double }
            close(y, Erf.erf(x), "erf($x)")
        }
    }

    @Test fun noninferiorAndSuperior() {
        for (p in data["pairs"]!!.jsonArray.map { it.jsonObject }) {
            val c = scored(p["c"]!!.jsonObject)
            val r = scored(p["r"]!!.jsonObject)
            close(p.d("mean"), c.mean, "mean")
            close(p.d("var"), c.variance, "var")
            close(p.d("noninferior"), Router.noninferior(c, r), "noninferior")
            close(p.d("superior"), Router.superior(c, r), "superior")
        }
    }

    @Test fun transferTable() {
        for (t in data["transfer"]!!.jsonArray.map { it.jsonObject }) {
            val k = Evidence.transfer(t.s("o_engine"), t.s("o_model"), t.i("o_eidx"), t["ok"]!!.jsonPrimitive.boolean, t.i("o_tier"),
                t.s("engine"), t.s("model"), t.i("tier"), t.i("eidx"))
            assertEquals(t.d("k"), k, t.toString())
        }
    }

    @Test fun evidenceGatherAndCounts() {
        val e = data["evidence"]!!.jsonObject
        val now = e.d("now")
        val ev = Evidence(null)
        for (o in e["outcomes"]!!.jsonArray.map { it.jsonObject }) {
            ev.items += Outcome(o.d("t"), o.s("mode"), o.s("kind"), o.s("domain"), o.s("engine"), o.s("model"), o.s("effort"),
                o.d("y"), o.d("w"), o.s("source"))
        }
        val tiers = e["tiers"]!!.jsonObject.mapValues { it.value.jsonPrimitive.int }
        val cache = mutableMapOf<Triple<String, String, String>, Map<Cell, DoubleArray>>()
        for (c in e["counts"]!!.jsonArray.map { it.jsonObject }) {
            val buckets = cache.getOrPut(Triple(c.s("mode"), c.s("kind"), c.s("domain"))) { ev.gather(c.s("mode"), c.s("kind"), c.s("domain"), now) }
            val (s, f) = Evidence.counts(buckets, c.s("engine"), c.s("model"), tiers.getValue(c.s("model")), c.i("eidx")) { _, m -> tiers.getValue(m) }
            close(c.d("s"), s, "s $c", 1e-9)
            close(c.d("f"), f, "f $c", 1e-9)
        }
    }

    @Test fun referenceAndDowngrade() {
        for (p in data["picks"]!!.jsonArray.map { it.jsonObject }) {
            val cands = p["candidates"]!!.jsonArray.map { scored(it.jsonObject) }
            val pk = Router.pickFrom(cands)
            assertEquals(p.i("default"), cands.indexOf(pk.default), "default $p")
            assertEquals(p.i("ref"), cands.indexOf(pk.ref), "ref $p")
            assertEquals(p.i("chosen"), cands.indexOf(pk.chosen), "chosen $p")
            close(p.d("confidence"), pk.confidence, "confidence")
        }
    }

    @Test fun judgeParse() {
        for (j in data["judge"]!!.jsonArray.map { it.jsonObject }) {
            val v = Judge.parse(j.s("text"), j["flip"]!!.jsonPrimitive.boolean)
            val want = j["verdict"]
            if (want is JsonNull) assertEquals(null, v, j.toString())
            else assertEquals(want!!.jsonArray.map { it.jsonPrimitive.double }, listOf(v!!.candidate, v.served), j.toString())
        }
    }

    @Test fun catalog() {
        for (c in data["catalog"]!!.jsonArray.map { it.jsonObject }) {
            val id = c.s("id")
            assertEquals(c.i("tier"), Catalog.tierOf(id), id)
            val v = c["version"]
            if (v is JsonArray) {
                val (line, version) = Catalog.claudeVersion(id)!!
                assertEquals(v[0].jsonPrimitive.content, line, id)
                close(v[1].jsonPrimitive.double, version, id)
            } else assertEquals(null, Catalog.claudeVersion(id), id)
            assertEquals(c["efforts"]!!.jsonArray.map { it.jsonPrimitive.content }, Catalog.claudeEfforts(id).map { it.wire }, id)
        }
    }

    @Test fun report() {
        val r = data["report"]!!.jsonObject
        val records = r["records"]!!.jsonArray.map { it.jsonObject }
        val (tasks, duels) = Report.tasksAndDuels(records)
        val now = r.d("now")
        val window = Report.WINDOW_DAYS * 86400.0
        val got = mapOf("current" to Report.period(tasks, duels, now - window, now + 1),
            "previous" to Report.period(tasks, duels, now - 2 * window, now - window))
        for ((name, p) in got) {
            val want = r["periods"]!!.jsonObject[name]!!.jsonObject
            assertEquals(want.i("tasks"), p.tasks, "$name tasks")
            assertEquals(want.i("problems"), p.problems, "$name problems")
            assertEquals(want.i("downgraded"), p.downgraded, "$name downgraded")
            assertEquals(want.i("duels"), p.duels, "$name duels")
            assertEquals(want.i("duels_as_good"), p.duelsAsGood, "$name duels_as_good")
            for ((k, v) in listOf("problem_rate" to p.problemRate, "saving" to p.saving, "down_problem_rate" to p.downProblemRate,
                "ref_problem_rate" to p.refProblemRate)) {
                val w = want[k]
                if (w is JsonNull) assertEquals(null, v, "$name $k") else close(w!!.jsonPrimitive.double, v!!, "$name $k")
            }
        }
        assertEquals(r.s("verdict"), Report.verdict(got.getValue("current")))
    }

    private fun JsonObject.s(k: String) = this[k]!!.jsonPrimitive.content
    private fun JsonObject.i(k: String) = this[k]!!.jsonPrimitive.int
    private fun JsonObject.d(k: String) = this[k]!!.jsonPrimitive.double
}
