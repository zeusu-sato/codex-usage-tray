Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
public static class PublicUiTest {
    public static readonly List<string> Requests = new List<string>();
    public static readonly List<string> Reports = new List<string>();
    public static int Attempts;
    public static bool FailLaunch;
    public static Form Start(string assembly, string backend, string data) {
        return Start(assembly, backend, data, 0);
    }
    public static Form Start(string assembly, string backend, string data, int loopDelayMilliseconds) {
        var ready = new TaskCompletionSource<Form>();
        var thread = new Thread(delegate() {
            try {
                Application.EnableVisualStyles();
                Type type = Assembly.LoadFile(assembly).GetType("UsageToggleForm", true);
                var wake = new EventWaitHandle(false, EventResetMode.AutoReset);
                Form form = (Form)Activator.CreateInstance(type, new object[] { null, backend, data, false, wake });
                form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-20000, -20000);
                form.ShowInTaskbar = false;
                ((NotifyIcon)Field(form, "trayIcon")).Visible = false;
                SetField(form, "reviewPresenter", new Action<Form>(Present));
                SetField(form, "clientPresenter", new Action<Form>(Present));
                SetField(form, "reviewRunner", new Action<string>(Launch));
                SetField(form, "reportOpener", new Action<string>(OpenReport));
                type.GetMethod("Prepare").Invoke(form, null);
                ready.SetResult(form);
                // Exercise a caller reaching Wait-Idle before the UI loop starts.
                if (loopDelayMilliseconds > 0) Thread.Sleep(loopDelayMilliseconds);
                Application.Run(form);
                wake.Dispose();
            } catch (Exception error) { ready.TrySetException(error); }
        });
        thread.IsBackground = true; thread.SetApartmentState(ApartmentState.STA); thread.Start();
        return ready.Task.GetAwaiter().GetResult();
    }
    private static void Present(Form form) {
        form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-20000, -20000);
        form.ShowInTaskbar = false; form.Show();
    }
    private static void Launch(string request) {
        Attempts++; if (FailLaunch) throw new InvalidOperationException("Fixture launch failure"); Requests.Add(request);
    }
    private static void OpenReport(string path) { Reports.Add(path); }
    public static object Field(Form form, string name) { return form.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form); }
    public static string BusyState(Form form) {
        return (string)form.Invoke(new Func<string>(delegate {
            // Startup and all busy flags change on this thread. Independent reads
            // could combine pre-startup idle flags with initialized=true and return early.
            if (!(bool)Field(form, "initialized")) return "startup";
            var names = new List<string>();
            foreach (string name in new string[] { "busy", "usageBusy", "monitorBusy", "reviewBusy", "reportBusy", "clientSelectionBusy" })
                if ((bool)Field(form, name)) names.Add(name);
            return String.Join(", ", names.ToArray());
        }));
    }
    public static void SetField(Form form, string name, object value) { form.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(form, value); }
    public static object Call(Form form, string method, object[] args) {
        return form.Invoke(new Func<object>(delegate { return form.GetType().GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(form, args); }));
    }
    public static void Click(Control control) {
        control.Invoke(new Action(delegate {
            Button button = control as Button;
            if (button != null) button.PerformClick();
            else typeof(Control).GetMethod("OnClick", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(control, new object[] { EventArgs.Empty });
        }));
    }
    public static void Select(ComboBox box, int index) { box.Invoke(new Action(delegate { box.SelectedIndex = index; })); }
    public static bool Space(CheckBox box) {
        return (bool)box.Invoke(new Func<bool>(delegate {
            box.Focus();
            typeof(Control).GetMethod("OnKeyDown", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(box, new object[] { new KeyEventArgs(Keys.Space) });
            typeof(Control).GetMethod("OnKeyUp", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(box, new object[] { new KeyEventArgs(Keys.Space) });
            return box.Checked;
        }));
    }
    public static void CaptureControl(Control control, string path) {
        control.Invoke(new Action(delegate {
            using (Bitmap bitmap = new Bitmap(control.Width, control.Height)) {
                control.DrawToBitmap(bitmap, new Rectangle(0, 0, control.Width, control.Height)); bitmap.Save(path);
            }
        }));
    }
    public static void UnownedShortcut(string assembly, string path, string target) {
        Assembly.LoadFile(assembly).GetType("StartupShortcuts", true).GetMethod("Save")
            .Invoke(null, new object[] { path, target, "", Path.GetDirectoryName(target), "Unrelated shortcut" });
    }
    public static void Dispose(Form form) { if (!form.IsDisposed) form.Invoke(new Action(form.Dispose)); }
    public static void Close(Form form) { form.Invoke(new Action(form.Close)); }
    public static void Escape(Form form) {
        form.Invoke(new Action(delegate { typeof(Form).GetMethod("ProcessDialogKey", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(form, new object[] { Keys.Escape }); }));
    }
    public static void Screenshot(Form form, string path) {
        form.Invoke(new Action(delegate {
            using (Bitmap bitmap = new Bitmap(form.Width, form.Height)) {
                form.DrawToBitmap(bitmap, new Rectangle(0, 0, form.Width, form.Height)); bitmap.Save(path);
            }
        }));
    }
    public static void SaveIcon(Form form, string path) {
        form.Invoke(new Action(delegate { using (Bitmap bitmap = ((Icon)Field(form, "usageIcon")).ToBitmap()) bitmap.Save(path); }));
    }
    public static void CheckDynamicSwitchPaint(Form form) {
        form.Invoke(new Action(delegate {
            Label usage = (Label)form.Controls["UsageDetail"];
            Label monitor = (Label)form.Controls["MonitorStatus"];
            Control toggle = form.Controls["UsageToggle"];
            string oldUsage = usage.Text, oldMonitor = monitor.Text;
            MethodInfo resize = form.GetType().GetMethod("ResizeForText", BindingFlags.Instance | BindingFlags.NonPublic);
            try {
                for (int iteration = 0; iteration < 12; iteration++) {
                    usage.Text = iteration % 2 == 0 ? "Short fixture value" : String.Join("\n", new string[] { "Fixture window 1", "Fixture window 2", "Fixture reset time", "Fixture explanation" });
                    monitor.Text = iteration % 2 == 0 ? "Short monitor text" : new string('M', 250);
                    resize.Invoke(form, null);
                    form.Update(); toggle.Invalidate(); toggle.Update();
                    foreach (Control other in form.Controls)
                        if (other is Label && other.Visible && other.Bounds.IntersectsWith(toggle.Bounds))
                            throw new InvalidOperationException("A relaid-out label overlaps the switch: " + other.Name);
                    using (Bitmap bitmap = new Bitmap(toggle.Width, toggle.Height)) {
                        toggle.DrawToBitmap(bitmap, new Rectangle(0, 0, toggle.Width, toggle.Height));
                        foreach (Point corner in new Point[] { Point.Empty, new Point(bitmap.Width - 1, 0), new Point(0, bitmap.Height - 1), new Point(bitmap.Width - 1, bitmap.Height - 1) })
                            if (bitmap.GetPixel(corner.X, corner.Y).ToArgb() != form.BackColor.ToArgb())
                                throw new InvalidOperationException("Switch corners retained transparent/stale parent painting.");
                    }
                }
            } finally { usage.Text = oldUsage; monitor.Text = oldMonitor; resize.Invoke(form, null); }
        }));
    }
    public static int IconBackground(Form form) {
        return (int)form.Invoke(new Func<int>(delegate {
            using (Bitmap bitmap = ((Icon)Field(form, "usageIcon")).ToBitmap()) return bitmap.GetPixel(0, 0).ToArgb();
        }));
    }
    public static IntPtr Window(int pid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr handle, IntPtr state) {
            uint owner; GetWindowThreadProcessId(handle, out owner);
            var title = new StringBuilder(256); GetWindowText(handle, title, title.Capacity);
            if (owner == pid && title.ToString() == "Codex + Claude Usage") { found = handle; return false; }
            return true;
        }, IntPtr.Zero); return found;
    }
    public static void MoveOffscreen(IntPtr handle) { SetWindowPos(handle, IntPtr.Zero, -20000, -20000, 0, 0, 0x0015); }
    public static void Hide(IntPtr handle) { ShowWindow(handle, 0); }
    private delegate bool EnumCallback(IntPtr window, IntPtr state);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumCallback callback, IntPtr state);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder title, int length);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr handle, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
'@
