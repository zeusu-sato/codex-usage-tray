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

internal sealed partial class UsageToggleForm
{
    public UsageToggleForm(string pythonPath, string backendPath, string stateDirectory, bool startInTray, EventWaitHandle showWindow, string selectedProvider)
    {
        if(selectedProvider!="codex"&&selectedProvider!="claude")throw new ArgumentException("Unknown provider");
        provider=selectedProvider;
        if(provider=="claude")usageTooltip="Claude Code Usage: 残量を確認しています";
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
        Text = provider=="claude"?"Claude Code Usage Tray":"Codex Usage Tray";
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
        if(provider=="claude")header.Text="Claude Usage";
        header.Font = new Font(Font.FontFamily, 18F, FontStyle.Bold);
        header.Location = new Point(24, 22);
        header.Size = new Size(408, 38);

        usageValue = new Label();
        usageValue.Name = "UsageRemaining";
        usageValue.AccessibleName = "Codexの残り使用枠";
        if(provider=="claude")usageValue.AccessibleName="Claude Codeの残り使用枠";
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
        if(provider=="claude")clientMenu.Text="Claude Codeを選ぶ…";
        clientMenu.Click += async delegate { await ChooseClientAsync(true); };
        trayMenu.Items.Add(clientMenu);
        startupMenu = new ToolStripMenuItem("Windowsログイン時に起動");
        startupMenu.CheckOnClick = false;
        startupMenu.Click += delegate { ToggleStartup(); };
        trayMenu.Items.Add(startupMenu);
        trayMenu.Opening += delegate { RefreshStartupState(); };
        trayMenu.Items.Add(new ToolStripSeparator());
        trayMenu.Items.Add("終了", null, delegate { if(HostExit!=null){HostExit();return;} exiting = true; Close(); });
        trayIcon = new NotifyIcon();
        trayIcon.Icon = Icon;
        trayIcon.Text = usageTooltip;
        trayIcon.ContextMenuStrip = trayMenu;
        trayIcon.DoubleClick += delegate { OpenWindow(); };
        trayIcon.MouseClick += delegate(object sender, MouseEventArgs e) { if(e.Button==MouseButtons.Left)OpenWindow(); };
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
        Activated += delegate { RefreshPolicy(); };
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

}
