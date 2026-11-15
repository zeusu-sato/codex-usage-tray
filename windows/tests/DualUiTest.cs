using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

public sealed class DualUiSession {
    public Form Host;
    public Thread Thread;
    public Exception Failure;
    public readonly ManualResetEventSlim Finished = new ManualResetEventSlim();
}

public static partial class DualUiTest {
    const BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic;

    static object Field(object target, string name) {
        return target.GetType().GetField(name, Fields).GetValue(target);
    }
    static Form[] Views(Form host) { return (Form[])Field(host, "views"); }
    static TabControl Tabs(Form host) { return (TabControl)Field(host, "tabs"); }
    static void Require(bool condition, string message) {
        if (!condition) throw new InvalidOperationException(message);
    }
    static object Invoke(DualUiSession session, Func<object> action) {
        if (session.Failure != null) throw new InvalidOperationException("UI thread failed", session.Failure);
        if (session.Finished.IsSet) throw new InvalidOperationException("UI loop ended unexpectedly");
        return session.Host.Invoke(action);
    }
    public static DualUiSession Start(string assembly, string backend, string data) {
        var ready = new TaskCompletionSource<DualUiSession>();
        var session = new DualUiSession();
        session.Thread = new Thread(delegate() {
            EventWaitHandle wake = null;
            try {
                Application.EnableVisualStyles();
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException, true);
                Type type = Assembly.LoadFile(assembly).GetType("UsageTrayHost", true);
                wake = new EventWaitHandle(false, EventResetMode.AutoReset);
                using (Form host = (Form)Activator.CreateInstance(type, new object[] { null, backend, data, false, wake })) {
                    session.Host = host;
                    host.StartPosition = FormStartPosition.Manual;
                    host.Location = new Point(-20000, -20000);
                    host.ShowInTaskbar = false;
                    foreach (Form view in Views(host)) {
                        ((NotifyIcon)Field(view, "trayIcon")).Visible = false;
                        view.GetType().GetField("reviewRunner", Fields).SetValue(view,
                            new Action<string>(delegate { throw new InvalidOperationException("Unexpected review launch"); }));
                    }
                    type.GetMethod("Prepare").Invoke(host, null);
                    // Signal only after the dedicated STA message loop is serving callbacks.
                    host.BeginInvoke(new Action(delegate { ready.TrySetResult(session); }));
                    Application.Run(host);
                }
            } catch (Exception error) {
                session.Failure = error;
                ready.TrySetException(error);
            } finally {
                if (wake != null) wake.Dispose();
                session.Finished.Set();
            }
        });
        session.Thread.IsBackground = true;
        session.Thread.SetApartmentState(ApartmentState.STA);
        session.Thread.Start();
        if (!ready.Task.Wait(15000)) throw new TimeoutException("UI message loop did not start");
        return ready.Task.GetAwaiter().GetResult();
    }
    public static string BusyState(DualUiSession session) {
        return (string)Invoke(session, delegate {
            var busy = new List<string>();
            Form[] views = Views(session.Host);
            for (int index = 0; index < views.Length; index++) {
                if (!(bool)Field(views[index], "initialized")) busy.Add(index + ":startup");
                foreach (string name in new string[] { "busy", "usageBusy", "monitorBusy", "reviewBusy", "reportBusy", "clientSelectionBusy" })
                    if ((bool)Field(views[index], name)) busy.Add(index + ":" + name);
            }
            return String.Join(", ", busy.ToArray());
        });
    }
    public static void VerifyInitial(DualUiSession session) {
        Invoke(session, delegate {
            Form[] views = Views(session.Host);
            Require(Tabs(session.Host).TabPages.Count == 2, "Provider tabs missing");
            Require(views[0].Controls["Heading"].Text == "Codex Usage" && views[1].Controls["Heading"].Text == "Claude Usage", "Provider heading mismatch");
            Require(views[0].Controls["UsageRemaining"].Text == "68%" && views[1].Controls["UsageRemaining"].Text == "24%", "Provider amounts crossed or did not load");
            Require(views[0].Controls["UsageRemaining"].ForeColor.ToArgb() == Color.FromArgb(28,111,85).ToArgb(), "Codex forecast color mismatch");
            Require(views[1].Controls["UsageRemaining"].ForeColor.ToArgb() == Color.FromArgb(157,104,0).ToArgb(), "Claude forecast color mismatch");
            return null;
        });
    }
    public static Task EnableClaude(DualUiSession session) {
        return (Task)Invoke(session, delegate {
            Form view = Views(session.Host)[1];
            return view.GetType().GetMethod("RunCommandAsync", Fields).Invoke(view, new object[] { "ui-enable" });
        });
    }
    public static void VerifyToggle(DualUiSession session) {
        Invoke(session, delegate {
            Form[] views = Views(session.Host);
            Require(((CheckBox)views[1].Controls["UsageToggle"]).Checked && !((CheckBox)views[0].Controls["UsageToggle"]).Checked, "Toggle crossed providers");
            return null;
        });
    }
    public static void OpenProvider(DualUiSession session, int index) {
        Invoke(session, delegate {
            ((Action)Field(Views(session.Host)[index], "HostOpen"))();
            Require(Tabs(session.Host).SelectedIndex == index && session.Host.Visible, "Tray did not open its provider tab");
            return null;
        });
    }
    public static void VerifyUpdateOnOpen(DualUiSession session) {
        Invoke(session, delegate {
            var host=session.Host; var type=host.GetType();
            var last=type.GetField("lastUpdateCheck", Fields);
            var checking=type.GetField("checkingUpdate", Fields);
            var open=type.GetMethod("OpenProvider", Fields);
            DateTime recent=DateTime.UtcNow; last.SetValue(host,recent);
            open.Invoke(host,new object[]{0});
            Require((DateTime)last.GetValue(host)==recent, "Recent update check repeated");
            DateTime old=DateTime.UtcNow.AddMinutes(-11); last.SetValue(host,old);
            checking.SetValue(host,true); open.Invoke(host,new object[]{0});
            Require((DateTime)last.GetValue(host)==old, "Concurrent update check started");
            checking.SetValue(host,false); open.Invoke(host,new object[]{0});
            Require((DateTime)last.GetValue(host)>old, "Opening did not start update check");
            return null;
        });
    }
}
