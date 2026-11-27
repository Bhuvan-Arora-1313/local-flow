using System;
using System.Threading;
using System.Windows;

namespace LocalFlowRemote
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            using var single = new Mutex(true, @"Local\LocalFlowRemote", out bool first);
            if (!first)
            {
                MessageBox.Show("LocalFlow is already running. Its icon is in the taskbar tray (bottom-right, maybe under ^).",
                    "LocalFlow");
                return;
            }
            System.Windows.Forms.Application.EnableVisualStyles();
            var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            app.DispatcherUnhandledException += (_, e) =>
            {
                Log.Write("unhandled: " + e.Exception);
                e.Handled = true;          // keep dictation alive; the log has the details
            };
            AppDomain.CurrentDomain.UnhandledException += (_, e) => Log.Write("fatal: " + e.ExceptionObject);
            app.Startup += (_, _) => new Controller(app.Dispatcher).Start();
            app.Run();
        }
    }
}
