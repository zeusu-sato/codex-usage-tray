using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string backend = Path.Combine(Application.StartupPath, "backend", "CodexUsageBackend.exe");
        string python = null;
        string dataDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexUsageTray");
        bool startInTray = false;
        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                if ((args[i] == "--backend" || args[i] == "--python" || args[i] == "--data-dir") && i + 1 < args.Length)
                {
                    string option = args[i];
                    string path = Path.GetFullPath(args[++i]);
                    if (option == "--backend") backend = path;
                    else if (option == "--python") python = path;
                    else dataDirectory = path;
                }
                else if (args[i] == "--tray") startInTray = true;
                else throw new ArgumentException("起動オプションを確認してください。");
            }
            // Different extracted versions share one resident instance for the same user data.
            dataDirectory = CanonicalPaths.DataDirectory(dataDirectory);
            string instanceName;
            using (SHA256 hash = SHA256.Create())
                instanceName = "Local\\CodexUsageTray." + BitConverter.ToString(hash.ComputeHash(
                    Encoding.UTF8.GetBytes(Path.GetFullPath(dataDirectory).TrimEnd(Path.DirectorySeparatorChar).ToUpperInvariant()))).Replace("-", "");
            bool firstInstance;
            using (Mutex instance = new Mutex(true, instanceName, out firstInstance))
            using (EventWaitHandle showWindow = new EventWaitHandle(false, EventResetMode.AutoReset, instanceName + ".Show"))
            {
                if (!firstInstance)
                {
                    if (!startInTray) showWindow.Set();
                    return;
                }
                try
                {
                    using (UsageToggleForm form = new UsageToggleForm(python, backend, dataDirectory, startInTray, showWindow))
                    {
                        form.Prepare();
                        Application.Run(form);
                    }
                }
                finally { instance.ReleaseMutex(); }
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Codex Usage Tray", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

internal static class CanonicalPaths
{
    public static string DataDirectory(string path)
    {
        path = Path.GetFullPath(path);
        Directory.CreateDirectory(path);
        return Existing(path);
    }

    public static string Existing(string path)
    {
        path = Path.GetFullPath(path);
        // Open with no data access, sharing reads/writes/deletion. BACKUP_SEMANTICS
        // allows directory handles; following links gives the same target as Python resolve().
        using (Microsoft.Win32.SafeHandles.SafeFileHandle handle = CreateFile(path, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero))
        {
            if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            StringBuilder buffer = new StringBuilder(512);
            for (int attempt = 0; attempt < 3; attempt++)
            {
                uint length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Capacity, 0);
                if (length == 0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                if (length >= buffer.Capacity)
                {
                    buffer = new StringBuilder(checked((int)length + 1));
                    continue;
                }
                string final = buffer.ToString();
                if (final.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) final = @"\\" + final.Substring(8);
                else if (final.StartsWith(@"\\?\", StringComparison.Ordinal)) final = final.Substring(4);
                return Path.GetFullPath(final);
            }
            throw new IOException("保存先の実体パスを確認できませんでした。");
        }
    }

    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFile(string name, uint access, uint share,
        IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", EntryPoint = "GetFinalPathNameByHandleW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(Microsoft.Win32.SafeHandles.SafeFileHandle handle,
        StringBuilder path, uint length, uint flags);
}

internal static class StartupShortcuts
{
    public static bool Matches(string path, string target, string arguments, string description)
    {
        object instance = new ShellLink();
        try
        {
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)instance).Load(path, 0);
            IShellLinkW link = (IShellLinkW)instance;
            StringBuilder actualTarget = new StringBuilder(32768);
            StringBuilder actualArguments = new StringBuilder(32768);
            StringBuilder actualDescription = new StringBuilder(1024);
            link.GetPath(actualTarget, actualTarget.Capacity, IntPtr.Zero, 4);
            link.GetArguments(actualArguments, actualArguments.Capacity);
            link.GetDescription(actualDescription, actualDescription.Capacity);
            return String.Equals(actualDescription.ToString(), description, StringComparison.Ordinal)
                && String.Equals(Path.GetFileName(actualTarget.ToString()), Path.GetFileName(target), StringComparison.OrdinalIgnoreCase)
                && String.Equals(actualArguments.ToString(), arguments, StringComparison.OrdinalIgnoreCase);
        }
        finally { Marshal.FinalReleaseComObject(instance); }
    }

    public static void Save(string path, string target, string arguments, string workingDirectory, string description)
    {
        object instance = new ShellLink();
        try
        {
            IShellLinkW link = (IShellLinkW)instance;
            link.SetPath(target);
            link.SetArguments(arguments);
            link.SetWorkingDirectory(workingDirectory);
            link.SetDescription(description);
            link.SetIconLocation(target, 0);
            link.SetShowCmd(7);
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)instance).Save(path, true);
        }
        finally { Marshal.FinalReleaseComObject(instance); }
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class ShellLink { }

    // Vtable order follows the Unicode Shell Link interface; no ANSI path conversion.
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int length, IntPtr findData, uint flags);
        void GetIDList(out IntPtr itemList);
        void SetIDList(IntPtr itemList);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder description, int length);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string description);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder directory, int length);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder arguments, int length);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int command);
        void SetShowCmd(int command);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int length, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr owner, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }
}

internal sealed class ToggleSwitch : CheckBox
{
    public ToggleSwitch()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint
            | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw
            | ControlStyles.Opaque, true);
        Appearance = Appearance.Normal;
        AutoSize = false;
        BackColor = Color.FromArgb(247, 249, 250);
        AccessibleRole = AccessibleRole.CheckButton;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        // Clear the full control, including rounded corners, after moves/resizes.
        // Transparent CheckBox painting can replay stale sibling text from its parent.
        e.Graphics.Clear(Parent == null ? BackColor : Parent.BackColor);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        float scale = e.Graphics.DpiX / 96F;
        float padding = 4F * scale;
        float height = Math.Min(32F * scale, Height - 2F * padding);
        RectangleF track = new RectangleF(padding, (Height - height) / 2F, Width - 2F * padding, height);
        if (track.Width < height || height <= 4F) return;
        bool known = Text == "ON" || Text == "OFF";
        Color fill = !known ? Color.FromArgb(234, 238, 240)
            : !Enabled ? (Checked ? Color.FromArgb(159, 187, 176) : Color.FromArgb(218, 224, 228))
            : Checked ? Color.FromArgb(28, 111, 85) : Color.FromArgb(105, 117, 126);
        Color stateText = known && Enabled ? Color.White : Color.FromArgb(73, 85, 93);
        using (GraphicsPath shape = new GraphicsPath())
        {
            shape.AddArc(track.Left, track.Top, height, height, 90, 180);
            shape.AddArc(track.Right - height, track.Top, height, height, 270, 180);
            shape.CloseFigure();
            using (Brush background = new SolidBrush(fill)) e.Graphics.FillPath(background, shape);
            using (Pen outline = new Pen(!known || !Enabled ? Color.FromArgb(174, 185, 192) : fill, scale))
                e.Graphics.DrawPath(outline, shape);
        }
        if (known)
        {
            float inset = 3F * scale;
            float diameter = height - 2F * inset;
            float left = Checked ? track.Right - inset - diameter : track.Left + inset;
            RectangleF thumb = new RectangleF(left, track.Top + inset, diameter, diameter);
            using (Brush white = new SolidBrush(Enabled ? Color.White : Color.FromArgb(247, 249, 250)))
                e.Graphics.FillEllipse(white, thumb);
            RectangleF label = Checked
                ? RectangleF.FromLTRB(track.Left + inset, track.Top, thumb.Left - inset, track.Bottom)
                : RectangleF.FromLTRB(thumb.Right + inset, track.Top, track.Right - inset, track.Bottom);
            TextRenderer.DrawText(e.Graphics, Checked ? "ON" : "OFF", Font, Rectangle.Round(label), stateText,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        }
        else
        {
            // A missing/unfinished backend result is visibly unknown, never a false OFF.
            TextRenderer.DrawText(e.Graphics, Text, Font, Rectangle.Round(track), stateText,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        }
        if (Focused && ShowFocusCues)
            ControlPaint.DrawFocusRectangle(e.Graphics, new Rectangle(1, 1, Width - 2, Height - 2),
                SystemColors.Highlight, Parent == null ? SystemColors.Control : Parent.BackColor);
    }

    protected override void OnPaintBackground(PaintEventArgs e) { e.Graphics.Clear(Parent == null ? BackColor : Parent.BackColor); }
    protected override void OnCheckedChanged(EventArgs e) { base.OnCheckedChanged(e); Invalidate(); }
    protected override void OnTextChanged(EventArgs e) { base.OnTextChanged(e); Invalidate(); }
    protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Cursor = Enabled ? Cursors.Hand : Cursors.Default; Invalidate(); }
    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
}

