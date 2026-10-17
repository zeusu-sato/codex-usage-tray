param([string]$AssemblyPath=(Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'))
$ErrorActionPreference='Stop'
$CaptureDemo=$env:CODEX_USAGE_CAPTURE_DEMO -eq '1'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
. (Join-Path $PSScriptRoot 'tests\TrayRegistrations.ps1')
$root = Join-Path ([IO.Path]::GetTempPath()) ('credit-dual-ui-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory((Join-Path $root 'providers\claude'))
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$fixture=Join-Path $root 'FixtureBackend.exe'
& $compiler /nologo /target:exe /codepage:65001 "/out:$fixture" /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'tests\FixtureBackend.cs')
if($LASTEXITCODE -ne 0){throw 'Fixture compilation failed'}
$encoding=[Text.UTF8Encoding]::new($false)
$forecast=@{status='comfortable';title='余裕があります';detail='テスト用の見通しです';window_label='Weekly';observed_hours=12;projected_remaining_percent=50}
[IO.File]::WriteAllText((Join-Path $root 'fixture.json'),(@{remaining=68;configured=(-not $CaptureDemo);forecast=$forecast}|ConvertTo-Json -Depth 5),$encoding)
$forecast.status='tight';$forecast.title='ペースに注意'
[IO.File]::WriteAllText((Join-Path $root 'providers\claude\fixture.json'),(@{remaining=24;configured=(-not $CaptureDemo);forecast=$forecast}|ConvertTo-Json -Depth 5),$encoding)
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

public sealed class DualUiSession {
    public Form Host;
    public Thread Thread;
    public Exception Failure;
    public readonly ManualResetEventSlim Finished = new ManualResetEventSlim();
}

public static class DualUiTest {
    const BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic;

    static object Field(object target, string name) {
        return target.GetType().GetField(name, Fields).GetValue(target);
    }
    static Form[] Views(Form host) { return (Form[])Field(host, "views"); }
    static TabControl Tabs(Form host) { return (TabControl)Field(host, "tabs"); }
    static void Require(bool condition, string message) {
        if (!condition) throw new InvalidOperationException(message);
    }
    static object Invoke(DualUiSession session, Func<object> action) {
        if (session.Failure != null) throw new InvalidOperationException("UI thread failed", session.Failure);
        if (session.Finished.IsSet) throw new InvalidOperationException("UI loop ended unexpectedly");
        return session.Host.Invoke(action);
    }
    public static DualUiSession Start(string assembly, string backend, string data) {
        var ready = new TaskCompletionSource<DualUiSession>();
        var session = new DualUiSession();
        session.Thread = new Thread(delegate() {
            EventWaitHandle wake = null;
            try {
                Application.EnableVisualStyles();
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException, true);
                Type type = Assembly.LoadFile(assembly).GetType("UsageTrayHost", true);
                wake = new EventWaitHandle(false, EventResetMode.AutoReset);
                using (Form host = (Form)Activator.CreateInstance(type, new object[] { null, backend, data, false, wake })) {
                    session.Host = host;
                    host.StartPosition = FormStartPosition.Manual;
                    host.Location = new Point(-20000, -20000);
                    host.ShowInTaskbar = false;
                    foreach (Form view in Views(host)) {
                        ((NotifyIcon)Field(view, "trayIcon")).Visible = false;
                        view.GetType().GetField("reviewRunner", Fields).SetValue(view,
                            new Action<string>(delegate { throw new InvalidOperationException("Unexpected review launch"); }));
                    }
                    type.GetMethod("Prepare").Invoke(host, null);
                    // Signal only after the dedicated STA message loop is serving callbacks.
                    host.BeginInvoke(new Action(delegate { ready.TrySetResult(session); }));
                    Application.Run(host);
                }
            } catch (Exception error) {
                session.Failure = error;
                ready.TrySetException(error);
            } finally {
                if (wake != null) wake.Dispose();
                session.Finished.Set();
            }
        });
        session.Thread.IsBackground = true;
        session.Thread.SetApartmentState(ApartmentState.STA);
        session.Thread.Start();
        if (!ready.Task.Wait(15000)) throw new TimeoutException("UI message loop did not start");
        return ready.Task.GetAwaiter().GetResult();
    }
    public static string BusyState(DualUiSession session) {
        return (string)Invoke(session, delegate {
            var busy = new List<string>();
            Form[] views = Views(session.Host);
            for (int index = 0; index < views.Length; index++) {
                if (!(bool)Field(views[index], "initialized")) busy.Add(index + ":startup");
                foreach (string name in new string[] { "busy", "usageBusy", "monitorBusy", "reviewBusy", "reportBusy", "clientSelectionBusy" })
                    if ((bool)Field(views[index], name)) busy.Add(index + ":" + name);
            }
            return String.Join(", ", busy.ToArray());
        });
    }
    public static void VerifyInitial(DualUiSession session) {
        Invoke(session, delegate {
            Form[] views = Views(session.Host);
            Require(Tabs(session.Host).TabPages.Count == 2, "Provider tabs missing");
            Require(views[0].Controls["Heading"].Text == "Codex Usage" && views[1].Controls["Heading"].Text == "Claude Usage", "Provider heading mismatch");
            Require(views[0].Controls["UsageRemaining"].Text == "68%" && views[1].Controls["UsageRemaining"].Text == "24%", "Provider amounts crossed or did not load");
            Require(views[0].Controls["UsageRemaining"].ForeColor.ToArgb() == Color.FromArgb(28,111,85).ToArgb(), "Codex forecast color mismatch");
            Require(views[1].Controls["UsageRemaining"].ForeColor.ToArgb() == Color.FromArgb(157,104,0).ToArgb(), "Claude forecast color mismatch");
            return null;
        });
    }
    public static Task EnableClaude(DualUiSession session) {
        return (Task)Invoke(session, delegate {
            Form view = Views(session.Host)[1];
            return view.GetType().GetMethod("RunCommandAsync", Fields).Invoke(view, new object[] { "ui-enable" });
        });
    }
    public static void VerifyToggle(DualUiSession session) {
        Invoke(session, delegate {
            Form[] views = Views(session.Host);
            Require(((CheckBox)views[1].Controls["UsageToggle"]).Checked && !((CheckBox)views[0].Controls["UsageToggle"]).Checked, "Toggle crossed providers");
            return null;
        });
    }
    public static void OpenProvider(DualUiSession session, int index) {
        Invoke(session, delegate {
            ((Action)Field(Views(session.Host)[index], "HostOpen"))();
            Require(Tabs(session.Host).SelectedIndex == index && session.Host.Visible, "Tray did not open its provider tab");
            return null;
        });
    }
    static void RequireNumberPixels(Bitmap bitmap, int minimum, int brightness = 230) {
        int pixels = 0;
        // The symbol is only 18% opaque. Count bright foreground glyph pixels,
        // excluding the bottom gauge so it cannot hide missing number rendering.
        int bottom = bitmap.Height == 32 ? 26 : 12;
        for (int y = 0; y < bottom; y++) for (int x = 0; x < bitmap.Width; x++) {
            Color color = bitmap.GetPixel(x,y);
            if (color.A >= 220 && color.R >= brightness && color.G >= brightness && color.B >= brightness) pixels++;
        }
        Require(pixels >= minimum, "Missing foreground number/question mark in " + bitmap.Width + "px icon: " + pixels + " bright pixels");
    }
    static void SaveIcon(Icon icon, string stem, bool credit = false) {
        using (Bitmap actual = icon.ToBitmap()) {
            Require(actual.Width == 32 && actual.Height == 32, "Unexpected source icon size");
            actual.Save(stem + "-32.png");
            using (var small = new Bitmap(16,16))
            using (var graphics = Graphics.FromImage(small)) {
                graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                graphics.DrawImage(actual, new Rectangle(0,0,16,16));
                small.Save(stem + "-16.png");
                RequireNumberPixels(small, 2, credit ? 180 : 230);
            }
            RequireNumberPixels(actual, 8);
        }
    }
    public static void Capture(DualUiSession session, string folder, int index) {
        Invoke(session, delegate {
            Form host = session.Host;
            Require(Tabs(host).SelectedIndex == index, "Capture requested for hidden provider tab");
            using (var bitmap = new Bitmap(host.Width, host.Height)) {
                host.DrawToBitmap(bitmap, new Rectangle(0, 0, bitmap.Width, bitmap.Height));
                bitmap.Save(Path.Combine(folder, "provider-" + index + ".png"));
            }
            string provider = index == 0 ? "codex" : "claude";
            SaveIcon((Icon)Field(Views(host)[index], "usageIcon"), Path.Combine(folder, provider + "-icon"), Views(host)[index].Controls["UsageRemaining"].ForeColor.ToArgb() == Color.FromArgb(106,76,196).ToArgb());
            return null;
        });
    }
    public static void CapturePreviews(DualUiSession session, string folder) {
        Invoke(session, delegate {
            Type symbols = session.Host.GetType().Assembly.GetType("TraySymbols", true);
            MethodInfo create = symbols.GetMethod("Create", BindingFlags.Static | BindingFlags.NonPublic);
            foreach (string provider in new string[] { "codex", "claude" }) {
                foreach (double? value in new double?[] { 68, 24, 100, null }) {
                    string label = value.HasValue ? value.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : "unknown";
                    Color color = !value.HasValue ? Color.FromArgb(94,106,115)
                        : value == 24 ? Color.FromArgb(157,104,0) : Color.FromArgb(28,111,85);
                    using (Icon icon = (Icon)create.Invoke(null, new object[] { value, color, provider, null }))
                        SaveIcon(icon, Path.Combine(folder, provider + "-preview-" + label));
                }
            }
            return null;
        });
    }
    public static void CaptureCreditPreviews(DualUiSession session, string folder) {
        Directory.CreateDirectory(folder);
        Invoke(session, delegate {
            Type symbols = session.Host.GetType().Assembly.GetType("TraySymbols", true);
            MethodInfo create = symbols.GetMethod("Create", BindingFlags.Static | BindingFlags.NonPublic);
            string[] texts = { "812", "61k", ".9M", ".1M", "∞", "¤", "688", "1k" };
            string[] names = { "812", "61k", ".9M", ".1M", "infinity", "currency", "688", "1k" };
            for (int i = 0; i < texts.Length; i++) {
                using (Icon icon = (Icon)create.Invoke(null, new object[] { (double?)100, Color.FromArgb(106,76,196), "codex", texts[i] })) {
                    SaveIcon(icon, Path.Combine(folder, "credit-" + names[i]), true);
                    using (Bitmap bitmap = icon.ToBitmap()) {
                        for (int y = 0; y < 32; y++) for (int x = 0; x < 32; x++) {
                            Color c = bitmap.GetPixel(x,y);
                            if (c.R > 230 && c.G > 230 && c.B > 230)
                                Require(x >= 1 && x <= 30 && y >= 1 && y <= 25, "Credit glyph outside padded text area: " + texts[i]);
                        }
                        Require(bitmap.GetPixel(15,28).R < 200, "Credit gauge must contain only the track");
                    }
                }
            }
            return null;
        });
    }
    public static Task RefreshCredit(DualUiSession session, int index) {
        return (Task)Invoke(session, delegate {
            Form view = Views(session.Host)[index];
            return view.GetType().GetMethod("CheckUsageAsync", Fields).Invoke(view, null);
        });
    }
    public static void VerifyCredit(DualUiSession session, int index, string title, string summary) {
        Invoke(session, delegate {
            Form view = Views(session.Host)[index];
            Require(view.Controls["UsageRemaining"].Text == title, "Credit title missing");
            Require(view.Controls["UsageDetail"].Text.StartsWith(summary), "Credit summary missing");
            Require(((string)Field(view,"usageTooltip")).Contains(title), "Credit tooltip missing");
            Require(view.Controls["UsageForecast"].Text == "Credit 利用中は見通しを表示しません。", "Credit forecast explanation missing");
            using (Bitmap bitmap = ((Icon)Field(view,"usageIcon")).ToBitmap())
                Require(bitmap.GetPixel(0,0).ToArgb() == Color.FromArgb(106,76,196).ToArgb(), "Credit icon background mismatch");
            return null;
        });
    }
    public static void Stop(DualUiSession session) {
        if (!session.Finished.IsSet) {
            session.Host.Invoke(new Action(delegate {
                session.Host.GetType().GetField("exiting", Fields).SetValue(session.Host, true);
                session.Host.Close();
            }));
        }
        Require(session.Finished.Wait(10000), "UI loop did not finish during cleanup");
        Require(session.Thread.Join(1000), "UI thread survived cleanup");
        if (session.Failure != null) throw new InvalidOperationException("UI cleanup failed", session.Failure);
        Require(session.Host.IsDisposed, "Host was not disposed");
    }
}
'@
function Wait-DualIdle($session) {
    $watch=[Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Milliseconds 25
        $busy=[DualUiTest]::BusyState($session)
    } while ($busy.Length -gt 0 -and $watch.ElapsedMilliseconds -lt 20000)
    if ($busy.Length -gt 0) { throw "UI remains busy: $busy" }
}
$session=$null
try{
 $session=[DualUiTest]::Start([IO.Path]::GetFullPath($AssemblyPath),$fixture,$root)
 Wait-DualIdle $session
 [DualUiTest]::VerifyInitial($session)
 if(-not $CaptureDemo){
 $task=[DualUiTest]::EnableClaude($session)
 if(-not $task.Wait(12000)){throw 'Toggle operation timed out'}
 $null=$task.GetAwaiter().GetResult()
 Wait-DualIdle $session
 [DualUiTest]::VerifyToggle($session)
 }
 foreach($index in 1,0){
     [DualUiTest]::OpenProvider($session,$index)
     Wait-DualIdle $session
     [DualUiTest]::Capture($session,$root,$index)
 }
 [DualUiTest]::CapturePreviews($session,$root)
 [DualUiTest]::CaptureCreditPreviews($session,(Join-Path $env:USERPROFILE 'credit-icon-samples\windows'))
 Write-Output 'PASS: eight Credit glyphs fit the padded 32px area, track has no fill, and 32/16px samples contain visible text.'
 foreach($index in 0,1){
     $title=if($index -eq 0){'Credit 利用中'}else{'追加利用中'}
     $summary=if($index -eq 0){'残り61,794クレジット'}else{'追加利用：今月の上限まで残り $688.00（使用 $0.00）'}
     $path=if($index -eq 0){Join-Path $root 'fixture.json'}else{Join-Path $root 'providers\claude\fixture.json'}
     foreach($text in $(if($index -eq 0){@('61k')}else{@('688','∞','¤')})){
         $credit=@{kind=$(if($index -eq 0){'codex_credits'}else{'claude_extra_usage'});tray_text=$text;amount_known=($text -ne '¤');title=$title;summary=$summary}
         [IO.File]::WriteAllText($path,(@{remaining=0;credit=$credit}|ConvertTo-Json -Depth 5),$encoding)
         $task=[DualUiTest]::RefreshCredit($session,$index)
         if(-not $task.Wait(12000)){throw 'Credit refresh timed out'}
         $null=$task.GetAwaiter().GetResult()
         [DualUiTest]::VerifyCredit($session,$index,$title,$summary)
         [DualUiTest]::OpenProvider($session,$index)
         [DualUiTest]::Capture($session,$root,$index)
     }
 }
 Write-Output 'PASS: dual-provider Credit modes (61k/688/∞/¤), titles, summaries, tooltips, and purple tray backgrounds.'

}finally{if($session){[DualUiTest]::Stop($session)};Remove-TestTrayRegistrations}
$commands=Get-ChildItem -LiteralPath $root -Filter 'command-*.txt' -Recurse | ForEach-Object {Get-Content -LiteralPath $_.FullName}
if($commands -contains 'review-run' -or $commands -contains 'review-decide'){throw 'Unexpected AI-related action'}
if($CaptureDemo){Write-Output 'PASS: synthetic dual-provider demo, no configured policies, no inference launch.'}
else{Write-Output 'PASS: isolated provider views, percentages/colors/toggles, tray-to-tab navigation, foreground digits at 32/16px (68/24/100/?), no inference launch, and completed STA cleanup.'}
Write-Output "Artifacts: $root"
