using System;
using System.Threading.Tasks;
using System.Windows.Threading;

namespace LocalFlowRemote
{
    /// <summary>
    /// The dictation flow, ported from the Mac's flow.py: hold the hotkey to
    /// talk, double-tap to lock hands-free (tap again to stop), x on the
    /// island to cancel. Audio goes to the Mac; the cleaned text comes back
    /// and is pasted where your cursor is. Everything here runs on the UI
    /// thread.
    /// </summary>
    internal sealed class Controller
    {
        private const double ShortTapS = 0.35, DoubleTapS = 0.4;
        private const int MinAudioBytes = Recorder.SampleRate * 2 * 3 / 10;   // 0.3 s
        private const int PreviewSeconds = 10;

        public Config Cfg { get; }
        private readonly Dispatcher _ui;
        private readonly KeyboardHook _hook;
        private readonly Recorder _rec = new();
        private readonly IslandWindow _island;
        private readonly GhostWindow _ghost = new();
        private Tray? _tray;

        private bool _recording, _locked, _hotDown, _toggleOn;
        private DateTime _pressT;
        private DispatcherTimer? _releaseTimer;
        private readonly DispatcherTimer _previewTimer;
        private bool _previewBusy;
        private IntPtr _monitor;
        private int _jobId, _cancelledUpTo, _pending;
        private readonly DispatcherTimer _healthTimer;

        public string LastText { get; private set; } = "";
        public byte[]? FailedAudio { get; private set; }
        public string Status { get; private set; } = "Starting…";
        public bool Connected { get; private set; }

