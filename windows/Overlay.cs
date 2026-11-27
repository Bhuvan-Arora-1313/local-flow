using System;
using System.Windows;
using System.Windows.Interop;
using static LocalFlowRemote.Native;

namespace LocalFlowRemote
{
    /// <summary>
    /// Floating windows that never take focus (the text must keep going to
    /// the app you're typing in), stay on top, and sit centred near the
    /// bottom of the monitor you're working on -- like the Mac's panels.
    /// </summary>
    internal abstract class OverlayWindow : Window
    {
        private IntPtr _monitor;
        private double _bottomGap;        // DIPs between the work-area bottom and this window
        private readonly bool _clickThrough;

        protected OverlayWindow(bool clickThrough)
        {
            _clickThrough = clickThrough;
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;
            Background = System.Windows.Media.Brushes.Transparent;
            ResizeMode = ResizeMode.NoResize;
            ShowInTaskbar = false;
            ShowActivated = false;
            Topmost = true;
            Focusable = false;
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            var hwnd = new WindowInteropHelper(this).Handle;
            long ex = GetWindowLongPtr(hwnd, GWL_EXSTYLE).ToInt64();
            ex |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST;
            if (_clickThrough) ex |= WS_EX_TRANSPARENT;
            SetWindowLongPtr(hwnd, GWL_EXSTYLE, new IntPtr(ex));
            HwndSource.FromHwnd(hwnd)?.AddHook((IntPtr h, int msg, IntPtr w, IntPtr l, ref bool handled) =>
            {
                if (msg == WM_MOUSEACTIVATE)
                {
                    handled = true;               // clicks (the island's x) don't steal focus
                    return new IntPtr(MA_NOACTIVATE);
                }
                return IntPtr.Zero;
            });
        }

        /// <summary>Show on <paramref name="monitor"/>, <paramref name="bottomGap"/> DIPs above the taskbar.</summary>
        public void ShowOn(IntPtr monitor, double bottomGap)
        {
            _monitor = monitor;
            _bottomGap = bottomGap;
            new WindowInteropHelper(this).EnsureHandle();
            Place();
            if (!IsVisible) Show();
            Place();
        }

        // moved to a monitor with a different scale: WPF re-sized us, re-centre
        protected override void OnDpiChanged(DpiScale oldDpi, DpiScale newDpi)
        {
            base.OnDpiChanged(oldDpi, newDpi);
            if (_monitor != IntPtr.Zero) Dispatcher.BeginInvoke(new Action(Place));
        }

        protected void Place()
        {
            var hwnd = new WindowInteropHelper(this).Handle;
            if (hwnd == IntPtr.Zero || _monitor == IntPtr.Zero) return;
            var (work, scale) = Screens.WorkArea(_monitor);
            int w = (int)Math.Round(Width * scale), h = (int)Math.Round(Height * scale);
            int x = work.Left + (work.Right - work.Left - w) / 2;
            int y = work.Bottom - (int)Math.Round(_bottomGap * scale) - h;
            SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOACTIVATE | SWP_NOSIZE);
        }
    }

    internal static class Screens
    {
        /// <summary>The monitor of the window you're typing into (else the mouse's).</summary>
        public static IntPtr Target()
        {
            var fg = GetForegroundWindow();
            if (fg != IntPtr.Zero) return MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST);
            GetCursorPos(out var p);
            return MonitorFromPoint(p, MONITOR_DEFAULTTONEAREST);
        }

        public static (RECT Work, double Scale) WorkArea(IntPtr monitor)
        {
            var mi = new MONITORINFO { cbSize = System.Runtime.InteropServices.Marshal.SizeOf<MONITORINFO>() };
            GetMonitorInfo(monitor, ref mi);
            double scale = 1.0;
            try
            {
                if (GetDpiForMonitor(monitor, 0, out uint dx, out _) == 0 && dx > 0) scale = dx / 96.0;
            }
            catch (DllNotFoundException) { }
            return (mi.rcWork, scale);
        }
    }
}
