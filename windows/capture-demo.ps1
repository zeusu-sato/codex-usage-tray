param(
    [string] $AssemblyPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'),
    [string] $OutputPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\images\demo.png')
)
$ErrorActionPreference = 'Stop'
if ([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') { throw 'Run with powershell.exe -NoProfile -STA -File windows\capture-demo.ps1' }
$AssemblyPath = [System.IO.Path]::GetFullPath($AssemblyPath)
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $AssemblyPath)) { throw 'Build the UI with windows\build.ps1 first.' }
$captureRoot = Join-Path (Split-Path $PSScriptRoot -Parent) ('build\demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
[void][System.IO.Directory]::CreateDirectory($captureRoot)
[void][System.IO.Directory]::CreateDirectory((Split-Path $OutputPath -Parent))
$fixtureBackend = Join-Path $captureRoot 'FixtureBackend.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /codepage:65001 "/out:$fixtureBackend" /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'tests\FixtureBackend.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fixture backend compilation failed' }
$data = Join-Path $captureRoot 'fixture-data'
[void][System.IO.Directory]::CreateDirectory($data)
# Synthetic trend metadata, unrelated to any account or live quota history.
$demoFixture = '{"remaining":98,"forecast":{"status":"comfortable","title":"\u4f59\u88d5\u304c\u3042\u308a\u305d\u3046\u3067\u3059","detail":"Weekly: \u76f4\u8fd112\u6642\u9593\u306e\u5e73\u5747\u304b\u3089\u6982\u7b97\u3002\u30ea\u30bb\u30c3\u30c8\u6642\u306e\u6b8b\u91cf\u306f\u7d0485%\u306e\u898b\u8fbc\u307f\u3067\u3059\u3002\n\u4f7f\u3044\u65b9\u304c\u5909\u308f\u308b\u3068\u898b\u901a\u3057\u3082\u5909\u308f\u308a\u307e\u3059\u3002","window_label":"Weekly","observed_hours":12,"projected_remaining_percent":85}}'
[System.IO.File]::WriteAllText((Join-Path $data 'fixture.json'), $demoFixture, [System.Text.UTF8Encoding]::new($false))

Add-Type -AssemblyName System.Windows.Forms,System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Drawing;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

public sealed class DemoCaptureHost : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
}

public static class DemoCapture {
    private static object Field(Form form, string name) {
        return form.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form);
    }
    private static void SetField(Form form, string name, object value) {
        form.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(form, value);
    }
    public static void Run(string assembly, string backend, string data, string output) {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Type type = Assembly.LoadFile(assembly).GetType("UsageToggleForm", true);
        Exception failure = null;
        using (var wake = new EventWaitHandle(false, EventResetMode.AutoReset))
        using (Form form = (Form)Activator.CreateInstance(type, new object[] { null, backend, data, false, wake }))
        using (Form host = new DemoCaptureHost())
        using (var timer = new System.Windows.Forms.Timer())
        using (Icon appIcon = Icon.ExtractAssociatedIcon(assembly)) {
            // Native controls need a visible parent to paint. An offscreen host
            // shows them without activating a window or exposing desktop data.
            host.StartPosition = FormStartPosition.Manual;
            host.Location = new Point(-20000, -20000);
            host.ShowInTaskbar = false;
            host.FormBorderStyle = FormBorderStyle.None;
            form.TopLevel = false;
            form.StartPosition = FormStartPosition.Manual;
            form.Location = Point.Empty;
            form.ShowInTaskbar = false;
            form.Icon = appIcon;
            host.Controls.Add(form);
            host.ClientSize = form.Size;
            form.Show();
            ((NotifyIcon)Field(form, "trayIcon")).Visible = false;
            SetField(form, "reviewRunner", new Action<string>(delegate { throw new InvalidOperationException("AI is forbidden in demo capture."); }));
            SetField(form, "reviewPresenter", new Action<Form>(delegate { throw new InvalidOperationException("No review confirmation expected in this fixture."); }));
            SetField(form, "clientPresenter", new Action<Form>(delegate { throw new InvalidOperationException("No client selection expected in this fixture."); }));
            SetField(form, "reportOpener", new Action<string>(delegate { throw new InvalidOperationException("No external document should open."); }));
            Stopwatch watch = Stopwatch.StartNew();
            timer.Interval = 25;
            timer.Tick += delegate {
                try {
                    if (watch.ElapsedMilliseconds > 15000) throw new TimeoutException("Fixture UI did not become ready.");
                    if (!(bool)Field(form, "initialized")) return;
                    foreach (string name in new string[] { "busy", "usageBusy", "monitorBusy", "reviewBusy", "reportBusy", "clientSelectionBusy" })
                        if ((bool)Field(form, name)) return;
                    if (form.Controls["UsageRemaining"].Text != "98%" || form.Controls["UsageToggle"].Enabled)
                        throw new InvalidOperationException("Unexpected first-run fixture state.");
                    timer.Stop();
                    ((System.Windows.Forms.Timer)Field(form, "usageTimer")).Stop();
                    ((System.Windows.Forms.Timer)Field(form, "monitorTimer")).Stop();
                    float scale;
                    using (Graphics graphics = form.CreateGraphics()) scale = graphics.DpiY / 96F;
                    int bannerHeight = (int)Math.Ceiling(34 * scale);
                    form.SuspendLayout();
                    foreach (Control control in form.Controls) control.Top += bannerHeight;
                    form.ClientSize = new Size(form.ClientSize.Width, form.ClientSize.Height + bannerHeight);
                    Label demo = new Label();
                    demo.Text = "Demo / \u30c6\u30b9\u30c8\u7528\u30c7\u30fc\u30bf";
                    demo.Font = new Font(form.Font.FontFamily, 10F, FontStyle.Bold);
                    demo.TextAlign = ContentAlignment.MiddleCenter;
                    demo.BackColor = Color.FromArgb(255, 241, 194);
                    demo.ForeColor = Color.FromArgb(96, 66, 10);
                    demo.SetBounds(0, 0, form.ClientSize.Width, bannerHeight);
                    form.Controls.Add(demo);
                    demo.BringToFront();
                    form.ResumeLayout(true);
                    host.ClientSize = form.Size;
                    using (Bitmap bitmap = new Bitmap(form.Width, form.Height)) {
                        form.DrawToBitmap(bitmap, new Rectangle(0, 0, form.Width, form.Height));
                        bitmap.Save(output, System.Drawing.Imaging.ImageFormat.Png);
                    }
                    Application.ExitThread();
                } catch (Exception error) {
                    failure = error; timer.Stop(); Application.ExitThread();
                }
            };
            type.GetMethod("Prepare").Invoke(form, null);
            timer.Start();
            Application.Run(host);
        }
        if (failure != null) throw new InvalidOperationException("Demo capture failed.", failure);
    }
}
'@
[DemoCapture]::Run($AssemblyPath, $fixtureBackend, $data, $OutputPath)
$commands = @(Get-ChildItem -LiteralPath $data -Filter 'command-*.txt' | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw })
if ($commands | Where-Object { $_ -notin @('ui-status', 'monitor-check', 'usage-check') }) { throw 'Unexpected command in the demo fixture.' }
Get-Item -LiteralPath $OutputPath | Select-Object FullName, Length
Write-Output 'Captured native offscreen WinForms controls using only synthetic fixture data; no AI, network, or installed Codex access.'