        public Controller(Dispatcher ui)
        {
            _ui = ui;
            Cfg = Config.Load();
            Sounds.Enabled = Cfg.Sounds;
            _island = new IslandWindow(() => _rec.CurrentBands, CancelAll);
            _hook = new KeyboardHook(Cfg.HotkeyVk);
            _hook.HotkeyDown += () => _ui.BeginInvoke(OnHotkeyDown);
            _hook.HotkeyUp += () => _ui.BeginInvoke(OnHotkeyUp);
            _hook.ChordAbort += () => _ui.BeginInvoke(OnChord);
            _previewTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1000) };
            _previewTimer.Tick += async (_, _) => await PreviewTick();
            _healthTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
            _healthTimer.Tick += async (_, _) => await CheckHealth();
        }

        public void Start()
        {
            _hook.Start();
            _tray = new Tray(this);
            Startup.Apply(Cfg.StartWithWindows);
            _healthTimer.Start();
            Log.Write($"started; hotkey {Cfg.HotkeyLabel}, Mac {(Cfg.IsSetUp ? ApiClient.BaseUrl(Cfg) : "not set up")}");
            if (!Cfg.IsSetUp) OpenSettings();
            else _ = CheckHealth();
        }

        // ---------- hotkey ----------
        private void OnHotkeyDown()
        {
            _hotDown = true;
            _pressT = DateTime.Now;
            switch (Cfg.Mode)
            {
                case "push_to_talk":
                    Begin();
                    break;
                case "toggle":
                    _toggleOn = !_toggleOn;
                    if (_toggleOn) Begin(); else End();
                    break;
                default:   // hold_or_lock
                    if (_locked)
                    {
                        _locked = false;
                        End();
                        return;
                    }
                    if (CancelReleaseTimer())
                    {
                        // 2nd tap of a double-tap: lock hands-free
                        _locked = true;
                        Log.Write("locked hands-free (double-tap)");
                        return;
                    }
                    Begin();
                    break;
            }
        }

        private void OnHotkeyUp()
        {
            _hotDown = false;
            switch (Cfg.Mode)
            {
                case "push_to_talk":
                    End();
                    break;
                case "toggle":
                    break;
                default:
                    if (_locked || !_recording) return;
                    if ((DateTime.Now - _pressT).TotalSeconds < ShortTapS)
                    {
                        // maybe the first tap of a double-tap: wait to see
                        _releaseTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(DoubleTapS) };
                        _releaseTimer.Tick += (_, _) =>
                        {
                            CancelReleaseTimer();
                            if (!_locked && !_hotDown) End();
                        };
                        _releaseTimer.Start();
                    }
                    else End();
                    break;
            }
        }

        // the hotkey was part of a shortcut (Alt+Tab ...): drop the recording
        private void OnChord()
        {
            CancelReleaseTimer();
            _locked = _toggleOn = false;
            if (_recording) Discard();
        }

        private bool CancelReleaseTimer()
        {
            var t = _releaseTimer;
            _releaseTimer = null;
            if (t == null) return false;
            t.Stop();
            return true;
        }

        // ---------- recording ----------
        private void Begin()
        {
            if (_recording) return;
            _monitor = Screens.Target();
            if (!Cfg.IsSetUp)
            {
                Sounds.Error();
                _ghost.ShowNotice(_monitor, "LocalFlow isn't connected to a Mac yet",
                    "Right-click the LocalFlow icon in the taskbar tray → Settings.");
                OpenSettings();
                return;
            }
            if (!_rec.Start(out var err))
            {
                Sounds.Error();
                _ghost.ShowNotice(_monitor, "Couldn't open the microphone",
                    "Check Windows Settings → Privacy & security → Microphone → \"Let desktop apps access your microphone\". " + err);
                return;
            }
            _recording = true;
            Sounds.Start();
            UpdateIsland();
            if (Cfg.LiveText)
            {
                _ghost.ShowListening(_monitor);
                _previewBusy = false;
                _previewTimer.Interval = TimeSpan.FromMilliseconds(700);
                _previewTimer.Start();
            }
        }

        private byte[] StopRecording()
        {
            _recording = false;
            _locked = _toggleOn = false;
            _previewTimer.Stop();
            _ghost.HideListening();
            return _rec.Stop();
        }

        private void End()
        {
            CancelReleaseTimer();
            if (!_recording) return;
            var pcm = StopRecording();
            if (pcm.Length < MinAudioBytes)
            {
                UpdateIsland();       // a stray tap, not speech
                return;
            }
            _ = Send(pcm);
        }

        private void Discard()
        {
            StopRecording();
            UpdateIsland();
        }

        /// <summary>The island's x: drop the recording, or abandon the transcription in flight.</summary>
        public void CancelAll()
        {
            CancelReleaseTimer();
            if (_recording) Discard();
            _cancelledUpTo = _jobId;
            _pending = 0;
            UpdateIsland();
        }

        private void UpdateIsland()
        {
            var s = _recording ? IslandState.Recording : _pending > 0 ? IslandState.Working : IslandState.Hidden;
            _island.SetState(s, _monitor);
        }

        // ---------- talking to the Mac ----------
        private async Task Send(byte[] pcm)
        {
            int id = ++_jobId;
            _pending++;
            UpdateIsland();
            var t0 = DateTime.Now;
            var r = await ApiClient.Transcribe(Cfg, pcm);
            if (id <= _cancelledUpTo) return;                    // x was pressed meanwhile
            _pending = Math.Max(0, _pending - 1);
            UpdateIsland();
            if (r.Ok && r.Text.Length > 0)
            {
                Log.Write($"dictation: {pcm.Length / 32000.0:F1}s audio, {r.Text.Length} chars, {(DateTime.Now - t0).TotalSeconds:F2}s round trip");
                LastText = r.Text;
                FailedAudio = null;
                SetConnected(true, null);
                await Inserter.Paste(r.Text);
                Sounds.Done();
            }
            else if (r.Status == 422)
            {
                Log.Write("nothing recognised");                 // silence: nothing to type
            }
            else
            {
                Log.Write("transcribe failed: " + r.Error);
                FailedAudio = pcm;
                SetConnected(false, r.Error);
                Sounds.Error();
                _ghost.ShowNotice(_monitor, "Couldn't get the text from your Mac",
                    $"{Cap(r.Error)}. Your recording is kept: tray icon → Retry last recording.", 8);
            }
            _tray?.Refresh();
        }

        public async Task RetryFailed()
        {
            var pcm = FailedAudio;
            if (pcm == null) return;
            _monitor = Screens.Target();
            await Send(pcm);
        }

        private async Task PreviewTick()
        {
            _previewTimer.Interval = TimeSpan.FromMilliseconds(1000);
            if (!_recording || _previewBusy) return;
            var pcm = _rec.AudioSoFar(PreviewSeconds);
            if (pcm.Length < Recorder.SampleRate) return;      // < 0.5 s
            _previewBusy = true;
            try
            {
                var r = await ApiClient.Preview(Cfg, pcm);
                if (_recording && r.Ok && r.Text.Length > 0) _ghost.SetText(r.Text);
            }
            finally { _previewBusy = false; }
        }

        public async Task CheckHealth()
        {
            if (!Cfg.IsSetUp)
            {
                Status = "Not set up: open Settings";
                Connected = false;
                _tray?.Refresh();
                return;
            }
            var r = await ApiClient.Health(Cfg);
            SetConnected(r.Ok, r.Ok ? null : r.Error);
        }

        private void SetConnected(bool ok, string? error)
        {
            var status = ok ? "Connected to your Mac" : "Mac not reachable: " + error;
            if (status != Status) Log.Write(status);
            Connected = ok;
            Status = status;
            _tray?.Refresh();
        }

        private static string Cap(string s) => s.Length == 0 ? s : char.ToUpper(s[0]) + s[1..];

        // ---------- menu actions ----------
        public async Task PasteLast()
        {
            if (LastText.Length > 0) await Inserter.Paste(LastText);
        }

        public async Task RestartMac()
        {
            var r = await ApiClient.RestartMac(Cfg);
            _ghost.ShowNotice(Screens.Target(), r.Ok ? "Restarting LocalFlow on the Mac" : "Couldn't restart the Mac's LocalFlow",
                r.Ok ? "It takes about 15 seconds to come back." : Cap(r.Error) + ".");
        }

        public void ApplySettings()
        {
            Cfg.Save();
            Sounds.Enabled = Cfg.Sounds;
            _hook.SetHotkey(Cfg.HotkeyVk);
            Startup.Apply(Cfg.StartWithWindows);
            _tray?.Refresh();
            _ = CheckHealth();
        }

        private SettingsWindow? _settings;

        public void OpenSettings()
        {
            if (_settings != null) { _settings.Activate(); return; }
            _settings = new SettingsWindow(this);
            _settings.Closed += (_, _) => _settings = null;
            _settings.Show();
            _settings.Activate();
        }

        public void Quit()
        {
            if (_recording) _rec.Stop();
            _hook.Dispose();
            _tray?.Dispose();
            System.Windows.Application.Current.Shutdown();
        }
    }
}
