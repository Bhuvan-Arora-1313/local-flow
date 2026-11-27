using System;
using System.Runtime.InteropServices;

namespace LocalFlowRemote
{
    /// <summary>Win32 calls: keyboard hook, synthetic input, monitors, window styles.</summary>
    internal static class Native
    {
        // ---------- low-level keyboard hook ----------
        public const int WH_KEYBOARD_LL = 13;
        public const int WM_KEYDOWN = 0x0100, WM_KEYUP = 0x0101, WM_SYSKEYDOWN = 0x0104, WM_SYSKEYUP = 0x0105;
        public const int WM_QUIT = 0x0012;
        public const uint LLKHF_EXTENDED = 0x1, LLKHF_INJECTED = 0x10;

        [StructLayout(LayoutKind.Sequential)]
        public struct KBDLLHOOKSTRUCT
        {
            public uint vkCode, scanCode, flags, time;
            public IntPtr dwExtraInfo;
        }

        public delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc fn, IntPtr hMod, uint threadId);
        [DllImport("user32.dll")] public static extern bool UnhookWindowsHookEx(IntPtr hook);
        [DllImport("user32.dll")] public static extern IntPtr CallNextHookEx(IntPtr hook, int nCode, IntPtr w, IntPtr l);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr GetModuleHandle(string? name);
        [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();

        [StructLayout(LayoutKind.Sequential)]
        public struct MSG
        {
            public IntPtr hwnd;
            public uint message;
            public IntPtr wParam, lParam;
            public uint time;
            public int x, y;
        }

        [DllImport("user32.dll")] public static extern int GetMessage(out MSG msg, IntPtr hwnd, uint min, uint max);
        [DllImport("user32.dll")] public static extern bool TranslateMessage(ref MSG msg);
        [DllImport("user32.dll")] public static extern IntPtr DispatchMessage(ref MSG msg);
        [DllImport("user32.dll")] public static extern bool PostThreadMessage(uint threadId, uint msg, IntPtr w, IntPtr l);

        // ---------- synthetic input ----------
        public const uint INPUT_KEYBOARD = 1;
        public const uint KEYEVENTF_EXTENDEDKEY = 0x1, KEYEVENTF_KEYUP = 0x2, KEYEVENTF_UNICODE = 0x4;

        [StructLayout(LayoutKind.Sequential)]
        public struct MOUSEINPUT
        {
            public int dx, dy;
            public uint mouseData, dwFlags, time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct KEYBDINPUT
        {
            public ushort wVk, wScan;
            public uint dwFlags, time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Explicit)]
        public struct InputUnion
        {
            [FieldOffset(0)] public MOUSEINPUT mi;
            [FieldOffset(0)] public KEYBDINPUT ki;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct INPUT
        {
            public uint type;
            public InputUnion u;
        }

        [DllImport("user32.dll", SetLastError = true)]
        public static extern uint SendInput(uint n, INPUT[] inputs, int size);
        [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint mapType);
        [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vk);

        public static bool IsExtended(int vk) =>
            vk == 0xA3 || vk == 0xA5 || vk == 0x5B || vk == 0x5C;   // RCtrl, RAlt, LWin, RWin

        public static INPUT Key(int vk, bool up) => new INPUT
        {
            type = INPUT_KEYBOARD,
            u = new InputUnion
            {
                ki = new KEYBDINPUT
                {
                    wVk = (ushort)vk,
                    wScan = (ushort)MapVirtualKey((uint)vk, 0),
                    dwFlags = (up ? KEYEVENTF_KEYUP : 0) | (IsExtended(vk) ? KEYEVENTF_EXTENDEDKEY : 0),
                },
            },
        };

        public static INPUT Key(int vk, uint scan, bool extended, bool up) => new INPUT
        {
            type = INPUT_KEYBOARD,
            u = new InputUnion
            {
                ki = new KEYBDINPUT
                {
                    wVk = (ushort)vk,
                    wScan = (ushort)scan,
                    dwFlags = (up ? KEYEVENTF_KEYUP : 0) | (extended ? KEYEVENTF_EXTENDEDKEY : 0),
                },
            },
        };

        public static INPUT Unicode(char c, bool up) => new INPUT
        {
            type = INPUT_KEYBOARD,
            u = new InputUnion { ki = new KEYBDINPUT { wScan = c, dwFlags = KEYEVENTF_UNICODE | (up ? KEYEVENTF_KEYUP : 0) } },
        };

        public static void Send(params INPUT[] inputs) =>
            SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<INPUT>());

        // ---------- monitors ----------
        [StructLayout(LayoutKind.Sequential)]
        public struct RECT { public int Left, Top, Right, Bottom; }

        [StructLayout(LayoutKind.Sequential)]
        public struct POINT { public int X, Y; }

        [StructLayout(LayoutKind.Sequential)]
        public struct MONITORINFO
        {
            public int cbSize;
            public RECT rcMonitor, rcWork;
            public uint dwFlags;
        }

        public const uint MONITOR_DEFAULTTONEAREST = 2;
        [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);
        [DllImport("user32.dll")] public static extern IntPtr MonitorFromPoint(POINT pt, uint flags);
        [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT pt);
        [DllImport("user32.dll")] public static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);
        [DllImport("shcore.dll")] public static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint dpiX, out uint dpiY);

        // ---------- windows ----------
        public const int GWL_EXSTYLE = -20;
        public const long WS_EX_TOPMOST = 0x8, WS_EX_TRANSPARENT = 0x20, WS_EX_TOOLWINDOW = 0x80, WS_EX_NOACTIVATE = 0x08000000;
        public const uint SWP_NOSIZE = 0x1, SWP_NOACTIVATE = 0x10;
        public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
        public const int WM_MOUSEACTIVATE = 0x0021, MA_NOACTIVATE = 3;

        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] public static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] public static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);
        [DllImport("user32.dll")]
        public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    }
}
