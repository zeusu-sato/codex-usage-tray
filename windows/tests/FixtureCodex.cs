// Test-only metadata server. Never uses a network, login, model, or real Codex.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
public static class FixtureCodex {
    public static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length == 1 && args[0] == "--version") { Console.WriteLine("codex-cli fixture-1.0"); return 0; }
        if (args.Length != 3 || args[0] != "app-server" || args[1] != "--listen" || args[2] != "stdio://") return 91;
        var json = new JavaScriptSerializer();
        string line;
        while ((line = Console.ReadLine()) != null) {
            var request = json.Deserialize<Dictionary<string, object>>(line);
            string method = Convert.ToString(request["method"]);
            File.AppendAllText(Environment.GetEnvironmentVariable("TRAY_FIXTURE_CAPTURE"), method + "\n");
            if (method == "initialize") Console.WriteLine("{\"id\":1,\"result\":{}}");
            else if (method == "initialized") continue;
            else if (method == "account/rateLimits/read") {
                if (Environment.GetEnvironmentVariable("TRAY_FIXTURE_FAIL") == "1") {
                    Console.WriteLine("{\"id\":2,\"error\":{\"message\":\"fixture secret must not escape\"}}");
                } else {
                    long reset = (long)(DateTime.UtcNow.AddDays(2) - new DateTime(1970, 1, 1)).TotalSeconds;
                    Console.WriteLine("{\"id\":2,\"result\":{\"rateLimitsByLimitId\":{\"codex\":{\"limitId\":\"codex\",\"primary\":{\"usedPercent\":26,\"windowDurationMins\":10080,\"resetsAt\":" + reset + "}}}}}");
                }
                return 0;
            } else { return 92; }
        }
        return 0;
    }
}
