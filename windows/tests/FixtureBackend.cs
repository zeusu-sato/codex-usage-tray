// Test-only console backend. It never contacts Codex, a network, or a model.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Web.Script.Serialization;

internal static class FixtureBackend
{
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    private static string folder;
    private static Dictionary<string, object> config;

    private static int Main(string[] args)
    {
        Dictionary<string, string> options = new Dictionary<string, string>();
        string command = null;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i].StartsWith("--") && i + 1 < args.Length) options[args[i]] = args[++i];
            else if (command == null) command = args[i];
        }
        if (command == "sleep-child") { Thread.Sleep(120000); return 0; }
        if (!options.TryGetValue("--data-dir", out folder)) return 2;
        Directory.CreateDirectory(folder);
        config = Read("fixture.json");
        File.WriteAllText(Path.Combine(folder, "command-" + Guid.NewGuid().ToString("N") + ".txt"), command ?? "missing");
        Dictionary<string, object> state = Read("fixture-state.json");
        string selected = Value(state, "selected_id", "");
        bool ambiguous = Flag(config, "ambiguous") && selected == "";
        bool mismatch = Flag(config, "mismatch");
        string signature = new String(mismatch ? 'b' : 'a', 64);
        object result;
        switch (command)
        {
            case "ui-status":
            case "ui-enable":
            case "ui-disable":
                bool configured = Flag(config, "configured");
                if (command != "ui-status") { state["enabled"] = command == "ui-enable"; Save("fixture-state.json", state); }
                bool enabled = configured && !mismatch && Flag(state, "enabled");
                result = new { ok = true, enabled = enabled, can_enable = configured && !mismatch,
                    title = configured ? (enabled ? "追加対策は有効です" : "追加対策は無効です") : "追加対策は未設定です",
                    detail = configured ? "これはテスト専用の対策です。" : "Codexの標準動作を使用します。",
                    expires_label = "追加対策を自動でインストールしません。" };
                break;
            case "monitor-check":
                result = new { ok = !ambiguous, mismatch = mismatch && !ambiguous,
                    alert = mismatch && !ambiguous && Value(state, "notified", "") != signature,
                    title = ambiguous ? "監視するCodexを選んでください" : (mismatch ? "Codexの変更を検知しました" : "記録したバージョンと一致しています"),
                    detail = "テスト環境（実際のCodexには接続しません）", checked_label = "最終確認: テスト時刻",
                    baseline_label = "初回記録: Codex fixture-1", current_label = "現在: Codex fixture-1",
                    signature = ambiguous ? "" : signature, needs_client_selection = ambiguous };
                break;
            case "monitor-notified":
                state["notified"] = options["--signature"]; Save("fixture-state.json", state);
                result = new { ok = true };
                break;
            case "usage-check":
                if (Flag(config, "slow"))
                {
                    ProcessStartInfo child = new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName, "sleep-child");
                    child.UseShellExecute = false; child.CreateNoWindow = true;
                    using (Process process = Process.Start(child)) File.WriteAllText(Path.Combine(folder, "child.pid"), process.Id.ToString());
                    File.WriteAllText(Path.Combine(folder, "parent.pid"), Process.GetCurrentProcess().Id.ToString());
                    Thread.Sleep(Flag(config, "hang") ? 120000 : 6000);
                }
                object percent;
                config.TryGetValue("remaining", out percent);
                bool stale = Flag(config, "stale");
                result = new { ok = !stale && percent != null, stale = stale, remaining_percent = percent,
                    title = percent == null ? "テスト状態: 残量は未確認" : "Codexの残り使用枠",
                    detail = (stale ? "前回の記録です。" : "") + "週間枠のリセット: 09/15 15:29 JST",
                    checked_label = "最終取得: テスト時刻", tooltip = stale ? "Codex Usage 未確認" : "Codex 残り" + percent + "% / 09/15 15:29 JST",
                    windows = new object[0] };
                break;
            case "review-status":
            case "review-decide":
                string reviewStatus = Value(state, "review_status", "unanswered");
                string requestPath = "";
                if (command == "review-decide")
                {
                    reviewStatus = options["--decision"] == "yes" ? "prepared" : "declined";
                    state["review_status"] = reviewStatus;
                    Save("fixture-state.json", state);
                    if (reviewStatus == "prepared")
                    {
                        requestPath = Path.Combine(folder, "fixture-review-request.json");
                        File.WriteAllText(requestPath, "{\"fixture_only\":true}");
                    }
                }
                result = new { ok = true, should_prompt = Flag(config, "prompt") && reviewStatus == "unanswered",
                    can_review = true, status = reviewStatus, title = "AIで対策を見直しますか",
                    detail = "その時点で利用可能な最上位モデル・最大推論強度で見直します。はいではUsageを使用します。",
                    signature = options["--signature"], request_path = requestPath };
                break;
            case "client-list":
                result = new { ok = true, selected_id = selected, clients = new object[] {
                    new { id = "stable", label = "VS Code / Codex fixture-1" },
                    new { id = "insiders sample", label = "VS Code Insiders / Codex fixture-2" } } };
                break;
            case "client-select":
                state["selected_id"] = options["--client-id"];
                Save("fixture-state.json", state);
                result = new { ok = true };
                break;
            case "review-latest":
                string reportFolder = Flag(config, "outside_report") ? Path.GetDirectoryName(folder) : Path.Combine(folder, "reviews", "fixture");
                Directory.CreateDirectory(reportFolder);
                string report = Path.Combine(reportFolder, "result.md");
                File.WriteAllText(report, "Fixture review result. No AI was run.");
                result = new { ok = true, report_path = report, detail = "テスト用の見直し結果です。" };
                break;
            default:
                result = new { ok = false, error = "unsupported fixture command" };
                break;
        }
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        Console.WriteLine(Json.Serialize(result));
        return 0;
    }

    private static Dictionary<string, object> Read(string name)
    {
        string path = Path.Combine(folder, name);
        return File.Exists(path) ? Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path)) : new Dictionary<string, object>();
    }
    private static void Save(string name, object data) { File.WriteAllText(Path.Combine(folder, name), Json.Serialize(data)); }
    private static bool Flag(Dictionary<string, object> data, string name) { object value; return data.TryGetValue(name, out value) && value is bool && (bool)value; }
    private static string Value(Dictionary<string, object> data, string name, string fallback) { object value; return data.TryGetValue(name, out value) ? Convert.ToString(value) : fallback; }
}
