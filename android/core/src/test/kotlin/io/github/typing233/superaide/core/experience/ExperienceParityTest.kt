package io.github.typing233.superaide.core.experience

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.io.File
import kotlin.io.path.createTempDirectory
import kotlin.test.assertEquals

/** 经验库和桌面版逐条比对（scripts/android/gen_fixtures.py 用桌面版代码算的）。 */
class ExperienceParityTest {
    private val data: JsonObject = Json.parseToJsonElement(
        javaClass.getResourceAsStream("/parity/router.json")!!.bufferedReader(Charsets.UTF_8).readText()
    ).jsonObject["experience"]!!.jsonObject

    @Test fun tokensCompactAndErrorLines() {
        for (t in data["tokens"]!!.jsonArray.map { it.jsonObject }) {
            val text = t["text"]!!.jsonPrimitive.content
            assertEquals(t["tokens"]!!.jsonArray.map { it.jsonPrimitive.content }, Recall.tokens(text), text)
            assertEquals(t["compact"]!!.jsonPrimitive.content, Recall.compact(text), text)
            assertEquals(t["errors"]!!.jsonPrimitive.content, Recall.errorLines(text), text)
        }
    }

    @Test fun recallPicksTheSameLessons() {
        val dir = createTempDirectory("lessons").toFile()
        val file = File(dir, "lessons.json")
        file.writeText(Json.encodeToString(JsonObject.serializer(), JsonObject(mapOf("version" to Json.parseToJsonElement("1"), "lessons" to data["lessons"]!!))))
        val store = Store(file)
        for (r in data["recall"]!!.jsonArray.map { it.jsonObject }) {
            val s = r["situation"]!!.jsonObject
            fun f(k: String) = s[k]?.jsonPrimitive?.contentOrNull.orEmpty()
            val got = Recall.recall(store, Situation(f("question"), f("text"), f("errors"), f("app"), f("url"), f("title"))).map { it.id }
            assertEquals(r["ids"]!!.jsonArray.map { it.jsonPrimitive.content }, got, s.toString())
        }
        dir.deleteRecursively()
    }
}
