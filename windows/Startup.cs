using System;
using Microsoft.Win32;

namespace LocalFlowRemote
{
    /// <summary>"Start with Windows": the current user's Run key (no admin needed).</summary>
    internal static class Startup
    {
        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string Name = "LocalFlow";

        public static void Apply(bool on)
        {
            try
            {
                using var k = Registry.CurrentUser.CreateSubKey(RunKey);
                var exe = Environment.ProcessPath;
                if (on && exe != null) k.SetValue(Name, $"\"{exe}\"");
                else if (k.GetValue(Name) != null) k.DeleteValue(Name);
            }
            catch (Exception e)
            {
                Log.Write("start-with-Windows setting failed: " + e.Message);
            }
        }
    }
}
