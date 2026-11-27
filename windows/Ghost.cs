using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace LocalFlowRemote
{
    /// <summary>
    /// The box above the island: the faded live transcript while you speak
    /// ("● listening…", like the Mac's ghost text), and short notices such
    /// as "Can't reach your Mac".
    /// </summary>
    internal sealed class GhostWindow : OverlayWindow
    {
        private const double GW = 440, GH = 92, MaxChars = 260;
        private static readonly double Gap = IslandWindow.BottomGap + IslandView.H + 12;

        private readonly TextBlock _caption, _text;
        private readonly DispatcherTimer _autoHide;

        private static readonly Brush ListeningColor = new SolidColorBrush(Color.FromArgb(217, 255, 128, 115));
        private static readonly Brush NoticeColor = new SolidColorBrush(Color.FromArgb(230, 255, 196, 92));
        private static readonly Brush FadedText = new SolidColorBrush(Color.FromArgb(148, 255, 255, 255));
        private static readonly Brush NoticeText = new SolidColorBrush(Color.FromArgb(225, 255, 255, 255));

        public GhostWindow() : base(clickThrough: true)
        {
            Width = GW;
            Height = GH;
            var font = new FontFamily("Segoe UI");
            _caption = new TextBlock
            {
                FontFamily = font, FontSize = 10.5, Margin = new Thickness(16, 9, 16, 0),
                VerticalAlignment = VerticalAlignment.Top,
            };
            _text = new TextBlock
            {
                FontFamily = font, FontSize = 15, TextWrapping = TextWrapping.Wrap,
                VerticalAlignment = VerticalAlignment.Bottom,   // overflow drops the OLDEST words
            };
            var clip = new Grid { Margin = new Thickness(16, 26, 16, 12), ClipToBounds = true };
            clip.Children.Add(_text);
            var grid = new Grid();
            grid.Children.Add(_caption);
            grid.Children.Add(clip);
            Content = new Border
            {
                CornerRadius = new CornerRadius(16),
                Background = new SolidColorBrush(Color.FromArgb(230, 23, 23, 28)),
                BorderBrush = new SolidColorBrush(Color.FromArgb(26, 255, 255, 255)),
                BorderThickness = new Thickness(1),
                Child = grid,
            };
            _autoHide = new DispatcherTimer();
            _autoHide.Tick += (_, _) => { _autoHide.Stop(); Hide(); };
        }

        public void ShowListening(IntPtr monitor)
        {
            _autoHide.Stop();
            _caption.Text = "● listening…";
            _caption.Foreground = ListeningColor;
            _text.Foreground = FadedText;
            _text.Text = "";
            ShowOn(monitor, Gap);
        }

        public void SetText(string text)
        {
            text = (text ?? "").Trim();
            if (text.Length > MaxChars) text = "…" + text[^(int)MaxChars..];
            _text.Text = text;
        }

        public void ShowNotice(IntPtr monitor, string caption, string text, double seconds = 6)
        {
            _caption.Text = caption;
            _caption.Foreground = NoticeColor;
            _text.Foreground = NoticeText;
            _text.Text = text;
            ShowOn(monitor, Gap);
            _autoHide.Stop();
            _autoHide.Interval = TimeSpan.FromSeconds(seconds);
            _autoHide.Start();
        }

        public void HideListening()
        {
            if (_caption.Foreground == ListeningColor) Hide();
        }
    }
}
