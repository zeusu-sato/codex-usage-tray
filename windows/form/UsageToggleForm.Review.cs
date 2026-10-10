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
    private void UpdateReviewControls()
    {
        if (IsDisposed || exiting) return;
        reviewButton.Visible = clientAvailable;
        reviewButton.Enabled = clientAvailable && !reviewBusy && !clientSwitching;
        reviewMenu.Enabled = clientAvailable && !reviewBusy && !clientSwitching;
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
        string state = provider=="claude"?Path.Combine(dataDirectory,"providers","claude"):dataDirectory;
        string reviews = CanonicalPaths.Existing(Path.Combine(state, "reviews"))
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

    private async Task CheckReviewAsync(bool manual)
    {
        if (reviewBusy || clientSwitching || !clientAvailable || String.IsNullOrEmpty(currentVersionSignature) || IsDisposed || exiting) return;
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

}
