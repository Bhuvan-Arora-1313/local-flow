using System;
using System.Collections.Specialized;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media.Imaging;
using static LocalFlowRemote.Native;

namespace LocalFlowRemote
{
    /// <summary>
    /// Types the text where your cursor is: clipboard + Ctrl+V (instant, and
    /// works in terminals, browsers, Office), then puts your clipboard back --
    /// same as the Mac's inserter.py. Must run on the UI thread.
    /// </summary>
    internal static class Inserter
    {
        private const int VK_LCONTROL = 0xA2, VK_V = 0x56;
        private static readonly int[] Modifiers = { 0x10, 0x11, 0x12, 0x5B, 0x5C };  // Shift Ctrl Alt Win

        public static async Task Paste(string text)
        {
            if (string.IsNullOrEmpty(text)) return;
            // a still-held modifier would turn Ctrl+V into something else
            for (int i = 0; i < 40 && AnyModifierDown(); i++) await Task.Delay(15);

            string? prevText = null;
            BitmapSource? prevImage = null;
            StringCollection? prevFiles = null;
            try
            {
                if (Clipboard.ContainsText()) prevText = Clipboard.GetText();
                else if (Clipboard.ContainsFileDropList()) prevFiles = Clipboard.GetFileDropList();
                else if (Clipboard.ContainsImage()) prevImage = Clipboard.GetImage();
            }
            catch (Exception e) { Log.Write("clipboard read: " + e.Message); }

            var data = new DataObject();
            data.SetData(DataFormats.UnicodeText, text);
            // keep dictations out of Win+V clipboard history / cloud clipboard
            data.SetData("ExcludeClipboardContentFromMonitorProcessing", new MemoryStream(new byte[4]));
            if (!await Retry(() => Clipboard.SetDataObject(data, true)))
            {
                Log.Write("clipboard busy -- typing the text instead");
                TypeText(text);
                return;
            }
            await Task.Delay(40);
            Send(Key(VK_LCONTROL, false), Key(VK_V, false), Key(VK_V, true), Key(VK_LCONTROL, true));
            await Task.Delay(350);   // let the app read the clipboard before we restore it

            if (prevText != null) await Retry(() => Clipboard.SetText(prevText));
            else if (prevFiles != null) await Retry(() => Clipboard.SetFileDropList(prevFiles));
            else if (prevImage != null) await Retry(() => Clipboard.SetImage(prevImage));
        }

        /// <summary>Fallback: type each character (slower, no clipboard).</summary>
        public static void TypeText(string text)
        {
            foreach (var c in text)
            {
                if (c == '\n') { Send(Key(0x0D, false), Key(0x0D, true)); continue; }
                Send(Unicode(c, false), Unicode(c, true));
            }
        }

        private static bool AnyModifierDown()
        {
            foreach (var vk in Modifiers)
                if ((GetAsyncKeyState(vk) & 0x8000) != 0) return true;
            return false;
        }

        // another app can hold the clipboard open for a moment
        private static async Task<bool> Retry(Action a)
        {
            for (int i = 0; i < 10; i++)
            {
                try { a(); return true; }
                catch (COMException) { await Task.Delay(30); }
                catch (ExternalException) { await Task.Delay(30); }
            }
            return false;
        }
    }
}
