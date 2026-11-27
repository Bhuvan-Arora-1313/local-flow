using System;
using System.Diagnostics;
using System.Drawing;
using System.Reflection;
using WF = System.Windows.Forms;

namespace LocalFlowRemote
{
    /// <summary>The tray icon and its menu -- the Windows twin of the Mac's menu-bar item.</summary>
    internal sealed class Tray : IDisposable
    {
        private readonly Controller _c;
        private readonly WF.NotifyIcon _icon;
        private readonly WF.ToolStripMenuItem _status, _hint, _pasteLast, _retry, _hotkey, _live, _sounds, _startup;

        public Tray(Controller c)
        {
            _c = c;
            var menu = new WF.ContextMenuStrip();
            _status = new WF.ToolStripMenuItem { Enabled = false };
            _hint = new WF.ToolStripMenuItem { Enabled = false };
            _pasteLast = new WF.ToolStripMenuItem("Paste last dictation", null, async (_, _) => await _c.PasteLast());
            _retry = new WF.ToolStripMenuItem("Retry last recording", null, async (_, _) => await _c.RetryFailed());
            _hotkey = new WF.ToolStripMenuItem("Hotkey");
            foreach (var h in Config.Hotkeys)
            {
                var id = h.Id;
                _hotkey.DropDownItems.Add(new WF.ToolStripMenuItem(h.Label, null, (_, _) =>
                {
                    _c.Cfg.Hotkey = id;
                    _c.ApplySettings();
                }) { Tag = id });
            }
            _live = new WF.ToolStripMenuItem("Show live text while speaking", null, (_, _) =>
            {
                _c.Cfg.LiveText = !_c.Cfg.LiveText;
                _c.ApplySettings();
            });
            _sounds = new WF.ToolStripMenuItem("Sounds", null, (_, _) =>
            {
                _c.Cfg.Sounds = !_c.Cfg.Sounds;
                _c.ApplySettings();
            });
            _startup = new WF.ToolStripMenuItem("Start with Windows", null, (_, _) =>
            {
                _c.Cfg.StartWithWindows = !_c.Cfg.StartWithWindows;
                _c.ApplySettings();
            });

            menu.Items.Add(_status);
            menu.Items.Add(_hint);
            menu.Items.Add(new WF.ToolStripSeparator());
            menu.Items.Add(_pasteLast);
            menu.Items.Add(_retry);
            menu.Items.Add(new WF.ToolStripSeparator());
            menu.Items.Add(_hotkey);
            menu.Items.Add(_live);
            menu.Items.Add(_sounds);
            menu.Items.Add(_startup);
            menu.Items.Add(new WF.ToolStripSeparator());
            menu.Items.Add(new WF.ToolStripMenuItem("Settings…", null, (_, _) => _c.OpenSettings()));
            menu.Items.Add(new WF.ToolStripMenuItem("Check connection", null, async (_, _) => await _c.CheckHealth()));
            menu.Items.Add(new WF.ToolStripMenuItem("Restart LocalFlow on the Mac", null, async (_, _) => await _c.RestartMac()));
            menu.Items.Add(new WF.ToolStripMenuItem("Open log", null, (_, _) =>
            {
                try { Process.Start(new ProcessStartInfo(Log.FilePath) { UseShellExecute = true }); } catch { }
            }));
            menu.Items.Add(new WF.ToolStripSeparator());
            menu.Items.Add(new WF.ToolStripMenuItem("Quit LocalFlow", null, (_, _) => _c.Quit()));
            menu.Opening += (_, _) => Refresh();

            _icon = new WF.NotifyIcon
            {
                Icon = LoadIcon(),
                ContextMenuStrip = menu,
                Visible = true,
            };
            _icon.MouseClick += (_, e) =>
            {
                if (e.Button == WF.MouseButtons.Left) _c.OpenSettings();
            };
            Refresh();
        }

        private static Icon LoadIcon()
        {
            try
            {
                using var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("localflow.ico");
                if (s != null) return new Icon(s, WF.SystemInformation.SmallIconSize);
            }
            catch { }
            return SystemIcons.Application;
        }

        public void Refresh()
        {
            var cfg = _c.Cfg;
            _status.Text = (_c.Connected ? "● " : "○ ") + _c.Status;
            _hint.Text = cfg.Mode switch
            {
                "push_to_talk" => $"Hold {cfg.HotkeyLabel} to talk",
                "toggle" => $"Tap {cfg.HotkeyLabel} to start / stop",
                _ => $"Hold {cfg.HotkeyLabel} to talk · double-tap for hands-free",
            };
            _pasteLast.Enabled = _c.LastText.Length > 0;
            _retry.Enabled = _c.FailedAudio != null;
            foreach (WF.ToolStripMenuItem i in _hotkey.DropDownItems) i.Checked = (string?)i.Tag == cfg.Hotkey;
            _live.Checked = cfg.LiveText;
            _sounds.Checked = cfg.Sounds;
            _startup.Checked = cfg.StartWithWindows;
            var tip = "LocalFlow: " + _c.Status;
            _icon.Text = tip.Length > 63 ? tip[..62] + "…" : tip;
        }

        public void Dispose()
        {
            _icon.Visible = false;
            _icon.Dispose();
        }
    }
}
