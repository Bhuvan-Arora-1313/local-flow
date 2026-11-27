using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace LocalFlowRemote
{
    /// <summary>Pairing with the Mac + preferences. Opens by itself on first run.</summary>
    internal sealed class SettingsWindow : Window
    {
        private readonly Controller _c;
        private readonly TextBox _host, _port, _token;
        private readonly ComboBox _hotkey, _mode;
        private readonly CheckBox _live, _sounds, _startup;
        private readonly TextBlock _result;

        public SettingsWindow(Controller c)
        {
            _c = c;
            var cfg = c.Cfg;
            Title = "LocalFlow";
            Width = 460;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            FontFamily = new FontFamily("Segoe UI");
            FontSize = 13;

            _result = new TextBlock { Margin = new Thickness(0, 10, 0, 0), TextWrapping = TextWrapping.Wrap };
            var p = new StackPanel { Margin = new Thickness(22, 18, 22, 18) };
            p.Children.Add(new TextBlock
            {
                Text = "LocalFlow",
                FontSize = 20,
                FontWeight = FontWeights.SemiBold,
            });
            p.Children.Add(Note("Speak anywhere on this PC and the text is typed where your cursor is. "
                + "The speech model runs on your Mac: this app sends your voice there over Tailscale."));

            p.Children.Add(Label("Mac's Tailscale address"));
            _host = Box(cfg.Host);
            p.Children.Add(_host);
            p.Children.Add(Note("The Mac's Tailscale IP (100.x.x.x) or its name. This PC needs Tailscale running, "
                + "with the Mac on the same tailnet or shared with you."));

            p.Children.Add(Label("Port"));
            _port = Box(cfg.Port.ToString());
            _port.Width = 90;
            _port.HorizontalAlignment = HorizontalAlignment.Left;
            p.Children.Add(_port);

            p.Children.Add(Label("Pairing token"));
            _token = Box(cfg.Token);
            p.Children.Add(_token);
            p.Children.Add(Note("On the Mac: LocalFlow menu → Settings → Remote dictation → Pairing token."));

            p.Children.Add(Label("Hotkey"));
            _hotkey = new ComboBox { Margin = new Thickness(0, 2, 0, 0) };
            foreach (var h in Config.Hotkeys)
            {
                _hotkey.Items.Add(new ComboBoxItem { Content = h.Label, Tag = h.Id });
                if (h.Id == cfg.Hotkey) _hotkey.SelectedIndex = _hotkey.Items.Count - 1;
            }
            if (_hotkey.SelectedIndex < 0) _hotkey.SelectedIndex = 0;
            p.Children.Add(_hotkey);

            p.Children.Add(Label("How the hotkey works"));
            _mode = new ComboBox { Margin = new Thickness(0, 2, 0, 0) };
            foreach (var (id, label) in new[]
            {
                ("hold_or_lock", "Hold to talk · double-tap for hands-free"),
                ("push_to_talk", "Hold to talk"),
                ("toggle", "Tap to start, tap to stop"),
            })
            {
                _mode.Items.Add(new ComboBoxItem { Content = label, Tag = id });
                if (id == cfg.Mode) _mode.SelectedIndex = _mode.Items.Count - 1;
            }
            if (_mode.SelectedIndex < 0) _mode.SelectedIndex = 0;
            p.Children.Add(_mode);

            _live = Check("Show live text while speaking", cfg.LiveText);
            _sounds = Check("Sounds", cfg.Sounds);
            _startup = Check("Start with Windows", cfg.StartWithWindows);
            p.Children.Add(_live);
            p.Children.Add(_sounds);
            p.Children.Add(_startup);

            var buttons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 18, 0, 0) };
            var test = new Button { Content = "Test connection", Padding = new Thickness(14, 5, 14, 5) };
            var save = new Button
            {
                Content = "Save",
                Padding = new Thickness(22, 5, 22, 5),
                Margin = new Thickness(10, 0, 0, 0),
                IsDefault = true,
            };
            test.Click += async (_, _) =>
            {
                var tmp = Read();
                if (tmp == null) return;
                _result.Text = "Checking…";
                _result.Foreground = Brushes.Gray;
                var r = await ApiClient.Health(tmp);
                _result.Text = r.Ok ? "✓ Connected to your Mac" : "✗ " + r.Error;
                _result.Foreground = r.Ok ? Brushes.SeaGreen : Brushes.Firebrick;
            };
            save.Click += (_, _) =>
            {
                var tmp = Read();
                if (tmp == null) return;
                cfg.Host = tmp.Host;
                cfg.Port = tmp.Port;
                cfg.Token = tmp.Token;
                cfg.Hotkey = tmp.Hotkey;
                cfg.Mode = tmp.Mode;
                cfg.LiveText = tmp.LiveText;
                cfg.Sounds = tmp.Sounds;
                cfg.StartWithWindows = tmp.StartWithWindows;
                _c.ApplySettings();
                Close();
            };
            buttons.Children.Add(test);
            buttons.Children.Add(save);
            p.Children.Add(buttons);
            p.Children.Add(_result);

            Content = p;
        }

        private Config? Read()
        {
            if (!int.TryParse(_port.Text.Trim(), out int port) || port < 1 || port > 65535)
            {
                _result.Text = "✗ The port must be a number (LocalFlow's default is 8765).";
                _result.Foreground = Brushes.Firebrick;
                return null;
            }
            if (string.IsNullOrWhiteSpace(_host.Text) || string.IsNullOrWhiteSpace(_token.Text))
            {
                _result.Text = "✗ Fill in the Mac's address and the pairing token.";
                _result.Foreground = Brushes.Firebrick;
                return null;
            }
            return new Config
            {
                Host = _host.Text.Trim(),
                Port = port,
                Token = _token.Text.Trim(),
                Hotkey = (string)((ComboBoxItem)_hotkey.SelectedItem).Tag,
                Mode = (string)((ComboBoxItem)_mode.SelectedItem).Tag,
                LiveText = _live.IsChecked == true,
                Sounds = _sounds.IsChecked == true,
                StartWithWindows = _startup.IsChecked == true,
            };
        }

        private static TextBlock Label(string s) =>
            new() { Text = s, FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 14, 0, 0) };

        private static TextBlock Note(string s) =>
            new() { Text = s, TextWrapping = TextWrapping.Wrap, Foreground = Brushes.DimGray, FontSize = 12, Margin = new Thickness(0, 4, 0, 0) };

        private static TextBox Box(string v) =>
            new() { Text = v, Padding = new Thickness(4, 3, 4, 3), Margin = new Thickness(0, 2, 0, 0) };

        private static CheckBox Check(string s, bool on) =>
            new() { Content = s, IsChecked = on, Margin = new Thickness(0, 10, 0, 0) };
    }
}
