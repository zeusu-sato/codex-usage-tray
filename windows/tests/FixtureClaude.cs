// Test-only Claude metadata peer: no network, authentication, model, or real CLI.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;

public static class FixtureClaude
{
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static readonly string[] ExpectedArguments = {
        "--print", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--safe-mode", "--no-session-persistence", "--strict-mcp-config", "--no-chrome",
        "--disable-slash-commands", "--tools", "", "--setting-sources="
    };

    static void Require(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Forbidden fixture protocol");
    }
    static void LogLaunch(string category)
    {
        File.AppendAllText(Environment.GetEnvironmentVariable("TRAY_CLAUDE_FIXTURE_LAUNCHES"), category + "\n");
    }
    static void ReadControl(string subtype, string identifier)
    {
        var message = Json.Deserialize<Dictionary<string, object>>(Console.ReadLine());
        Require(message.Count == 3 && Convert.ToString(message["type"]) == "control_request"
                && Convert.ToString(message["request_id"]) == identifier);
        var request = message["request"] as Dictionary<string, object>;
        Require(request != null && Convert.ToString(request["subtype"]) == subtype);
        if (subtype == "initialize")
        {
            Require(request.Count == 5 && request["promptSuggestions"] is bool && !(bool)request["promptSuggestions"]
                    && request["agentProgressSummaries"] is bool && !(bool)request["agentProgressSummaries"]);
            Require(request["skills"] is IList && ((IList)request["skills"]).Count == 0
                    && request["plugins"] is IList && ((IList)request["plugins"]).Count == 0);
        }
        else Require(subtype == "get_usage" && request.Count == 2
                     && request["skip_behaviors"] is bool && (bool)request["skip_behaviors"]);
        File.AppendAllText(Environment.GetEnvironmentVariable("TRAY_CLAUDE_FIXTURE_CAPTURE"), subtype + "\n");
    }
    static void Success(string identifier, object payload)
    {
        Console.WriteLine(Json.Serialize(new { type = "control_response", response = new {
            subtype = "success", request_id = identifier, response = payload } }));
        Console.Out.Flush();
    }
    public static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        try
        {
            if (args.Length == 1 && args[0] == "--version")
            {
                LogLaunch("version");
                Console.WriteLine((Environment.GetEnvironmentVariable("TRAY_CLAUDE_FIXTURE_VERSION") ?? "2.1.263") + " (Claude Code)");
                return 0;
            }
            LogLaunch("metadata");
            Require(args.Length == ExpectedArguments.Length);
            for (int index = 0; index < args.Length; index++) Require(args[index] == ExpectedArguments[index]);
            ReadControl("initialize", "usage-tray-initialize");
            Success("usage-tray-initialize", new { account = new {
                email = "fixture-private-account@example.invalid", organization = "Fixture Private Organization",
                name = "Fixture Private Name", apiProvider = "firstParty", tokenSource = "claude.ai" } });
            ReadControl("get_usage", "usage-tray-get-usage");
            if (Environment.GetEnvironmentVariable("TRAY_FIXTURE_FAIL") == "1")
            {
                Console.WriteLine(Json.Serialize(new { type = "control_response", response = new {
                    subtype = "error", request_id = "usage-tray-get-usage", error = "fixture-error-secret-must-not-escape" } }));
                return 0;
            }
            string reset = DateTime.UtcNow.AddHours(4).ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'Z'", CultureInfo.InvariantCulture);
            string weekly = DateTime.UtcNow.AddDays(2).ToString("yyyy-MM-dd'T'HH:mm:ss.ffffff'Z'", CultureInfo.InvariantCulture);
            if (Environment.GetEnvironmentVariable("TRAY_CLAUDE_FIXTURE_NULL_RESET") == "1") reset = null;
            Success("usage-tray-get-usage", new { rate_limits_available = true, rate_limits = new {
                five_hour = new { utilization = 12, resets_at = reset },
                seven_day = new { utilization = 27, resets_at = weekly },
                seven_day_sonnet = new { utilization = 99, resets_at = weekly } },
                behavior = "fixture-private-behavior" });
            return 0;
        }
        catch { return 92; }
    }
}
