package com.localflow.remote

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Talks to the LocalFlow remote-dictation server (server.py in the main
 * repo) over the Tailscale tailnet. All calls here are blocking -- always
 * invoke from a background thread.
 */
object ApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val PCM = "application/octet-stream".toMediaType()

    // live preview should never queue up behind a slow request
    private val previewClient = client.newBuilder()
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    private fun baseUrl(host: String, port: Int) = "http://$host:$port"

    fun health(host: String, port: Int, token: String): Result<Boolean> = try {
        val req = Request.Builder()
            .url("${baseUrl(host, port)}/v1/health")
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (resp.isSuccessful) Result.success(true)
            else Result.failure(IOException("HTTP ${resp.code}"))
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    /**
     * Sends raw little-endian 16-bit mono PCM @ 16kHz -- exactly what the
     * Mac's Transcriber expects, so the server does zero resampling.
     */
    fun transcribe(host: String, port: Int, token: String, pcm: ByteArray): Result<String> = try {
        val req = Request.Builder()
            .url("${baseUrl(host, port)}/v1/transcribe")
            .header("Authorization", "Bearer $token")
            .post(pcm.toRequestBody(PCM))
            .build()
        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (resp.isSuccessful) {
                Result.success(JSONObject(body).optString("text", ""))
            } else {
                Result.failure(IOException("HTTP ${resp.code}: $body"))
            }
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** Rough live transcript of the audio so far (speech model only, no cleanup). */
    fun preview(host: String, port: Int, token: String, pcm: ByteArray): Result<String> = try {
        val req = Request.Builder()
            .url("${baseUrl(host, port)}/v1/preview")
            .header("Authorization", "Bearer $token")
            .post(pcm.toRequestBody(PCM))
            .build()
        previewClient.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (resp.isSuccessful) Result.success(JSONObject(body).optString("text", ""))
            else Result.failure(IOException("HTTP ${resp.code}"))
        }
    } catch (e: Exception) {
        Result.failure(e)
    }
}