internal sealed class UsageToggleForm : Form
{
    private readonly string python;
    private readonly string backend;
    private readonly string dataDirectory;
    private readonly Label summary;
    private readonly Label detail;
    private readonly Label expiry;
    private readonly CheckBox toggle;
    private readonly Label monitorStatus;
    private readonly Label usageValue;
    private readonly Label usageTitle;
    private readonly Label usageDetail;
    private readonly Label usageForecast;
    private readonly Label usageChecked;
    private readonly Label mitigationHeading;
    private readonly Label trayHint;
    private readonly Button refreshUsage;
    private readonly Button reviewButton;
    private readonly Button reportButton;
    private readonly Label reviewFeedback;
    private readonly NotifyIcon trayIcon;
    private readonly ContextMenuStrip trayMenu;
    private readonly ToolStripMenuItem checkNow;
    private readonly ToolStripMenuItem reviewMenu;
    private readonly ToolStripMenuItem reportMenu;
    private readonly ToolStripMenuItem clientMenu;
    private readonly ToolStripMenuItem startupMenu;
    private readonly System.Windows.Forms.Timer monitorTimer;
    private readonly System.Windows.Forms.Timer usageTimer;
    private readonly EventWaitHandle showWindowEvent;
    private readonly object backendLock = new object();
    private readonly object usageLock = new object();
    private readonly object processLock = new object();
    private readonly HashSet<BackendJob> activeJobs = new HashSet<BackendJob>();
    private Icon usageIcon;
    private RegisteredWaitHandle showWindowWait;
    private bool busy;
    private bool monitorBusy;
    private bool usageBusy;
    private bool reviewBusy;
    private bool reportBusy;
    private bool clientMismatch;
    private bool clientAvailable;
    private bool clientSelectionBusy;
    private bool clientSelectionPrompted;
    private bool acknowledgementBusy;
    private bool initialized;
    private bool enabled;
    private bool showRequested;
    private bool exiting;
    private string pendingBalloonSignature;
    private DateTime pendingBalloonAt;
    private string pendingAcknowledgement;
    private string displayedSignature;
    private string usageTooltip = "Codex Usage: 残量を確認しています";
    private string monitorTooltipSuffix = "";
    private string lastUsageDetail;
    private string lastUsageValue;
    private string currentVersionSignature;
    private string promptedSignature;
    private ReviewPromptForm reviewPrompt;
    private Action<string> reviewRunner;
    private Action<Form> reviewPresenter;
    private Action<Form> clientPresenter;
    private Action<string> reportOpener;
    private ClientPickerForm clientPicker;
    private string startupDirectory;
    private const string StartupDescription = "Codex Usage Tray managed startup";

