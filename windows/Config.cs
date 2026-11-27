using System;
using System.IO;
using System.Text.Json;

namespace LocalFlowRemote
{
    /// <summary>Settings, in %APPDATA%\LocalFlow\config.json.</summary>
    internal sealed class Config
    {
        /// <summary>The Mac's Tailscale IP or MagicDNS name.</summary>
        public string Host { get; set; } = "";
        public int Port { get; set; } = 8765;
        /// <summary>The pairing token from the Mac's LocalFlow Settings.</summary>
        public string Token { get; set; } = "";
        /// <summary>LeftAlt, RightAlt or RightCtrl.</summary>
        public string Hotkey { get; set; } = "LeftAlt";
        /// <summary>hold_or_lock (hold to talk, double-tap for hands-free), push_to_talk, toggle.</summary>
        public string Mode { get; set; } = "hold_or_lock";
        public bool LiveText { get; set; } = true;
        public bool Sounds { get; set; } = true;
        public bool StartWithWindows { get; set; } = true;

        public static string Dir =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "LocalFlow");
        private static string FilePath => Path.Combine(Dir, "config.json");

        public bool IsSetUp => !string.IsNullOrWhiteSpace(Host) && !string.IsNullOrWhiteSpace(Token);

        public static readonly (string Id, string Label, int Vk)[] Hotkeys =
        {
            ("LeftAlt", "Left Alt", 0xA4),
            ("RightAlt", "Right Alt", 0xA5),
            ("RightCtrl", "Right Ctrl", 0xA3),
        };

        public int HotkeyVk
        {
            get
            {
                foreach (var h in Hotkeys) if (h.Id == Hotkey) return h.Vk;
                return 0xA4;
            }
        }

        public string HotkeyLabel
        {
            get
            {
                foreach (var h in Hotkeys) if (h.Id == Hotkey) return h.Label;
                return "Left Alt";
            }
        }

        private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

        public static Config Load()
        {
            try
            {
                if (File.Exists(FilePath))
                    return JsonSerializer.Deserialize<Config>(File.ReadAllText(FilePath)) ?? new Config();
            }
            catch (Exception e)
            {
                Log.Write("config unreadable, using defaults: " + e.Message);
            }
            return new Config();
        }

        public void Save()
        {
            Directory.CreateDirectory(Dir);
            var tmp = FilePath + ".tmp";
            File.WriteAllText(tmp, JsonSerializer.Serialize(this, Json));
            File.Move(tmp, FilePath, true);
        }
    }
}
