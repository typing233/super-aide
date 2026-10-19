package io.github.typing233.superaide.secure

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** API key 等秘密：用 Android Keystore 里的 AES-GCM 密钥加密后存成文件，明文不落盘。 */
class SecretStore(context: Context) {
    private val dir = File(context.filesDir, "secrets").apply { mkdirs() }

    fun put(name: String, value: String) {
        val cipher = Cipher.getInstance(TRANSFORM).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        File(dir, safe(name)).writeBytes(sealed)
    }

    fun get(name: String): String? {
        val f = File(dir, safe(name))
        if (!f.exists()) return null
        return runCatching {
            val bytes = f.readBytes()
            val cipher = Cipher.getInstance(TRANSFORM)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_LEN))
            String(cipher.doFinal(bytes, IV_LEN, bytes.size - IV_LEN), Charsets.UTF_8)
        }.getOrNull()
    }

    fun remove(name: String) {
        File(dir, safe(name)).delete()
    }

    private fun safe(name: String) = name.replace(Regex("[^A-Za-z0-9_.-]"), "_")

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    companion object {
        private const val ALIAS = "super-aide-secrets"
        private const val TRANSFORM = "AES/GCM/NoPadding"
        private const val IV_LEN = 12

        fun serviceKey(serviceId: String) = "service-$serviceId"
    }
}
