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
            clientPicker = new ClientPickerForm(clients, selected, SaveClientAsync, provider == "claude" ? "Claude Code" : "Codex");
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
        if(clientSwitching)return false;
        clientSwitching=true;
        UpdateReviewControls();
        UpdateRefreshButtons();
        try
        {
            // Finish existing reads before switching their source. Timers cannot start new ones meanwhile.
            while(usageBusy||monitorBusy||busy||reviewBusy)
            {
                if(IsDisposed||exiting)return false;
                await Task.Delay(40);
            }
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
            clientSwitching=false;
            await RunCommandAsync("ui-status");
            await RefreshAllAsync();
            return true;
        }
        catch (Exception error)
        {
            if (clientPicker != null && !clientPicker.IsDisposed) clientPicker.ShowFailure(error.Message);
            return false;
        }
        finally { clientSwitching=false;UpdateReviewControls();UpdateRefreshButtons(); }
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

}
