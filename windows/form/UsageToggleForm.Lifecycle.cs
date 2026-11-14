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
    internal async void RefreshPolicy()
    {
        if (initialized && !busy && !exiting && !Disposing) await RunCommandAsync("ui-status");
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
        if(HostOpen!=null){HostOpen();return;}
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
            helpTooltip.Dispose();
        }
        base.Dispose(disposing);
    }

    private async Task RunCommandAsync(string command)
    {
        if (busy || clientSwitching || IsDisposed || exiting || Disposing) return;
        busy = true;
        toggle.Enabled = false;
        UseWaitCursor = true;
        try
        {
            BackendReply reply = await Task.Run(() => ReadUiReply(CallBackend(command)));
            if (IsDisposed || exiting || Disposing) return;
            enabled = reply.Enabled;
            toggle.Checked = enabled;
            toggle.Text = enabled ? "ON" : "OFF";
            summary.Text = reply.Title;
            detail.Text = reply.Detail;
            helpTooltip.SetToolTip(detail, reply.Tooltip);
            helpTooltip.SetToolTip(summary, reply.Tooltip);
            helpTooltip.SetToolTip(toggle, reply.ExpiresLabel);
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
            if (IsDisposed || exiting || Disposing) return;
            toggle.Checked = false;
            toggle.Text = "未確認";
            toggle.Enabled = false;
            summary.Text = "状態を確認できません";
            detail.Text = error.Message + "\nこのウィンドウを開き直すと再確認できます。";
            detail.ForeColor = Color.FromArgb(148, 47, 43);
            helpTooltip.SetToolTip(detail, "");
            helpTooltip.SetToolTip(summary, "");
            helpTooltip.SetToolTip(toggle, "");
            ResizeForText();
        }
        finally
        {
            busy = false;
            if (!IsDisposed && !exiting && !Disposing) UseWaitCursor = false;
        }
    }

    private async Task CheckMonitorAsync()
    {
        if (monitorBusy || clientSwitching || IsDisposed || exiting) return;
        monitorBusy = true;
        UpdateRefreshButtons();
        try
        {
            await AcknowledgeNotificationAsync();
            MonitorReply reply = await Task.Run(() => ReadMonitorReply(CallBackend("monitor-check")));
            if (IsDisposed || exiting) return;
            // The label appears only when a stopped policy needs action or the check fails; otherwise it is a tooltip.
            bool needsAction = !reply.Ok || (reply.Mismatch && reply.PolicyStopped);
            monitorStatus.Text = !reply.Ok ? reply.Title + "\n" + reply.Detail
                : needsAction ? reply.Title + "\n" + reply.CurrentLabel : "";
            helpTooltip.SetToolTip(mitigationHeading, String.Join("\n", new string[] {
                reply.Title, reply.Mismatch ? reply.Detail : "", reply.BaselineLabel, reply.CurrentLabel, reply.CheckedLabel,
                "残量は5分ごと、バージョンは15分ごとに確認します。通常監視はAI推論を使いません。"
            }).Replace("\n\n", "\n"));
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
            monitorStatus.Text = "バージョンを確認できません\n" + error.Message;
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
                monitorStatus.Text = (monitorStatus.Text + "\n通知の記録は次回の確認時に再試行します。").TrimStart();
                ResizeForText();
            }
        }
        finally { acknowledgementBusy = false; }
    }

    private async Task RefreshAllAsync()
    {
        await Task.WhenAll(CheckMonitorAsync(), CheckUsageAsync());
    }

}
