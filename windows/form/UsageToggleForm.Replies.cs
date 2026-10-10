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

}
