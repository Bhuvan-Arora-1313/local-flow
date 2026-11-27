using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace LocalFlowRemote
{
    internal enum IslandState { Hidden, Recording, Working }

    /// <summary>
    /// The island, drawn exactly like the Mac's island.py: a small dark pill
    /// near the bottom of the screen with an (x) on the left and the live
    /// spectrum of your voice mirrored around the centre; three pulsing dots
    /// while the Mac transcribes.
    /// </summary>
    internal sealed class IslandWindow : OverlayWindow
    {
        public const double BottomGap = 16;
        private readonly IslandView _view;

        public IslandWindow(Func<float[]> bands, Action onCancel) : base(clickThrough: false)
        {
            Width = IslandView.W;
            Height = IslandView.H;
            _view = new IslandView(bands, onCancel);
            Content = _view;
        }

        public void SetState(IslandState s, IntPtr monitor)
        {
            if (s == IslandState.Hidden)
            {
                _view.State = s;
                Hide();
                return;
            }
            bool wasHidden = !IsVisible;
            _view.State = s;
            if (wasHidden) ShowOn(monitor, BottomGap);
        }
    }

    internal sealed class IslandView : FrameworkElement
    {
        // same geometry as island.py (points there, DIPs here)
        private const double PadX = 10, PadY = 5, BarW = 2, BtnD = 16, BtnMargin = 4;
        private const double ContentX0 = BtnMargin + BtnD + 6;
        public const double W = 96 + ContentX0 - PadX, H = 24;

        private readonly Func<float[]> _bands;
        private readonly Action _onCancel;
        private double[] _disp = new double[Recorder.Bands * 2];
        private readonly DateTime _t0 = DateTime.Now;
        private bool _hover, _animating;
        private IslandState _state = IslandState.Hidden;

        private static readonly Brush Fill = Frozen(Color.FromArgb(235, 23, 23, 28));
        private static readonly Pen Edge = FrozenPen(Color.FromArgb(26, 255, 255, 255), 1.0);
        private static readonly Brush BtnIdle = Frozen(Color.FromArgb(31, 255, 255, 255));
        private static readonly Brush BtnHover = Frozen(Color.FromArgb(56, 255, 255, 255));
        private static readonly Pen CrossIdle = FrozenPen(Color.FromArgb(140, 245, 250, 255), 1.3);
        private static readonly Pen CrossHover = FrozenPen(Color.FromArgb(217, 245, 250, 255), 1.3);

        private static Brush Frozen(Color c) { var b = new SolidColorBrush(c); b.Freeze(); return b; }
        private static Pen FrozenPen(Color c, double w)
        {
            var p = new Pen(Frozen(c), w) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
            p.Freeze();
            return p;
        }

        public IslandView(Func<float[]> bands, Action onCancel)
        {
            _bands = bands;
            _onCancel = onCancel;
            Width = W;
            Height = H;
            SnapsToDevicePixels = false;
        }

        public IslandState State
        {
            get => _state;
            set
            {
                if (value == IslandState.Recording && _state != IslandState.Recording)
                    _disp = new double[Recorder.Bands * 2];
                _state = value;
                bool on = value != IslandState.Hidden;
                if (on && !_animating) { CompositionTarget.Rendering += OnFrame; _animating = true; }
                else if (!on && _animating) { CompositionTarget.Rendering -= OnFrame; _animating = false; }
                InvalidateVisual();
            }
        }

        private void OnFrame(object? sender, EventArgs e)
        {
            var u = _state == IslandState.Recording ? _bands() : Array.Empty<float>();
            int n = Recorder.Bands;
            for (int i = 0; i < n * 2; i++)
            {
                // mirror low -> high around the centre: symmetric, centre-weighted
                int j = i < n ? n - 1 - i : i - n;
                double target = j < u.Length ? u[j] : 0;
                _disp[i] = _state == IslandState.Recording ? Math.Max(target, _disp[i] * 0.72) : _disp[i] * 0.80;
            }
            InvalidateVisual();
        }

        private Rect BtnRect => new(BtnMargin, (H - BtnD) / 2, BtnD, BtnD);

        protected override void OnRender(DrawingContext dc)
        {
            var b = new Rect(0.5, 0.5, W - 1, H - 1);
            dc.DrawRoundedRectangle(Fill, Edge, b, H / 2, H / 2);
            if (_state == IslandState.Working) DrawWorking(dc);
            else DrawBars(dc);
            DrawCancel(dc);
        }

        private void DrawCancel(DrawingContext dc)
        {
            var r = BtnRect;
            double cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2, d = 3.2;
            dc.DrawEllipse(_hover ? BtnHover : BtnIdle, null, new Point(cx, cy), r.Width / 2, r.Height / 2);
            var pen = _hover ? CrossHover : CrossIdle;
            dc.DrawLine(pen, new Point(cx - d, cy - d), new Point(cx + d, cy + d));
            dc.DrawLine(pen, new Point(cx - d, cy + d), new Point(cx + d, cy - d));
        }

        private void DrawBars(DrawingContext dc)
        {
            int n = _disp.Length;
            double areaW = W - ContentX0 - PadX;
            double gap = n > 1 ? Math.Max(1.5, (areaW - BarW * n) / (n - 1)) : 0;
            double maxH = H - 2 * PadY, midY = H / 2;
            for (int i = 0; i < n; i++)
            {
                double v = Math.Clamp(_disp[i], 0, 1);
                double h = 1.5 + v * maxH;
                double x = ContentX0 + i * (BarW + gap);
                byte a = (byte)(255 * (0.50 + 0.45 * Math.Clamp(v * 1.6, 0, 1)));
                var brush = new SolidColorBrush(Color.FromArgb(a, 245, 250, 255));
                dc.DrawRoundedRectangle(brush, null, new Rect(x, midY - h / 2, BarW, h), BarW / 2, BarW / 2);
            }
        }

        private void DrawWorking(DrawingContext dc)
        {
            double t = (DateTime.Now - _t0).TotalSeconds;
            double cx = ContentX0 + (W - ContentX0 - PadX) / 2, cy = H / 2;
            for (int i = -1; i <= 1; i++)
            {
                double ph = 0.5 + 0.5 * Math.Sin(t * 5.0 + i * 1.1);
                double r = 1.6 + 1.6 * ph;
                byte a = (byte)(255 * (0.35 + 0.55 * ph));
                dc.DrawEllipse(new SolidColorBrush(Color.FromArgb(a, 245, 250, 255)), null,
                    new Point(cx + i * 9.0, cy), r, r);
            }
        }

        private bool OverButton(Point p)
        {
            var r = BtnRect;
            r.Inflate(4, 4);
            return r.Contains(p);
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            bool h = OverButton(e.GetPosition(this));
            Cursor = h ? Cursors.Hand : Cursors.Arrow;
            if (h != _hover) { _hover = h; InvalidateVisual(); }
        }

        protected override void OnMouseLeave(MouseEventArgs e)
        {
            if (_hover) { _hover = false; InvalidateVisual(); }
        }

        protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
        {
            if (OverButton(e.GetPosition(this))) _onCancel();
            e.Handled = true;
        }

        // the whole pill takes mouse input (not just painted pixels)
        protected override HitTestResult HitTestCore(PointHitTestParameters p) =>
            new PointHitTestResult(this, p.HitPoint);
    }
}
