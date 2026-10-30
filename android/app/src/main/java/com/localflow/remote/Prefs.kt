package com.localflow.remote

import android.content.Context
import android.content.SharedPreferences

/**
 * Plain SharedPreferences, not encrypted: the token only grants access over
 * an already-encrypted, device-authenticated Tailscale tunnel, and this data
 * is private to the app under normal Android sandboxing like any other app
 * setting -- not worth an extra dependency for this threat model.
 */
object Prefs {
    private const val FILE = "localflow_remote_prefs"
    private const val KEY_HOST = "host"
    private const val KEY_PORT = "port"
    private const val KEY_TOKEN = "token"

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun host(context: Context): String = prefs(context).getString(KEY_HOST, "") ?: ""
    fun port(context: Context): Int = prefs(context).getInt(KEY_PORT, 8765)
    fun token(context: Context): String = prefs(context).getString(KEY_TOKEN, "") ?: ""

    // orientation is "land" or "port" -- each remembers its own island spot
    fun islandX(context: Context, orientation: String, default: Int): Int =
        prefs(context).getInt("island_x_$orientation", default)
    fun islandY(context: Context, orientation: String, default: Int): Int =
        prefs(context).getInt("island_y_$orientation", default)

    fun islandScale(context: Context): Float = prefs(context).getFloat("island_scale", 1f)
    fun islandOpacity(context: Context): Float = prefs(context).getFloat("island_opacity", 1f)

    fun saveIslandAppearance(context: Context, scale: Float, opacity: Float) {
        prefs(context).edit().putFloat("island_scale", scale).putFloat("island_opacity", opacity).apply()
    }

    fun ghostText(context: Context): Boolean = prefs(context).getBoolean("ghost_text", false)
    fun saveGhostText(context: Context, on: Boolean) {
        prefs(context).edit().putBoolean("ghost_text", on).apply()
    }

    fun saveIslandPosition(context: Context, orientation: String, x: Int, y: Int) {
        prefs(context).edit()
            .putInt("island_x_$orientation", x)
            .putInt("island_y_$orientation", y)
            .apply()
    }

    fun save(context: Context, host: String, port: Int, token: String) {
        prefs(context).edit()
            .putString(KEY_HOST, host)
            .putInt(KEY_PORT, port)
            .putString(KEY_TOKEN, token)
            .apply()
    }
}
