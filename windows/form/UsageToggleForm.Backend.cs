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
        if(provider=="claude")commandLine.Append(" --provider claude");
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

}
