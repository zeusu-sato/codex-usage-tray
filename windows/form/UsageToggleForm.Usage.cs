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
    private void UpdateRefreshButtons()
    {
        if (IsDisposed || exiting) return;
        bool available = !monitorBusy && !usageBusy && !clientSwitching;
        checkNow.Enabled = available;
        refreshUsage.Enabled = available;
    }

    private async Task CheckUsageAsync()
    {
        if (usageBusy || clientSwitching || IsDisposed || exiting) return;
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
        Icon next = TraySymbols.Create(remaining, ForecastColor(remaining, status), provider);
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
        if(!TopLevel)return;
        // Scrollbars affect ClientSize; always derive width from the design size, never from a prior layout.
        ClientSize = new Size((int)(456 * scale), Math.Min(availableHeight, wantedHeight));
    }

    private float DeviceDpiScale()
    {
        using (Graphics graphics = CreateGraphics()) return graphics.DpiY / 96F;
    }

}
