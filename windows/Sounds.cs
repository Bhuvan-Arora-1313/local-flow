using System;
using System.IO;
using System.Media;

namespace LocalFlowRemote
{
    /// <summary>
    /// Short cues like the Mac's Tink / Pop / Basso, synthesised at startup
    /// (Windows' own system sounds are much louder and longer).
    /// </summary>
    internal static class Sounds
    {
        private const int Rate = 22050;
        private static readonly SoundPlayer StartP = Player(Tink());
        private static readonly SoundPlayer DoneP = Player(Pop());
        private static readonly SoundPlayer ErrorP = Player(Thud());

        public static bool Enabled = true;

        public static void Start() => Play(StartP);
        public static void Done() => Play(DoneP);
        public static void Error() => Play(ErrorP);

        private static void Play(SoundPlayer p)
        {
            if (!Enabled) return;
            try { p.Stop(); p.Play(); } catch (Exception e) { Log.Write("sound: " + e.Message); }
        }

        private static float[] Tink()
        {
            var s = new float[(int)(Rate * 0.12)];
            for (int i = 0; i < s.Length; i++)
            {
                double t = (double)i / Rate, env = Math.Exp(-t / 0.025) * Math.Min(1, t / 0.002);
                s[i] = (float)(env * (0.20 * Math.Sin(2 * Math.PI * 2093 * t) + 0.07 * Math.Sin(2 * Math.PI * 3136 * t)));
            }
            return s;
        }

        private static float[] Pop()
        {
            var s = new float[(int)(Rate * 0.09)];
            double phase = 0;
            for (int i = 0; i < s.Length; i++)
            {
                double t = (double)i / Rate;
                double f = 420 + 520 * Math.Exp(-t / 0.012);    // quick downward sweep
                phase += 2 * Math.PI * f / Rate;
                double env = Math.Exp(-t / 0.022) * Math.Min(1, t / 0.0015);
                s[i] = (float)(0.32 * env * Math.Sin(phase));
            }
            return s;
        }

        private static float[] Thud()
        {
            var s = new float[(int)(Rate * 0.32)];
            for (int i = 0; i < s.Length; i++)
            {
                double t = (double)i / Rate, env = Math.Exp(-t / 0.07) * Math.Min(1, t / 0.004);
                s[i] = (float)(env * (0.30 * Math.Sin(2 * Math.PI * 155 * t) + 0.12 * Math.Sin(2 * Math.PI * 310 * t)));
            }
            return s;
        }

        private static SoundPlayer Player(float[] samples)
        {
            var ms = new MemoryStream();
            var w = new BinaryWriter(ms);
            int bytes = samples.Length * 2;
            w.Write("RIFF"u8.ToArray()); w.Write(36 + bytes); w.Write("WAVE"u8.ToArray());
            w.Write("fmt "u8.ToArray()); w.Write(16); w.Write((short)1); w.Write((short)1);
            w.Write(Rate); w.Write(Rate * 2); w.Write((short)2); w.Write((short)16);
            w.Write("data"u8.ToArray()); w.Write(bytes);
            foreach (var v in samples) w.Write((short)Math.Clamp(v * 32767, -32768, 32767));
            ms.Position = 0;
            var p = new SoundPlayer(ms);
            try { p.Load(); } catch { }
            return p;
        }
    }
}
