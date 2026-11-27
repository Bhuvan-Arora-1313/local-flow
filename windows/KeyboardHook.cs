using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using static LocalFlowRemote.Native;

namespace LocalFlowRemote
{
    /// <summary>
    /// Global hotkey, like the Mac's hold-Option listener.
    ///
    /// A bare press of the hotkey is swallowed, so a tap of Alt doesn't open
    /// app menus / ribbon key tips. When the hotkey turns out to be part of a
    /// shortcut (Alt+Tab, Ctrl+C, ...), the recording is aborted and the
    /// swallowed press is replayed in front of the other key, so the shortcut
    /// still works exactly as normal.
    ///
    /// Runs on its own thread with its own message loop: Windows silently
    /// drops a low-level hook whose thread is too busy to answer, and the UI
    /// thread sometimes is.
    /// </summary>
    internal sealed class KeyboardHook : IDisposable
    {
        public event Action? HotkeyDown, HotkeyUp, ChordAbort;

        private volatile int _hotVk;
        private Thread? _thread;
        private uint _threadId;
        private IntPtr _hook;
        private LowLevelKeyboardProc? _proc;   // keep the delegate alive

        // hook-thread state only
        private readonly HashSet<int> _down = new();
        private bool _hotDown, _chordPass, _replayed;

        private const int VK_LCONTROL = 0xA2, VK_RMENU = 0xA5;

        public KeyboardHook(int vk) { _hotVk = vk; }

        public void SetHotkey(int vk) => _hotVk = vk;

        public void Start()
        {
            var ready = new ManualResetEventSlim();
            _thread = new Thread(() =>
            {
                _threadId = GetCurrentThreadId();
                _proc = Proc;
                _hook = SetWindowsHookEx(WH_KEYBOARD_LL, _proc, GetModuleHandle(null), 0);
                if (_hook == IntPtr.Zero) Log.Write($"keyboard hook failed: {Marshal.GetLastWin32Error()}");
                ready.Set();
                while (GetMessage(out var msg, IntPtr.Zero, 0, 0) > 0)
                {
                    TranslateMessage(ref msg);
                    DispatchMessage(ref msg);
                }
                if (_hook != IntPtr.Zero) UnhookWindowsHookEx(_hook);
            }) { IsBackground = true, Name = "hotkey-hook" };
            _thread.Start();
            ready.Wait(2000);
        }

        // AltGr (Right Alt on many layouts) arrives as a fake Left Ctrl + Right Alt
        private bool Ignored(int vk, int hot) => hot == VK_RMENU && vk == VK_LCONTROL;

        private bool OthersHeld(int hot)
        {
            // drop keys whose key-up we never saw (lock screen, UAC prompt ...)
            _down.RemoveWhere(k => (GetAsyncKeyState(k) & 0x8000) == 0);
            foreach (var k in _down)
                if (k != hot && !Ignored(k, hot)) return true;
            return false;
        }

        private IntPtr Proc(int nCode, IntPtr wParam, IntPtr lParam)
        {
            if (nCode < 0) return CallNextHookEx(_hook, nCode, wParam, lParam);
            var k = Marshal.PtrToStructure<KBDLLHOOKSTRUCT>(lParam);
            if ((k.flags & LLKHF_INJECTED) != 0) return CallNextHookEx(_hook, nCode, wParam, lParam);

            int msg = wParam.ToInt32();
            bool isDown = msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN;
            bool isUp = msg == WM_KEYUP || msg == WM_SYSKEYUP;
            int vk = (int)k.vkCode;
            int hot = _hotVk;

            if (vk != hot)
            {
                if (isDown)
                {
                    _down.Add(vk);
                    if (_hotDown && !_chordPass && !_replayed && !Ignored(vk, hot))
                    {
                        // the hotkey is being used as a modifier: a shortcut, not dictation
                        _replayed = true;
                        Raise(ChordAbort);
                        Send(Key(hot, false), Key(vk, k.scanCode, (k.flags & LLKHF_EXTENDED) != 0, false));
                        return (IntPtr)1;
                    }
                }
                else if (isUp)
                {
                    _down.Remove(vk);
                }
                return CallNextHookEx(_hook, nCode, wParam, lParam);
            }

            if (isDown)
            {
                if (_hotDown)          // auto-repeat while held
                    return _chordPass || _replayed ? CallNextHookEx(_hook, nCode, wParam, lParam) : (IntPtr)1;
                _hotDown = true;
                if (OthersHeld(hot))
                {
                    // pressed on top of another key: part of a shortcut, leave it alone
                    _chordPass = true;
                    return CallNextHookEx(_hook, nCode, wParam, lParam);
                }
                Raise(HotkeyDown);
                return (IntPtr)1;
            }
            if (isUp)
            {
                _hotDown = false;
                if (_chordPass || _replayed)
                {
                    _chordPass = _replayed = false;
                    return CallNextHookEx(_hook, nCode, wParam, lParam);
                }
                Raise(HotkeyUp);
                return (IntPtr)1;
            }
            return CallNextHookEx(_hook, nCode, wParam, lParam);
        }

        private static void Raise(Action? a)
        {
            try { a?.Invoke(); } catch (Exception e) { Log.Write("hotkey handler: " + e); }
        }

        public void Dispose()
        {
            if (_threadId != 0) PostThreadMessage(_threadId, WM_QUIT, IntPtr.Zero, IntPtr.Zero);
        }
    }
}
