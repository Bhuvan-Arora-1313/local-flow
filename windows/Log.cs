using System;
using System.IO;

namespace LocalFlowRemote
{
    /// <summary>%APPDATA%\LocalFlow\localflow.log -- never the dictated text, only events/errors.</summary>
    internal static class Log
    {
        private static readonly object Gate = new();
        public static string FilePath => Path.Combine(Config.Dir, "localflow.log");

        public static void Write(string line)
        {
            try
            {
                lock (Gate)
                {
                    Directory.CreateDirectory(Config.Dir);
                    var f = new FileInfo(FilePath);
                    if (f.Exists && f.Length > 1_000_000)
                        File.Move(FilePath, FilePath + ".1", true);
                    File.AppendAllText(FilePath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {line}{Environment.NewLine}");
                }
            }
            catch
            {
                // logging must never take the app down
            }
        }
    }
}