    public UsageToggleForm(string pythonPath, string backendPath, string stateDirectory, bool startInTray, EventWaitHandle showWindow)
    {
        python = pythonPath;
        backend = backendPath;
        dataDirectory = CanonicalPaths.DataDirectory(stateDirectory);
        startupDirectory = Environment.GetFolderPath(Environment.SpecialFolder.Startup);
        reviewRunner = LaunchReviewRunner;
        reviewPresenter = delegate(Form prompt) { prompt.Show(this); };
        clientPresenter = delegate(Form picker) { picker.Show(this); };
        reportOpener = OpenReportDocument;
        showRequested = !startInTray;
        showWindowEvent = showWindow;
        Text = "Codex Usage Tray";
        Name = "CodexUsageTray";
        AccessibleName = Text;
        Font = new Font("Yu Gothic UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        ClientSize = new Size(456, 580);
        AutoScroll = true;
        BackColor = Color.FromArgb(247, 249, 250);
        ForeColor = Color.FromArgb(32, 41, 48);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ShowInTaskbar = !startInTray;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        Label header = new Label();
        header.Name = "Heading";
        header.Text = "Codex Usage";
        header.Font = new Font(Font.FontFamily, 18F, FontStyle.Bold);
        header.Location = new Point(24, 22);
        header.Size = new Size(408, 38);

        usageValue = new Label();
        usageValue.Name = "UsageRemaining";
        usageValue.AccessibleName = "Codexの残り使用枠";
        usageValue.Text = "?";
        usageValue.Font = new Font(Font.FontFamily, 34F, FontStyle.Bold);
        usageValue.Location = new Point(20, 65);
        usageValue.Size = new Size(260, 70);
        usageValue.ForeColor = Color.FromArgb(94, 106, 115);

        refreshUsage = new Button();
        refreshUsage.Name = "RefreshUsage";
        refreshUsage.AccessibleName = "使用枠とバージョンを今すぐ確認";
        refreshUsage.Text = "更新";
        refreshUsage.Location = new Point(356, 84);
        refreshUsage.Size = new Size(76, 32);
        refreshUsage.TabIndex = 0;
        refreshUsage.Click += async delegate { await RefreshAllAsync(); };

        usageTitle = new Label();
        usageTitle.Name = "UsageTitle";
        usageTitle.AccessibleName = "使用枠の状態";
        usageTitle.Text = "残量を確認しています…";
        usageTitle.Font = new Font(Font.FontFamily, 10.5F, FontStyle.Bold);
        usageTitle.AutoSize = true;
        usageTitle.Location = new Point(24, 138);
        usageTitle.MaximumSize = new Size(408, 0);

        usageDetail = new Label();
        usageDetail.Name = "UsageDetail";
        usageDetail.AccessibleName = "使用枠とリセット日時";
        usageDetail.AutoSize = true;
        usageDetail.Location = new Point(24, 166);
        usageDetail.MaximumSize = new Size(408, 0);
        usageDetail.Font = new Font(Font.FontFamily, 9F);

        usageForecast = new Label();
        usageForecast.Name = "UsageForecast";
        usageForecast.AccessibleName = "リセットまでの見通し";
        usageForecast.AutoSize = true;
        usageForecast.MaximumSize = new Size(408, 0);
        usageForecast.Font = new Font(Font.FontFamily, 9F);
        usageForecast.ForeColor = UsageColor(null);
        usageForecast.Text = "見通し: 残量を確認しています";

        usageChecked = new Label();
        usageChecked.Name = "UsageChecked";
        usageChecked.AccessibleName = "使用枠の最終確認";
        usageChecked.AutoSize = true;
        usageChecked.Location = new Point(24, 204);
        usageChecked.MaximumSize = new Size(408, 0);
        usageChecked.Font = new Font(Font.FontFamily, 9F);
        usageChecked.ForeColor = Color.FromArgb(94, 106, 115);

        mitigationHeading = new Label();
        mitigationHeading.Name = "MitigationHeading";
        mitigationHeading.Text = "追加対策";
        mitigationHeading.AutoSize = true;
        mitigationHeading.Location = new Point(24, 246);
        mitigationHeading.Font = new Font(Font.FontFamily, 11F, FontStyle.Bold);

        summary = new Label();
        summary.Name = "StatusTitle";
        summary.AccessibleName = "設定の状態";
        summary.Text = "状態を確認しています…";
        summary.Location = new Point(24, 78);
        summary.Size = new Size(274, 48);
        summary.TextAlign = ContentAlignment.MiddleLeft;

        toggle = new ToggleSwitch();
        toggle.Name = "UsageToggle";
        toggle.AccessibleName = "Usage対策の有効・無効";
        toggle.AccessibleDescription = "ONは有効、OFFは無効です。Spaceキーで切り替えます。";
        toggle.AutoCheck = false;
        toggle.Text = "確認中";
        toggle.Location = new Point(310, 78);
        toggle.Size = new Size(122, 46);
        toggle.TextAlign = ContentAlignment.MiddleCenter;
        toggle.Font = new Font(Font.FontFamily, 12F, FontStyle.Bold);
        toggle.Enabled = false;
        toggle.TabIndex = 1;
        toggle.Click += async delegate { await RunCommandAsync(enabled ? "ui-disable" : "ui-enable"); };

        detail = new Label();
        detail.Name = "StatusDetail";
        detail.AccessibleName = "設定の説明";
        detail.AutoSize = true;
        detail.Location = new Point(24, 145);
        detail.MaximumSize = new Size(408, 0);

        expiry = new Label();
        expiry.Name = "ExpiryLabel";
        expiry.AccessibleName = "自動停止の条件";
        expiry.AutoSize = true;
        expiry.Location = new Point(24, 236);
        expiry.MaximumSize = new Size(408, 0);
        expiry.ForeColor = Color.FromArgb(94, 106, 115);
        expiry.Font = new Font(Font.FontFamily, 9F);

        reviewButton = new Button();
        reviewButton.Name = "ReviewWithAi";
        reviewButton.AccessibleName = "AIで対策を見直す";
        reviewButton.Text = "AIで見直す…";
        reviewButton.Size = new Size(156, 32);
        reviewButton.Location = new Point(24, 300);
        reviewButton.TabIndex = 2;
        reviewButton.Visible = false;
        reviewButton.Click += async delegate { await CheckReviewAsync(true); };

        reportButton = new Button();
        reportButton.Name = "OpenReviewReport";
        reportButton.AccessibleName = "見直し結果を開く";
        reportButton.Text = "見直し結果を開く";
        reportButton.Size = new Size(184, 32);
        reportButton.Location = new Point(192, 300);
        reportButton.TabIndex = 3;
        reportButton.Visible = false;
        reportButton.Click += async delegate { await OpenLatestReviewAsync(); };

        reviewFeedback = new Label();
        reviewFeedback.Name = "ReviewStatus";
        reviewFeedback.AccessibleName = "AI見直しの状態";
        reviewFeedback.AutoSize = true;
        reviewFeedback.MaximumSize = new Size(408, 0);
        reviewFeedback.Location = new Point(24, 338);
        reviewFeedback.Font = new Font(Font.FontFamily, 9F);
        reviewFeedback.ForeColor = Color.FromArgb(94, 106, 115);

        monitorStatus = new Label();
        monitorStatus.Name = "MonitorStatus";
        monitorStatus.AccessibleName = "バージョン確認";
        monitorStatus.AutoSize = true;
        monitorStatus.Location = new Point(24, 274);
        monitorStatus.MaximumSize = new Size(408, 0);
        monitorStatus.Font = new Font(Font.FontFamily, 9F);
        monitorStatus.ForeColor = Color.FromArgb(94, 106, 115);
        monitorStatus.Text = "バージョンを確認しています…";

        trayHint = new Label();
        trayHint.Name = "TrayVisibilityHint";
        trayHint.Text = "常に表示するには、^ 内のアイコンをタスクバーへドラッグ。";
        trayHint.AutoSize = true;
        trayHint.MaximumSize = new Size(408, 0);
        trayHint.Location = new Point(24, 544);
        trayHint.Font = new Font(Font.FontFamily, 8.5F);
        trayHint.ForeColor = Color.FromArgb(94, 106, 115);

        trayMenu = new ContextMenuStrip();
        trayMenu.Items.Add("開く", null, delegate { OpenWindow(); });
        checkNow = new ToolStripMenuItem("今すぐ確認");
        checkNow.Click += async delegate { await RefreshAllAsync(); };
        trayMenu.Items.Add(checkNow);
        reviewMenu = new ToolStripMenuItem("AIで見直す…");
        reviewMenu.Enabled = false;
        reviewMenu.Click += async delegate { await CheckReviewAsync(true); };
        trayMenu.Items.Add(reviewMenu);
        reportMenu = new ToolStripMenuItem("見直し結果を開く");
        reportMenu.Click += async delegate { await OpenLatestReviewAsync(); };
        trayMenu.Items.Add(reportMenu);
        clientMenu = new ToolStripMenuItem("Codexを選ぶ…");
        clientMenu.Click += async delegate { await ChooseClientAsync(true); };
        trayMenu.Items.Add(clientMenu);
        startupMenu = new ToolStripMenuItem("Windowsログイン時に起動");
        startupMenu.CheckOnClick = false;
        startupMenu.Click += delegate { ToggleStartup(); };
        trayMenu.Items.Add(startupMenu);
        trayMenu.Opening += delegate { RefreshStartupState(); };
        trayMenu.Items.Add(new ToolStripSeparator());
        trayMenu.Items.Add("終了", null, delegate { exiting = true; Close(); });
        trayIcon = new NotifyIcon();
        trayIcon.Icon = Icon;
        trayIcon.Text = usageTooltip;
        trayIcon.ContextMenuStrip = trayMenu;
        trayIcon.DoubleClick += delegate { OpenWindow(); };
        trayIcon.BalloonTipClicked += delegate { OpenWindow(); };
        trayIcon.BalloonTipShown += async delegate
        {
            if (String.IsNullOrEmpty(pendingBalloonSignature)) return;
            displayedSignature = pendingBalloonSignature;
            pendingAcknowledgement = pendingBalloonSignature;
            pendingBalloonSignature = null;
            await AcknowledgeNotificationAsync();
        };
        trayIcon.Visible = true;
        UpdateUsageIcon(null);

        monitorTimer = new System.Windows.Forms.Timer();
        monitorTimer.Interval = 15 * 60 * 1000;
        monitorTimer.Tick += async delegate { await CheckMonitorAsync(); };
        usageTimer = new System.Windows.Forms.Timer();
        usageTimer.Interval = 5 * 60 * 1000;
        usageTimer.Tick += async delegate { await CheckUsageAsync(); };

        Controls.AddRange(new Control[] { header, usageValue, refreshUsage, usageTitle, usageDetail, usageForecast,
            usageChecked, mitigationHeading, summary, toggle, detail, expiry, reviewButton, reportButton, reviewFeedback, monitorStatus, trayHint });
        Activated += async delegate
        {
            if (initialized && !busy) await RunCommandAsync("ui-status");
        };
        FormClosing += delegate(object sender, FormClosingEventArgs args)
        {
            if (args.CloseReason == CloseReason.UserClosing && !exiting)
            {
                args.Cancel = true;
                showRequested = false;
                Hide();
            }
        };
        ResizeForText();
    }

    public void Prepare()
    {
        // Create a message-loop handle without showing a --tray window.
        IntPtr handle = Handle;
        showWindowWait = ThreadPool.RegisterWaitForSingleObject(showWindowEvent, delegate
        {
            try { BeginInvoke(new Action(OpenWindow)); }
            catch (InvalidOperationException) { }
        }, null, Timeout.Infinite, false);
        BeginInvoke(new Action(async delegate
        {
            initialized = true;
            monitorTimer.Start();
            usageTimer.Start();
            await Task.WhenAll(RunCommandAsync("ui-status"), CheckMonitorAsync(), CheckUsageAsync());
        }));
    }

    protected override void SetVisibleCore(bool value)
    {
        base.SetVisibleCore(value && showRequested);
    }

    private void OpenWindow()
    {
        if (IsDisposed || exiting) return;
        showRequested = true;
        ShowInTaskbar = true;
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Show();
        // A --tray process may inherit SW_HIDE; explicitly restore the native window.
        ShowWindowNative(Handle, 9);
        Activate();
        BringToFront();
        SetForegroundWindow(Handle);
    }

    [DllImport("user32.dll", EntryPoint = "ShowWindow")]
    private static extern bool ShowWindowNative(IntPtr window, int command);
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            exiting = true;
            if (showWindowWait != null) showWindowWait.Unregister(null);
            if (monitorTimer != null) monitorTimer.Dispose();
            if (usageTimer != null) usageTimer.Dispose();
            if (reviewPrompt != null) { reviewPrompt.Dispose(); reviewPrompt = null; }
            if (clientPicker != null) { clientPicker.Dispose(); clientPicker = null; }
            lock (processLock)
            {
                foreach (BackendJob job in activeJobs) job.Dispose();
                activeJobs.Clear();
            }
            if (trayIcon != null) { trayIcon.Visible = false; trayIcon.Dispose(); }
            if (usageIcon != null) { usageIcon.Dispose(); usageIcon = null; }
            if (trayMenu != null) trayMenu.Dispose();
        }
        base.Dispose(disposing);
    }

    private async Task RunCommandAsync(string command)
    {
        if (busy || IsDisposed) return;
        busy = true;
        toggle.Enabled = false;
        UseWaitCursor = true;
        try
        {
            BackendReply reply = await Task.Run(() => ReadUiReply(CallBackend(command)));
            if (IsDisposed) return;
            enabled = reply.Enabled;
            toggle.Checked = enabled;
            toggle.Text = enabled ? "ON" : "OFF";
            summary.Text = reply.Title;
            detail.Text = reply.Detail;
            expiry.Text = reply.ExpiresLabel;
            toggle.Enabled = enabled || reply.CanEnable;
            if (!reply.Ok)
            {
                // The returned state remains authoritative, but the failure must be visible.
                summary.Text = String.IsNullOrWhiteSpace(reply.Title) ? "設定を変更できませんでした" : reply.Title;
                detail.ForeColor = Color.FromArgb(148, 47, 43);
            }
            else detail.ForeColor = ForeColor;
            ResizeForText();
        }
        catch (Exception error)
        {
            if (IsDisposed) return;
            toggle.Checked = false;
            toggle.Text = "未確認";
            toggle.Enabled = false;
            summary.Text = "状態を確認できません";
            detail.Text = error.Message + "\nこのウィンドウを開き直すと再確認できます。";
            detail.ForeColor = Color.FromArgb(148, 47, 43);
            expiry.Text = "";
            ResizeForText();
        }
        finally
        {
            busy = false;
            if (!IsDisposed) UseWaitCursor = false;
        }
    }

    private async Task CheckMonitorAsync()
    {
        if (monitorBusy || IsDisposed || exiting) return;
        monitorBusy = true;
        UpdateRefreshButtons();
        try
        {
            await AcknowledgeNotificationAsync();
            MonitorReply reply = await Task.Run(() => ReadMonitorReply(CallBackend("monitor-check")));
            if (IsDisposed || exiting) return;
            monitorStatus.Text = String.Join("\n", new string[] {
                reply.Title, reply.Detail, reply.BaselineLabel, reply.CurrentLabel,
                reply.CheckedLabel, "15分ごとに確認 · AIは使用しません"
            });
            monitorStatus.ForeColor = reply.Ok ? Color.FromArgb(94, 106, 115) : Color.FromArgb(148, 47, 43);
            monitorTooltipSuffix = !reply.Ok ? " / 版不明" : (reply.Mismatch ? " / 版変更" : "");
            clientAvailable = reply.Ok && !String.IsNullOrEmpty(reply.Signature);
            clientMismatch = reply.Ok && reply.Mismatch;
            currentVersionSignature = clientAvailable ? reply.Signature : null;
            UpdateReviewControls();
            UpdateTrayTooltip();
            ResizeForText();
            // A suppressed Windows notification may produce no Shown/Closed event.
            if (!String.IsNullOrEmpty(pendingBalloonSignature)
                && DateTime.UtcNow - pendingBalloonAt >= TimeSpan.FromMinutes(1)) pendingBalloonSignature = null;
            if (reply.Ok && reply.Mismatch && reply.Alert && !String.IsNullOrEmpty(reply.Signature)
                && reply.Signature != displayedSignature && String.IsNullOrEmpty(pendingBalloonSignature))
            {
                pendingBalloonSignature = reply.Signature;
                pendingBalloonAt = DateTime.UtcNow;
                trayIcon.BalloonTipTitle = Shorten(reply.Title, 63);
                trayIcon.BalloonTipText = Shorten(reply.Detail + "\n" + reply.BaselineLabel + "\n" + reply.CurrentLabel, 255);
                trayIcon.BalloonTipIcon = ToolTipIcon.Info;
                try { trayIcon.ShowBalloonTip(10000); }
                catch { pendingBalloonSignature = null; throw; }
            }
            else if (reply.Ok && !reply.Mismatch)
            {
                pendingBalloonSignature = null;
                displayedSignature = null;
            }
            // A detected client change also changes whether the switch can apply.
            if (reply.Ok && !busy) await RunCommandAsync("ui-status");
            if (reply.Ok && reply.Mismatch) await CheckReviewAsync(false);
            if (reply.NeedsClientSelection) await ChooseClientAsync(false);
        }
        catch (Exception error)
        {
            if (IsDisposed || exiting) return;
            monitorStatus.Text = "バージョンを確認できません\n" + error.Message + "\n15分後に再確認します。";
            monitorStatus.ForeColor = Color.FromArgb(148, 47, 43);
            monitorTooltipSuffix = " / 版不明";
            clientMismatch = false;
            clientAvailable = false;
            currentVersionSignature = null;
            UpdateReviewControls();
            UpdateTrayTooltip();
            ResizeForText();
        }
        finally
        {
            monitorBusy = false;
            UpdateRefreshButtons();
        }
    }

    private async Task AcknowledgeNotificationAsync()
    {
        if (acknowledgementBusy || String.IsNullOrEmpty(pendingAcknowledgement) || IsDisposed || exiting) return;
        acknowledgementBusy = true;
        string signature = pendingAcknowledgement;
        try
        {
            Dictionary<string, object> reply = await Task.Run(() => CallBackend("monitor-notified", "--signature", signature));
            if (!RequireBoolean(reply, "ok")) throw new InvalidOperationException("通知の記録を保存できませんでした。");
            if (pendingAcknowledgement == signature) pendingAcknowledgement = null;
        }
        catch (Exception)
        {
            // Retry recording at the next check without repeating the same visible notification.
            if (!IsDisposed && !exiting)
            {
                monitorStatus.Text += "\n通知の記録は次回の確認時に再試行します。";
                ResizeForText();
            }
        }
        finally { acknowledgementBusy = false; }
    }

    private async Task RefreshAllAsync()
    {
        await Task.WhenAll(CheckMonitorAsync(), CheckUsageAsync());
    }

    private void UpdateReviewControls()
    {
        if (IsDisposed || exiting) return;
        reviewButton.Visible = clientAvailable;
        reviewButton.Enabled = clientAvailable && !reviewBusy;
        reviewMenu.Enabled = clientAvailable && !reviewBusy;
        reportButton.Visible = clientAvailable;
        reportButton.Enabled = !reportBusy;
        if (reviewPrompt != null && !reviewPrompt.IsDisposed
            && reviewPrompt.Signature != currentVersionSignature)
        {
            reviewPrompt.Dispose();
            reviewPrompt = null;
        }
    }

    private async Task OpenLatestReviewAsync()
    {
        if (reportBusy || IsDisposed || exiting) return;
        reportBusy = true;
        reportButton.Enabled = false;
        reportMenu.Enabled = false;
        try
        {
            Dictionary<string, object> reply = await Task.Run(() => CallBackend("review-latest"));
            if (IsDisposed || exiting) return;
            string message = RequireString(reply, "detail");
            string path = RequireString(reply, "report_path");
            if (!RequireBoolean(reply, "ok") || String.IsNullOrEmpty(path))
            {
                reviewFeedback.Text = message;
                ResizeForText();
                OpenWindow();
                return;
            }
            reportOpener(ValidateReportPath(path));
        }
        catch (Exception error)
        {
            if (IsDisposed || exiting) return;
            reviewFeedback.Text = "見直し結果を開けませんでした。\n" + error.Message;
            ResizeForText();
            OpenWindow();
        }
        finally
        {
            reportBusy = false;
            if (!IsDisposed && !exiting) { reportButton.Enabled = true; reportMenu.Enabled = true; }
        }
    }

    private string ValidateReportPath(string path)
    {
        string report = CanonicalPaths.Existing(path);
        string reviews = CanonicalPaths.Existing(Path.Combine(dataDirectory, "reviews"))
            .TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!report.StartsWith(reviews, StringComparison.OrdinalIgnoreCase)
            || !String.Equals(Path.GetExtension(report), ".md", StringComparison.OrdinalIgnoreCase) || !File.Exists(report))
            throw new InvalidOperationException("このアプリの見直し結果を確認できませんでした。");
        return report;
    }

    private static void OpenReportDocument(string path)
    {
        ProcessStartInfo start = new ProcessStartInfo(path);
        start.UseShellExecute = true;
        using (Process opened = Process.Start(start)) { }
    }

    private async Task ChooseClientAsync(bool manual)
    {
        if (clientSelectionBusy || IsDisposed || exiting) return;
        if (clientPicker != null && !clientPicker.IsDisposed)
        {
            if (manual) clientPicker.Activate();
            return;
        }
        if (!manual && clientSelectionPrompted) return;
        clientSelectionBusy = true;
        clientMenu.Enabled = false;
        try
        {
            Dictionary<string, object> data = await Task.Run(() => CallBackend("client-list"));
            if (IsDisposed || exiting) return;
            if (!RequireBoolean(data, "ok")) throw new InvalidOperationException("Codexの一覧を確認できませんでした。");
            string selected = RequireString(data, "selected_id");
            object rows;
            if (!data.TryGetValue("clients", out rows) || !(rows is System.Collections.IEnumerable) || rows is string)
                throw new InvalidOperationException("Codexの一覧を読み取れませんでした。");
            List<ClientOption> clients = new List<ClientOption>();
            HashSet<string> identifiers = new HashSet<string>(StringComparer.Ordinal);
            foreach (object value in (System.Collections.IEnumerable)rows)
            {
                Dictionary<string, object> row = value as Dictionary<string, object>;
                if (row == null) throw new InvalidOperationException("Codexの一覧を読み取れませんでした。");
                string id = RequireString(row, "id");
                string label = RequireString(row, "label");
                if (String.IsNullOrWhiteSpace(id) || String.IsNullOrWhiteSpace(label) || !identifiers.Add(id))
                    throw new InvalidOperationException("Codexの一覧を読み取れませんでした。");
                clients.Add(new ClientOption(id, label));
            }
            clientSelectionPrompted = true;
            clientPicker = new ClientPickerForm(clients, selected, SaveClientAsync);
            clientPicker.Icon = Icon;
            clientPresenter(clientPicker);
        }
        catch (Exception error)
        {
            if (IsDisposed || exiting) return;
            reviewFeedback.Text = "Codexの選択を準備できませんでした。\n" + error.Message;
            ResizeForText();
            if (manual) OpenWindow();
        }
        finally
        {
            clientSelectionBusy = false;
            if (!IsDisposed && !exiting) clientMenu.Enabled = true;
        }
    }

    private async Task<bool> SaveClientAsync(string clientId)
    {
        try
        {
            Dictionary<string, object> reply = await Task.Run(() => CallBackend("client-select", "--client-id", clientId));
            if (IsDisposed || exiting) return false;
            if (!RequireBoolean(reply, "ok")) throw new InvalidOperationException("Codexの選択を保存できませんでした。");
            promptedSignature = null;
            lastUsageValue = null;
            lastUsageDetail = null;
            usageValue.Text = "?";
            usageTitle.Text = "選択したCodexの残量を確認しています…";
            usageDetail.Text = "";
            usageValue.ForeColor = UsageColor(null);
            usageForecast.Text = "見通し: 現在の残量は未確認です";
            usageForecast.ForeColor = UsageColor(null);
            usageChecked.Text = "";
            usageTooltip = "Codex Usage: 選択した環境を確認中";
            UpdateUsageIcon(null);
            UpdateTrayTooltip();
            await RunCommandAsync("ui-status");
            await RefreshAllAsync();
            return true;
        }
        catch (Exception error)
        {
            if (clientPicker != null && !clientPicker.IsDisposed) clientPicker.ShowFailure(error.Message);
            return false;
        }
    }

    private string StartupShortcutPath()
    {
        return Path.Combine(startupDirectory, "CodexUsageTray-managed.lnk");
    }

    private string StartupArguments()
    {
        string arguments = "--tray --data-dir " + QuoteArgument(dataDirectory);
        string packaged = Path.Combine(Application.StartupPath, "backend", "CodexUsageBackend.exe");
        if (!String.Equals(Path.GetFullPath(backend), Path.GetFullPath(packaged), StringComparison.OrdinalIgnoreCase))
            arguments += " --backend " + QuoteArgument(backend);
        if (!String.IsNullOrEmpty(python)) arguments += " --python " + QuoteArgument(python);
        return arguments;
    }

    private bool StartupEnabled()
    {
        string path = StartupShortcutPath();
        if (!File.Exists(path)) return false;
        return StartupShortcuts.Matches(path, Application.ExecutablePath, StartupArguments(), StartupDescription);
    }

    private void RefreshStartupState()
    {
        try { startupMenu.Checked = StartupEnabled(); startupMenu.ToolTipText = ""; }
        catch { startupMenu.Checked = false; startupMenu.ToolTipText = "自動起動の設定を確認できません。"; }
    }

    private void ToggleStartup()
    {
        try
        {
            SetStartupEnabled(!StartupEnabled());
            RefreshStartupState();
        }
        catch (Exception error)
        {
            MessageBox.Show(this, error.Message, "自動起動を変更できません", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void SetStartupEnabled(bool enable)
    {
        string path = StartupShortcutPath();
        bool owned = StartupEnabled();
        if (File.Exists(path) && !owned)
            throw new InvalidOperationException("同じ名前の別のショートカットがあるため、変更しませんでした。");
        if (!enable)
        {
            if (owned) File.Delete(path);
            return;
        }
        Directory.CreateDirectory(startupDirectory);
        StartupShortcuts.Save(path, Application.ExecutablePath, StartupArguments(), Application.StartupPath, StartupDescription);
        if (!StartupEnabled()) throw new InvalidOperationException("自動起動の保存結果を確認できませんでした。");
    }

    private async Task CheckReviewAsync(bool manual)
    {
        if (reviewBusy || !clientAvailable || String.IsNullOrEmpty(currentVersionSignature) || IsDisposed || exiting) return;
        if (!manual && !clientMismatch) return;
        if (reviewPrompt != null && !reviewPrompt.IsDisposed)
        {
            if (manual) reviewPrompt.Activate();
            return;
        }
        string signature = currentVersionSignature;
        if (!manual && promptedSignature == signature) return;
        reviewBusy = true;
        UpdateReviewControls();
        try
        {
            ReviewReply reply = await Task.Run(() => ReadReviewReply(CallBackend("review-status", "--signature", signature)));
            if (IsDisposed || exiting || currentVersionSignature != signature) return;
            if (!reply.Ok || reply.Signature != signature) throw new InvalidOperationException(reply.Detail);
            if (!reply.CanReview || (!manual && !reply.ShouldPrompt))
            {
                if (manual)
                {
                    reviewFeedback.Text = reply.Title + "\n" + reply.Detail;
                    ResizeForText();
                    OpenWindow();
                }
                return;
            }
            promptedSignature = signature;
            reviewPrompt = new ReviewPromptForm(signature, reply.Detail, async delegate(bool yes)
            {
                return await CompleteReviewDecisionAsync(signature, yes);
            });
            reviewPrompt.Icon = Icon;
            reviewPresenter(reviewPrompt);
        }
        catch (Exception error)
        {
            if (IsDisposed || exiting) return;
            reviewFeedback.Text = "見直しの確認に失敗しました。\n" + error.Message;
            ResizeForText();
            if (manual) OpenWindow();
        }
        finally
        {
            reviewBusy = false;
            UpdateReviewControls();
        }
    }

    private async Task<bool> CompleteReviewDecisionAsync(string signature, bool yes)
    {
        if (reviewBusy || IsDisposed || exiting) return false;
        reviewBusy = true;
        UpdateReviewControls();
        try
        {
            ReviewReply reply = await Task.Run(() => ReadReviewReply(CallBackend("review-decide", "--signature", signature,
                "--decision", yes ? "yes" : "no")));
            if (IsDisposed || exiting) return false;
            if (!reply.Ok || reply.Signature != signature) throw new InvalidOperationException(reply.Detail);
            if (yes)
            {
                if (!Path.IsPathRooted(reply.RequestPath) || !File.Exists(reply.RequestPath))
                    throw new InvalidOperationException("見直しの依頼ファイルを確認できませんでした。");
                // This launch is reachable only from the confirmation's explicit Yes click.
                reviewRunner(reply.RequestPath);
                reviewFeedback.Text = "AIによる見直し用のウィンドウを開きました。";
            }
            else reviewFeedback.Text = "AIによる見直しは開始していません。必要なときに「AIで見直す…」から確認できます。";
            ResizeForText();
            return true;
        }
        catch (Exception error)
        {
            if (IsDisposed || exiting) return false;
            reviewFeedback.Text = (yes ? "見直しを開始できませんでした。\n" : "選択を保存できませんでした。\n") + error.Message;
            ResizeForText();
            if (reviewPrompt != null && !reviewPrompt.IsDisposed)
                reviewPrompt.ShowFailure(error.Message + "\n再試行する場合は、もう一度選んでください。");
            return false;
        }
        finally
        {
            reviewBusy = false;
            UpdateReviewControls();
        }
    }

    private void LaunchReviewRunner(string requestPath)
    {
        ProcessStartInfo start = CreateBackendStart(new string[] { "review-run", "--request", requestPath }, true);
        // The user-requested console continues independently if the tray app closes.
        using (Process launched = Process.Start(start))
        {
            if (launched == null) throw new InvalidOperationException("見直し用ウィンドウを開けませんでした。");
        }
    }

    private void UpdateRefreshButtons()
    {
        if (IsDisposed || exiting) return;
        bool available = !monitorBusy && !usageBusy;
        checkNow.Enabled = available;
        refreshUsage.Enabled = available;
    }

    private async Task CheckUsageAsync()
    {
        if (usageBusy || IsDisposed || exiting) return;
        usageBusy = true;
        UpdateRefreshButtons();
        try
        {
            UsageReply reply = await Task.Run(() => ReadUsageReply(CallBackend("usage-check")));
            if (IsDisposed || exiting) return;
            bool current = reply.Ok && !reply.Stale && !reply.Blocked && reply.RemainingPercent.HasValue;
            usageValue.Text = current ? reply.RemainingPercent.Value.ToString("0.#", CultureInfo.InvariantCulture) + "%" : "?";
            Color forecastColor = ForecastColor(current ? reply.RemainingPercent : null, reply.Forecast.Status);
            usageValue.ForeColor = forecastColor;
            usageTitle.Text = reply.Title;
            usageDetail.Text = reply.Detail;
            usageForecast.ForeColor = forecastColor;
            usageForecast.Text = !current
                ? (reply.Blocked ? "見通し: 利用制限があるため判定できません" : "見通し: 現在の残量は未確認です")
                : reply.RemainingPercent.Value == 0 ? "残量なし: 対象の利用枠の残量は0%です。"
                : "見通し: " + reply.Forecast.Title + (String.IsNullOrEmpty(reply.Forecast.Detail) ? "" : "\n" + reply.Forecast.Detail);
            usageChecked.Text = reply.CheckedLabel + (String.IsNullOrEmpty(reply.CheckedLabel) ? "" : "\n")
                + (reply.Stale ? "現在の残量は未確認 · 5分ごとに再確認" : "5分ごとに更新 · AIは使用しません");
            usageTooltip = reply.Tooltip;
            if (current)
            {
                lastUsageValue = usageValue.Text;
                lastUsageDetail = reply.Detail;
            }
            UpdateForecastIcon(current ? reply.RemainingPercent : null, reply.Forecast.Status);
            UpdateTrayTooltip();
            ResizeForText();
        }
        catch (Exception error)
        {
            if (IsDisposed || exiting) return;
            usageValue.Text = "?";
            usageValue.ForeColor = UsageColor(null);
            usageTitle.Text = "現在の残量を確認できません";
            usageForecast.Text = "見通し: 現在の残量は未確認です";
            usageForecast.ForeColor = UsageColor(null);
            usageDetail.Text = error.Message;
            if (!String.IsNullOrEmpty(lastUsageValue))
                usageDetail.Text += "\n前回の表示（現在の残量は未確認）: " + lastUsageValue + "\n" + lastUsageDetail;
            usageChecked.Text = "5分後に再確認します。";
            usageTooltip = "Codex Usage: 現在の残量は未確認";
            UpdateUsageIcon(null);
            UpdateTrayTooltip();
            ResizeForText();
        }
        finally
        {
            usageBusy = false;
            UpdateRefreshButtons();
        }
    }

    private void UpdateTrayTooltip()
    {
        trayIcon.Text = Shorten(usageTooltip, 63 - monitorTooltipSuffix.Length) + monitorTooltipSuffix;
    }

    private static Color UsageColor(double? remaining)
    {
        return ForecastColor(remaining, "collecting");
    }

    private static Color ForecastColor(double? remaining, string status)
    {
        if (!remaining.HasValue) return Color.FromArgb(94, 106, 115);
        if (remaining.Value == 0 || status == "at_risk") return Color.FromArgb(174, 43, 39);
        if (status == "tight") return Color.FromArgb(157, 104, 0);
        if (status == "comfortable") return Color.FromArgb(28, 111, 85);
        return Color.FromArgb(94, 106, 115);
    }

    private void UpdateUsageIcon(double? remaining)
    {
        UpdateForecastIcon(remaining, "collecting");
    }

    private void UpdateForecastIcon(double? remaining, string status)
    {
        Icon next = CreateForecastIcon(remaining, status);
        Icon previous = usageIcon;
        usageIcon = next;
        trayIcon.Icon = next;
        if (previous != null) previous.Dispose();
    }

    private static Icon CreateUsageIcon(double? remaining)
    {
        return CreateForecastIcon(remaining, "collecting");
    }

    private static Icon CreateForecastIcon(double? remaining, string status)
    {
        // Draw at 2x the common 16px tray size, with strong contrast on either taskbar theme.
        using (Bitmap bitmap = new Bitmap(32, 32))
        using (Graphics graphics = Graphics.FromImage(bitmap))
        using (SolidBrush background = new SolidBrush(ForecastColor(remaining, status)))
        using (SolidBrush track = new SolidBrush(Color.FromArgb(64, 0, 0, 0)))
        using (Font font = new Font("Segoe UI", remaining == 100 ? 17F : 22F, FontStyle.Bold, GraphicsUnit.Pixel))
        using (StringFormat format = new StringFormat(StringFormat.GenericTypographic))
        {
            graphics.Clear(Color.Transparent);
            graphics.SmoothingMode = SmoothingMode.None;
            graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            graphics.FillRectangle(background, 0, 0, 32, 32);
            format.Alignment = StringAlignment.Center;
            format.LineAlignment = StringAlignment.Center;
            string number = remaining.HasValue ? Math.Floor(remaining.Value).ToString(CultureInfo.InvariantCulture) : "?";
            graphics.DrawString(number, font, Brushes.White, new RectangleF(0, -1, 32, 27), format);
            graphics.FillRectangle(track, 2, 27, 28, 3);
            if (remaining.HasValue)
                graphics.FillRectangle(Brushes.White, 2, 27, (float)(28 * remaining.Value / 100), 3);
            IntPtr handle = bitmap.GetHicon();
            try
            {
                using (Icon borrowed = Icon.FromHandle(handle)) return (Icon)borrowed.Clone();
            }
            finally { DestroyIcon(handle); }
        }
    }

    [DllImport("user32.dll")]
    private static extern bool DestroyIcon(IntPtr handle);

    private static string Shorten(string text, int length)
    {
        text = text.Replace('\r', ' ').Replace('\n', ' ');
        return text.Length > length ? text.Substring(0, length - 1) + "…" : text;
    }

    private void ResizeForText()
    {
        float scale = DeviceDpiScale();
        int scrollOffset = AutoScrollPosition.Y;
        usageDetail.Top = usageTitle.Bottom + (int)(6 * scale);
        usageForecast.Top = usageDetail.Bottom + (int)(8 * scale);
        usageForecast.Left = usageDetail.Left;
        usageChecked.Top = usageForecast.Bottom + (int)(8 * scale);
        mitigationHeading.Top = usageChecked.Bottom + (int)(22 * scale);
        summary.Top = mitigationHeading.Bottom + (int)(6 * scale);
        toggle.Top = summary.Top;
        detail.Top = Math.Max(summary.Bottom, toggle.Bottom) + (int)(10 * scale);
        expiry.Top = detail.Bottom + (int)(10 * scale);
        reviewButton.Top = expiry.Bottom + (int)(10 * scale);
        reportButton.Top = reviewButton.Top;
        reviewFeedback.Top = (clientAvailable ? reviewButton.Bottom : expiry.Bottom) + (int)(8 * scale);
        int reviewBottom = String.IsNullOrEmpty(reviewFeedback.Text)
            ? (clientAvailable ? reviewButton.Bottom : expiry.Bottom) : reviewFeedback.Bottom;
        monitorStatus.Top = reviewBottom + (int)(18 * scale);
        trayHint.Top = monitorStatus.Bottom + (int)(18 * scale);
        int wantedHeight = trayHint.Bottom - scrollOffset + (int)(20 * scale);
        int availableHeight = Math.Max((int)(240 * scale), Screen.FromControl(this).WorkingArea.Height - (int)(80 * scale));
        AutoScrollMinSize = new Size(0, wantedHeight);
        // Scrollbars affect ClientSize; always derive width from the design size, never from a prior layout.
        ClientSize = new Size((int)(456 * scale), Math.Min(availableHeight, wantedHeight));
    }

    private float DeviceDpiScale()
    {
        using (Graphics graphics = CreateGraphics()) return graphics.DpiY / 96F;
    }

    private Dictionary<string, object> CallBackend(params string[] arguments)
    {
        bool usage = arguments.Length > 0 && arguments[0] == "usage-check";
        lock (usage ? usageLock : backendLock) return CallBackendLocked(arguments, usage ? 30000 : 10000);
    }

    private Dictionary<string, object> CallBackendLocked(string[] arguments, int timeoutMilliseconds)
    {
        ProcessStartInfo start = CreateBackendStart(arguments, false);
        string output;
        string errors;
        int exitCode;
        using (Process process = new Process())
        using (BackendJob job = new BackendJob())
        {
            process.StartInfo = start;
            lock (processLock)
            {
                if (exiting) throw new OperationCanceledException();
                process.Start();
                try { job.Assign(process); }
                catch
                {
                    try { process.Kill(); } catch (InvalidOperationException) { }
                    throw;
                }
                activeJobs.Add(job);
            }
            try
            {
                Stopwatch watch = Stopwatch.StartNew();
                Task<string> outputTask = process.StandardOutput.ReadToEndAsync();
                Task<string> errorTask = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(timeoutMilliseconds)
                    || !Task.WaitAll(new Task[] { outputTask, errorTask }, Math.Max(0, timeoutMilliseconds - (int)watch.ElapsedMilliseconds)))
                {
                    job.Dispose();
                    process.WaitForExit(1000);
                    throw new InvalidOperationException("確認がタイムアウトしました。");
                }
                output = outputTask.GetAwaiter().GetResult();
                errors = errorTask.GetAwaiter().GetResult();
                exitCode = process.ExitCode;
            }
            finally { lock (processLock) activeJobs.Remove(job); }
        }
        Dictionary<string, object> data;
        try
        {
            data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(output);
            if (data == null) throw new FormatException();
            if (exitCode != 0 && RequireBoolean(data, "ok")) throw new FormatException();
            return data;
        }
        catch (Exception error)
        {
            if (!(error is ArgumentException) && !(error is InvalidOperationException) && !(error is FormatException)) throw;
            // Stderr is captured to avoid blocking, but raw internal paths/tracebacks are not UI copy.
            throw new InvalidOperationException(exitCode != 0 || !String.IsNullOrWhiteSpace(errors)
                ? "設定用プログラムを実行できませんでした。"
                : "設定の応答を読み取れませんでした。");
        }
    }

    private ProcessStartInfo CreateBackendStart(string[] arguments, bool visible)
    {
        if (!File.Exists(backend)) throw new InvalidOperationException("バックエンドが見つかりません。配布ZIPをすべて展開してください。");
        bool script = String.Equals(Path.GetExtension(backend), ".py", StringComparison.OrdinalIgnoreCase);
        if (script && (String.IsNullOrEmpty(python) || !File.Exists(python)))
            throw new InvalidOperationException("開発用のPythonパスを --python で指定してください。");
        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = script ? python : backend;
        StringBuilder commandLine = new StringBuilder();
        if (script) commandLine.Append("-X utf8 ").Append(QuoteArgument(backend)).Append(' ');
        commandLine.Append("--data-dir ").Append(QuoteArgument(dataDirectory));
        foreach (string argument in arguments) commandLine.Append(' ').Append(QuoteArgument(argument));
        start.Arguments = commandLine.ToString();
        start.WorkingDirectory = Path.GetDirectoryName(backend);
        start.UseShellExecute = visible;
        start.CreateNoWindow = !visible;
        start.WindowStyle = visible ? ProcessWindowStyle.Normal : ProcessWindowStyle.Hidden;
        if (!visible)
        {
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
        }
        return start;
    }

    private static BackendReply ReadUiReply(Dictionary<string, object> data)
    {
        try
        {
            BackendReply reply = new BackendReply();
            reply.Ok = RequireBoolean(data, "ok");
            reply.Enabled = RequireBoolean(data, "enabled");
            reply.CanEnable = RequireBoolean(data, "can_enable");
            reply.Title = RequireString(data, "title");
            reply.Detail = RequireString(data, "detail");
            reply.ExpiresLabel = RequireString(data, "expires_label");
            return reply;
        }
        catch (FormatException) { throw new InvalidOperationException("設定の応答を読み取れませんでした。"); }
    }

    private static MonitorReply ReadMonitorReply(Dictionary<string, object> data)
    {
        try
        {
            MonitorReply reply = new MonitorReply();
            reply.Ok = RequireBoolean(data, "ok");
            reply.Mismatch = RequireBoolean(data, "mismatch");
            reply.Alert = RequireBoolean(data, "alert");
            reply.Title = RequireString(data, "title");
            reply.Detail = RequireString(data, "detail");
            reply.CheckedLabel = RequireString(data, "checked_label");
            reply.BaselineLabel = RequireString(data, "baseline_label");
            reply.CurrentLabel = RequireString(data, "current_label");
            reply.Signature = RequireString(data, "signature");
            object selection;
            reply.NeedsClientSelection = data.TryGetValue("needs_client_selection", out selection) && selection is bool && (bool)selection;
            return reply;
        }
        catch (FormatException) { throw new InvalidOperationException("バージョンの応答を読み取れませんでした。"); }
    }

    private static UsageReply ReadUsageReply(Dictionary<string, object> data)
    {
        try
        {
            UsageReply reply = new UsageReply();
            reply.Ok = RequireBoolean(data, "ok");
            reply.Stale = RequireBoolean(data, "stale");
            reply.Title = RequireString(data, "title");
            reply.Detail = RequireString(data, "detail");
            reply.CheckedLabel = RequireString(data, "checked_label");
            reply.Tooltip = RequireString(data, "tooltip");
            object blocked;
            if (data.TryGetValue("blocked", out blocked))
            {
                if (!(blocked is bool)) throw new FormatException();
                reply.Blocked = (bool)blocked;
            }
            reply.Forecast = ReadForecastReply(data);
            object remaining;
            if (!data.TryGetValue("remaining_percent", out remaining)) throw new FormatException();
            if (remaining != null)
            {
                if (!(remaining is int) && !(remaining is long) && !(remaining is double) && !(remaining is decimal))
                    throw new FormatException();
                double percent = Convert.ToDouble(remaining, CultureInfo.InvariantCulture);
                if (Double.IsNaN(percent) || Double.IsInfinity(percent) || percent < 0 || percent > 100)
                    throw new FormatException();
                reply.RemainingPercent = percent;
            }
            return reply;
        }
        catch (FormatException) { throw new InvalidOperationException("使用枠の応答を読み取れませんでした。"); }
    }

    private static ForecastReply ReadForecastReply(Dictionary<string, object> data)
    {
        ForecastReply collecting = new ForecastReply {
            Status = "collecting", Title = "データを集めています",
            Detail = "まだ見通しを判定できません。残量の更新時に再確認します。"
        };
        object raw;
        if (!data.TryGetValue("forecast", out raw) || !(raw is Dictionary<string, object>)) return collecting;
        try
        {
            Dictionary<string, object> forecast = (Dictionary<string, object>)raw;
            string status = RequireString(forecast, "status");
            if (status != "comfortable" && status != "tight" && status != "at_risk"
                && status != "collecting" && status != "unavailable") throw new FormatException();
            string title = RequireString(forecast, "title");
            string detail = RequireString(forecast, "detail");
            if (String.IsNullOrWhiteSpace(title) || title.Length > 200 || detail.Length > 4000) throw new FormatException();
            object window;
            if (!forecast.TryGetValue("window_label", out window) || (window != null && !(window is string))) throw new FormatException();
            CheckForecastNumber(forecast, "observed_hours", Double.MaxValue);
            CheckForecastNumber(forecast, "projected_remaining_percent", 100);
            return new ForecastReply { Status = status, Title = title, Detail = detail };
        }
        catch (FormatException) { return collecting; }
    }

    private static void CheckForecastNumber(Dictionary<string, object> data, string name, double maximum)
    {
        object value;
        if (!data.TryGetValue(name, out value)) throw new FormatException();
        if (value == null) return;
        if (!(value is int) && !(value is long) && !(value is double) && !(value is decimal)) throw new FormatException();
        double number = Convert.ToDouble(value, CultureInfo.InvariantCulture);
        if (Double.IsNaN(number) || Double.IsInfinity(number) || number < 0 || number > maximum) throw new FormatException();
    }

    private static ReviewReply ReadReviewReply(Dictionary<string, object> data)
    {
        try
        {
            ReviewReply reply = new ReviewReply();
            reply.Ok = RequireBoolean(data, "ok");
            reply.ShouldPrompt = RequireBoolean(data, "should_prompt");
            reply.CanReview = RequireBoolean(data, "can_review");
            reply.Title = RequireString(data, "title");
            reply.Detail = RequireString(data, "detail");
            reply.Signature = RequireString(data, "signature");
            reply.RequestPath = RequireString(data, "request_path");
            return reply;
        }
        catch (FormatException) { throw new InvalidOperationException("見直し設定の応答を読み取れませんでした。"); }
    }

    private static bool RequireBoolean(Dictionary<string, object> data, string key)
    {
        object value;
        if (!data.TryGetValue(key, out value) || !(value is bool)) throw new FormatException();
        return (bool)value;
    }

    private static string RequireString(Dictionary<string, object> data, string key)
    {
        object value;
        if (!data.TryGetValue(key, out value) || !(value is string)) throw new FormatException();
        return (string)value;
    }

    private static string QuoteArgument(string argument)
    {
        // Windows command-line quoting; paths with spaces and a trailing backslash are safe.
        StringBuilder quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char value in argument)
        {
            if (value == '\\') { slashes++; continue; }
            if (value == '"') quoted.Append('\\', slashes * 2 + 1);
            else quoted.Append('\\', slashes);
            quoted.Append(value);
            slashes = 0;
        }
        quoted.Append('\\', slashes * 2);
        return quoted.Append('"').ToString();
    }

    private sealed class BackendReply
    {
        public bool Ok;
        public bool Enabled;
        public bool CanEnable;
        public string Title;
        public string Detail;
        public string ExpiresLabel;
    }

    private sealed class MonitorReply
    {
        public bool Ok;
        public bool Mismatch;
        public bool Alert;
        public string Title;
        public string Detail;
        public string CheckedLabel;
        public string BaselineLabel;
        public string CurrentLabel;
        public string Signature;
        public bool NeedsClientSelection;
    }

    private sealed class UsageReply
    {
        public bool Ok;
        public bool Stale;
        public bool Blocked;
        public ForecastReply Forecast;
        public string Title;
        public string Detail;
        public string CheckedLabel;
        public string Tooltip;
        public double? RemainingPercent;
    }

    private sealed class ForecastReply
    {
        public string Status;
        public string Title;
        public string Detail;
    }

    private sealed class ReviewReply
    {
        public bool Ok;
        public bool ShouldPrompt;
        public bool CanReview;
        public string Title;
        public string Detail;
        public string Signature;
        public string RequestPath;
    }

    private sealed class BackendJob : IDisposable
    {
        private IntPtr handle;

        public BackendJob()
        {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new InvalidOperationException("確認用プロセスを準備できませんでした。");
            ExtendedLimits limits = new ExtendedLimits();
            limits.BasicLimitInformation.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            int size = Marshal.SizeOf(typeof(ExtendedLimits));
            IntPtr data = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(limits, data, false);
                if (!SetInformationJobObject(handle, 9, data, (uint)size))
                    throw new InvalidOperationException("確認用プロセスを準備できませんでした。");
            }
            catch { Dispose(); throw; }
            finally { Marshal.FreeHGlobal(data); }
        }

        public void Assign(Process process)
        {
            if (!AssignProcessToJobObject(handle, process.Handle))
                throw new InvalidOperationException("確認用プロセスを管理できませんでした。");
        }

        public void Dispose()
        {
            IntPtr owned = Interlocked.Exchange(ref handle, IntPtr.Zero);
            if (owned != IntPtr.Zero) CloseHandle(owned);
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BasicLimits
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IoCounters
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct ExtendedLimits
        {
            public BasicLimits BasicLimitInformation;
            public IoCounters IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr job, int informationClass, IntPtr data, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);
    }
}

internal sealed class ClientOption
{
    public readonly string Id;
    public readonly string Label;
    public ClientOption(string id, string label) { Id = id; Label = label; }
    public override string ToString() { return Label; }
}

internal sealed class ClientPickerForm : Form
{
    private readonly ComboBox choices;
    private readonly Label failure;
    private readonly Button selectButton;
    private readonly Button cancelButton;
    private readonly Func<string, Task<bool>> save;
    private bool saving;

    public ClientPickerForm(List<ClientOption> clients, string selectedId, Func<string, Task<bool>> selection)
    {
        save = selection;
        Name = "CodexClientPicker";
        Text = "Codexを選ぶ";
        AccessibleName = Text;
        Font = new Font("Yu Gothic UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96, 96);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(500, 246);
        BackColor = Color.FromArgb(247, 249, 250);
        Label explanation = new Label();
        explanation.Text = clients.Count == 0
            ? "対応するCodexが見つかりません。VS CodeまたはInsidersにCodex拡張機能をインストールしてから、再度選んでください。"
            : "監視するCodexを選んでください。\n選択だけではAIは起動しません。";
        explanation.Location = new Point(24, 20);
        explanation.Size = new Size(452, 64);
        choices = new ComboBox();
        choices.Name = "CodexClientChoices";
        choices.AccessibleName = "監視するCodex";
        choices.DropDownStyle = ComboBoxStyle.DropDownList;
        choices.Location = new Point(24, 94);
        choices.Size = new Size(452, 30);
        choices.TabIndex = 0;
        foreach (ClientOption client in clients)
        {
            int index = choices.Items.Add(client);
            if (client.Id == selectedId) choices.SelectedIndex = index;
        }
        failure = new Label();
        failure.Name = "ClientSelectionFailure";
        failure.Location = new Point(24, 136);
        failure.MaximumSize = new Size(452, 0);
        failure.AutoSize = true;
        failure.ForeColor = Color.FromArgb(148, 47, 43);
        selectButton = new Button();
        selectButton.Name = "SelectCodexClient";
        selectButton.Text = "このCodexを使う";
        selectButton.Location = new Point(196, 190);
        selectButton.Size = new Size(144, 34);
        selectButton.Enabled = choices.SelectedIndex >= 0;
        selectButton.TabIndex = 1;
        selectButton.Click += async delegate { await SaveAsync(); };
        cancelButton = new Button();
        cancelButton.Name = "CancelCodexClient";
        cancelButton.Text = "キャンセル";
        cancelButton.Location = new Point(352, 190);
        cancelButton.Size = new Size(124, 34);
        cancelButton.TabIndex = 2;
        cancelButton.Click += delegate { Close(); };
        choices.SelectedIndexChanged += delegate { selectButton.Enabled = !saving && choices.SelectedIndex >= 0; };
        AcceptButton = selectButton;
        CancelButton = cancelButton;
        Controls.AddRange(new Control[] { explanation, choices, failure, selectButton, cancelButton });
        FormClosing += delegate(object sender, FormClosingEventArgs args)
        {
            if (saving && args.CloseReason == CloseReason.UserClosing) args.Cancel = true;
        };
    }

    public void ShowFailure(string text)
    {
        failure.Text = text;
        float scale;
        using (Graphics graphics = CreateGraphics()) scale = graphics.DpiY / 96F;
        selectButton.Top = Math.Max((int)(190 * scale), failure.Bottom + (int)(16 * scale));
        cancelButton.Top = selectButton.Top;
        ClientSize = new Size((int)(500 * scale), cancelButton.Bottom + (int)(22 * scale));
    }

    private async Task SaveAsync()
    {
        if (saving || choices.SelectedIndex < 0) return;
        saving = true;
        choices.Enabled = false;
        selectButton.Enabled = false;
        cancelButton.Enabled = false;
        bool saved = false;
        try { saved = await save(((ClientOption)choices.SelectedItem).Id); }
        finally
        {
            saving = false;
            if (!IsDisposed)
            {
                choices.Enabled = true;
                selectButton.Enabled = choices.SelectedIndex >= 0;
                cancelButton.Enabled = true;
            }
        }
        if (saved && !IsDisposed) Close();
    }
}

internal sealed class ReviewPromptForm : Form
{
    public string Signature { get; private set; }
    private readonly Func<bool, Task<bool>> decide;
    private readonly Label description;
    private readonly Label failure;
    private readonly Button yesButton;
    private readonly Button noButton;
    private bool submitting;
    private bool completed;

    public ReviewPromptForm(string signature, string detail, Func<bool, Task<bool>> decision)
    {
        Signature = signature;
        decide = decision;
        Name = "AiReviewConfirmation";
        Text = "AIで対策を見直しますか";
        AccessibleName = Text;
        Font = new Font("Yu Gothic UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96, 96);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(500, 248);
        BackColor = Color.FromArgb(247, 249, 250);

        Label heading = new Label();
        heading.Text = Text;
        heading.Font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        heading.Location = new Point(24, 20);
        heading.Size = new Size(452, 36);
        description = new Label();
        description.Name = "ReviewPromptDetail";
        description.Text = detail;
        description.AutoSize = true;
        description.MaximumSize = new Size(452, 0);
        description.Location = new Point(24, 64);
        failure = new Label();
        failure.Name = "ReviewPromptFailure";
        failure.AutoSize = true;
        failure.MaximumSize = new Size(452, 0);
        failure.Location = new Point(24, 140);
        failure.ForeColor = Color.FromArgb(148, 47, 43);

        yesButton = new Button();
        yesButton.Name = "ReviewYes";
        yesButton.Text = "はい";
        yesButton.AccessibleName = "はい、AIで見直しを開始する";
        yesButton.Size = new Size(112, 34);
        yesButton.Location = new Point(240, 190);
        yesButton.TabIndex = 1;
        yesButton.Click += async delegate { await SubmitAsync(true); };
        noButton = new Button();
        noButton.Name = "ReviewNo";
        noButton.Text = "いいえ";
        noButton.AccessibleName = "いいえ、AIを開始しない";
        noButton.Size = new Size(112, 34);
        noButton.Location = new Point(364, 190);
        noButton.TabIndex = 0;
        noButton.Click += async delegate { await SubmitAsync(false); };
        AcceptButton = noButton;
        CancelButton = noButton;
        noButton.DialogResult = DialogResult.None;
        Controls.AddRange(new Control[] { heading, description, failure, yesButton, noButton });
        Shown += delegate { Arrange(); noButton.Focus(); };
        FormClosing += async delegate(object sender, FormClosingEventArgs args)
        {
            if (!completed && args.CloseReason == CloseReason.UserClosing)
            {
                args.Cancel = true;
                await SubmitAsync(false);
            }
        };
    }

    public void ShowFailure(string text)
    {
        failure.Text = text;
        Arrange();
    }

    private void Arrange()
    {
        float scale;
        using (Graphics graphics = CreateGraphics()) scale = graphics.DpiY / 96F;
        failure.Top = description.Bottom + (int)(12 * scale);
        int top = Math.Max((int)(164 * scale), failure.Bottom + (int)(24 * scale));
        yesButton.Top = top;
        noButton.Top = top;
        ClientSize = new Size((int)(500 * scale), noButton.Bottom + (int)(24 * scale));
    }

    private async Task SubmitAsync(bool yes)
    {
        if (submitting || completed || IsDisposed) return;
        submitting = true;
        yesButton.Enabled = false;
        noButton.Enabled = false;
        try
        {
            if (await decide(yes))
            {
                if (IsDisposed) return;
                completed = true;
                Close();
            }
        }
        finally
        {
            submitting = false;
            if (!IsDisposed)
            {
                yesButton.Enabled = true;
                noButton.Enabled = true;
                noButton.Focus();
            }
        }
    }
}
