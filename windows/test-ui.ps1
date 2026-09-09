param([string] $AssemblyPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$testRoot = Join-Path (Split-Path $PSScriptRoot -Parent) ('build\ui-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
[void][System.IO.Directory]::CreateDirectory($testRoot)
$fixtureBackend = Join-Path $testRoot 'FixtureBackend.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /codepage:65001 "/out:$fixtureBackend" /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'tests\FixtureBackend.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fixture backend compilation failed' }
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
public static class PublicUiTest {
    public static readonly List<string> Requests = new List<string>();
    public static readonly List<string> Reports = new List<string>();
    public static int Attempts;
    public static bool FailLaunch;
    public static Form Start(string assembly, string backend, string data) {
        return Start(assembly, backend, data, 0);
    }
    public static Form Start(string assembly, string backend, string data, int loopDelayMilliseconds) {
        var ready = new TaskCompletionSource<Form>();
        var thread = new Thread(delegate() {
            try {
                Application.EnableVisualStyles();
                Type type = Assembly.LoadFile(assembly).GetType("UsageToggleForm", true);
                var wake = new EventWaitHandle(false, EventResetMode.AutoReset);
                Form form = (Form)Activator.CreateInstance(type, new object[] { null, backend, data, false, wake });
                form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-20000, -20000);
                form.ShowInTaskbar = false;
                ((NotifyIcon)Field(form, "trayIcon")).Visible = false;
                SetField(form, "reviewPresenter", new Action<Form>(Present));
                SetField(form, "clientPresenter", new Action<Form>(Present));
                SetField(form, "reviewRunner", new Action<string>(Launch));
                SetField(form, "reportOpener", new Action<string>(OpenReport));
                type.GetMethod("Prepare").Invoke(form, null);
                ready.SetResult(form);
                // Exercise a caller reaching Wait-Idle before the UI loop starts.
                if (loopDelayMilliseconds > 0) Thread.Sleep(loopDelayMilliseconds);
                Application.Run(form);
                wake.Dispose();
            } catch (Exception error) { ready.TrySetException(error); }
        });
        thread.IsBackground = true; thread.SetApartmentState(ApartmentState.STA); thread.Start();
        return ready.Task.GetAwaiter().GetResult();
    }
    private static void Present(Form form) {
        form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-20000, -20000);
        form.ShowInTaskbar = false; form.Show();
    }
    private static void Launch(string request) {
        Attempts++; if (FailLaunch) throw new InvalidOperationException("Fixture launch failure"); Requests.Add(request);
    }
    private static void OpenReport(string path) { Reports.Add(path); }
    public static object Field(Form form, string name) { return form.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form); }
    public static string BusyState(Form form) {
        return (string)form.Invoke(new Func<string>(delegate {
            // Startup and all busy flags change on this thread. Independent reads
            // could combine pre-startup idle flags with initialized=true and return early.
            if (!(bool)Field(form, "initialized")) return "startup";
            var names = new List<string>();
            foreach (string name in new string[] { "busy", "usageBusy", "monitorBusy", "reviewBusy", "reportBusy", "clientSelectionBusy" })
                if ((bool)Field(form, name)) names.Add(name);
            return String.Join(", ", names.ToArray());
        }));
    }
    public static void SetField(Form form, string name, object value) { form.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(form, value); }
    public static object Call(Form form, string method, object[] args) {
        return form.Invoke(new Func<object>(delegate { return form.GetType().GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(form, args); }));
    }
    public static void Click(Control control) {
        control.Invoke(new Action(delegate {
            Button button = control as Button;
            if (button != null) button.PerformClick();
            else typeof(Control).GetMethod("OnClick", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(control, new object[] { EventArgs.Empty });
        }));
    }
    public static void Select(ComboBox box, int index) { box.Invoke(new Action(delegate { box.SelectedIndex = index; })); }
    public static bool Space(CheckBox box) {
        return (bool)box.Invoke(new Func<bool>(delegate {
            box.Focus();
            typeof(Control).GetMethod("OnKeyDown", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(box, new object[] { new KeyEventArgs(Keys.Space) });
            typeof(Control).GetMethod("OnKeyUp", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(box, new object[] { new KeyEventArgs(Keys.Space) });
            return box.Checked;
        }));
    }
    public static void CaptureControl(Control control, string path) {
        control.Invoke(new Action(delegate {
            using (Bitmap bitmap = new Bitmap(control.Width, control.Height)) {
                control.DrawToBitmap(bitmap, new Rectangle(0, 0, control.Width, control.Height)); bitmap.Save(path);
            }
        }));
    }
    public static void UnownedShortcut(string assembly, string path, string target) {
        Assembly.LoadFile(assembly).GetType("StartupShortcuts", true).GetMethod("Save")
            .Invoke(null, new object[] { path, target, "", Path.GetDirectoryName(target), "Unrelated shortcut" });
    }
    public static void Dispose(Form form) { if (!form.IsDisposed) form.Invoke(new Action(form.Dispose)); }
    public static void Close(Form form) { form.Invoke(new Action(form.Close)); }
    public static void Escape(Form form) {
        form.Invoke(new Action(delegate { typeof(Form).GetMethod("ProcessDialogKey", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(form, new object[] { Keys.Escape }); }));
    }
    public static void Screenshot(Form form, string path) {
        form.Invoke(new Action(delegate {
            using (Bitmap bitmap = new Bitmap(form.Width, form.Height)) {
                form.DrawToBitmap(bitmap, new Rectangle(0, 0, form.Width, form.Height)); bitmap.Save(path);
            }
        }));
    }
    public static void SaveIcon(Form form, string path) {
        form.Invoke(new Action(delegate { using (Bitmap bitmap = ((Icon)Field(form, "usageIcon")).ToBitmap()) bitmap.Save(path); }));
    }
    public static IntPtr Window(int pid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr handle, IntPtr state) {
            uint owner; GetWindowThreadProcessId(handle, out owner);
            var title = new StringBuilder(256); GetWindowText(handle, title, title.Capacity);
            if (owner == pid && title.ToString() == "Codex Usage Tray") { found = handle; return false; }
            return true;
        }, IntPtr.Zero); return found;
    }
    public static void MoveOffscreen(IntPtr handle) { SetWindowPos(handle, IntPtr.Zero, -20000, -20000, 0, 0, 0x0015); }
    public static void Hide(IntPtr handle) { ShowWindow(handle, 0); }
    private delegate bool EnumCallback(IntPtr window, IntPtr state);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumCallback callback, IntPtr state);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder title, int length);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr handle, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
'@

function Write-Fixture([string] $directory, [hashtable] $values) {
    [void][System.IO.Directory]::CreateDirectory($directory)
    [System.IO.File]::WriteAllText((Join-Path $directory 'fixture.json'), ($values | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
}
function Wait-Task($task, [int] $milliseconds = 12000) {
    if (-not $task.Wait($milliseconds)) { throw 'UI operation did not finish' }
    if ($task.IsFaulted) { throw $task.Exception }
}
function Wait-Idle($window) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Milliseconds 25
        $busy = [PublicUiTest]::BusyState($window)
    } while ($busy.Length -gt 0 -and $watch.ElapsedMilliseconds -lt 15000)
    if ($busy.Length -gt 0) { throw "Form remains busy: $busy" }
}
function Refresh-Quota($window) { Wait-Task ([PublicUiTest]::Call($window, 'CheckUsageAsync', @())) }
function Wait-Closed($window) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while (-not $window.IsDisposed -and $watch.ElapsedMilliseconds -lt 10000) { Start-Sleep -Milliseconds 20 }
    if (-not $window.IsDisposed) { throw 'Dialog did not close' }
}
function Wait-File([string] $path) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $path) -and $watch.ElapsedMilliseconds -lt 5000) { Start-Sleep -Milliseconds 20 }
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing fixture marker: $path" }
}
function Assert-Ended([int] $processId) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ((Get-Process -Id $processId -ErrorAction SilentlyContinue) -and $watch.ElapsedMilliseconds -lt 3000) { Start-Sleep -Milliseconds 20 }
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw "Fixture process remains: $processId" }
}

$window = $null
$aliasWindow = $null
$native = $null
$second = $null
$third = $null
try {
    $data = Join-Path $testRoot 'profile with spaces 日本語'
    Write-Fixture $data @{ remaining = 98 }
    $window = [PublicUiTest]::Start([System.IO.Path]::GetFullPath($AssemblyPath), $fixtureBackend, $data, 150)
    Wait-Idle $window
    if ($window.Text -ne 'Codex Usage Tray' -or $window.Controls['StatusTitle'].Text -ne '追加対策は未設定です' -or $window.Controls['UsageToggle'].Enabled) { throw "Public first-run state: $($window.Text); $($window.Controls['StatusTitle'].Text); $($window.Controls['StatusDetail'].Text)" }
    if (-not $window.Controls['ReviewWithAi'].Visible -or -not $window.Controls['ReviewWithAi'].Enabled) { throw 'Manual review must be available for a detected matching client' }
    if ([PublicUiTest]::Field($window, 'reviewPrompt')) { throw 'Matching baseline automatically asked for AI' }
    foreach ($percent in @(98, 21, 4, 0, 100)) {
        Write-Fixture $data @{ remaining = $percent }
        Refresh-Quota $window
        if ($window.Controls['UsageRemaining'].Text -ne "$percent%") { throw "Wrong quota at $percent%" }
        [PublicUiTest]::SaveIcon($window, (Join-Path $testRoot "icon-$percent.png"))
    }
    Write-Fixture $data @{ remaining = 98; stale = $true }
    Refresh-Quota $window
    if ($window.Controls['UsageRemaining'].Text -ne '?' -or -not $window.Controls['UsageDetail'].Text.Contains('前回')) { throw 'Stale quota displayed as current' }
    Write-Fixture $data @{ remaining = $null }
    Refresh-Quota $window
    if ($window.Controls['UsageRemaining'].Text -ne '?') { throw 'Unknown quota displayed as a number' }
    if ([PublicUiTest]::Field($window, 'usageTimer').Interval -ne 300000 -or [PublicUiTest]::Field($window, 'monitorTimer').Interval -ne 900000) { throw 'Polling intervals changed' }
    Write-Fixture $data @{ remaining = 98 }
    Refresh-Quota $window
    [PublicUiTest]::Screenshot($window, (Join-Path $testRoot 'public-first-run.png'))
    Write-Output 'PASS: packaged EXE backend, Unicode/space data path, unconfigured policy, manual review, quota states, and timers.'

    Write-Fixture $data @{ remaining = 98; configured = $true }
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    Wait-Idle $window
    $switch = $window.Controls['UsageToggle']
    if ($switch.GetType().Name -ne 'ToggleSwitch' -or $switch.AutoCheck -or $switch.AccessibilityObject.Role -ne [System.Windows.Forms.AccessibleRole]::CheckButton) { throw 'Toggle bar lost its confirmed-state checkbox semantics' }
    [PublicUiTest]::CaptureControl($switch, (Join-Path $testRoot 'switch-off.png'))
    if ([PublicUiTest]::Space($switch)) { throw 'Space visually committed ON before the backend reply' }
    Wait-Idle $window
    if (-not $switch.Checked -or $switch.Text -ne 'ON') { throw 'Space did not activate the confirmed toggle state' }
    [PublicUiTest]::CaptureControl($switch, (Join-Path $testRoot 'switch-on.png'))
    if (-not [PublicUiTest]::Space($switch)) { throw 'Space visually committed OFF before the backend reply' }
    Wait-Idle $window
    if ($switch.Checked -or $switch.Text -ne 'OFF') { throw 'Space did not deactivate the confirmed toggle state' }
    $switchCommands = @(Get-ChildItem -LiteralPath $data -Filter 'command-*.txt' | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw })
    if (@($switchCommands | Where-Object { $_ -eq 'ui-enable' }).Count -ne 1 -or @($switchCommands | Where-Object { $_ -eq 'ui-disable' }).Count -ne 1) { throw 'A keyboard toggle sent duplicate backend commands' }
    [PublicUiTest]::SetField($window, 'backend', (Join-Path $testRoot 'missing-fixture.exe'))
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    if ($switch.Enabled -or $switch.Text -ne '未確認') { throw 'An unknown state looked like confirmed OFF' }
    [PublicUiTest]::CaptureControl($switch, (Join-Path $testRoot 'switch-unknown.png'))
    [PublicUiTest]::SetField($window, 'backend', $fixtureBackend)
    Write-Fixture $data @{ remaining = 98 }
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    Write-Output 'PASS: rounded checkbox switch supports Space exactly once, exposes ON/OFF, and preserves unknown and pending states.'

    Wait-Task ([PublicUiTest]::Call($window, 'CheckReviewAsync', @($true)))
    $prompt = [PublicUiTest]::Field($window, 'reviewPrompt')
    if (-not $prompt -or $prompt.AcceptButton.Name -ne 'ReviewNo') { throw 'Manual review confirmation must default to No' }
    [PublicUiTest]::Screenshot($prompt, (Join-Path $testRoot 'review-confirmation.png'))
    [PublicUiTest]::Click($prompt.Controls['ReviewNo'])
    Wait-Closed $prompt
    Wait-Task ([PublicUiTest]::Call($window, 'CheckReviewAsync', @($true)))
    $prompt = [PublicUiTest]::Field($window, 'reviewPrompt')
    [PublicUiTest]::Escape($prompt)
    Wait-Closed $prompt
    Wait-Task ([PublicUiTest]::Call($window, 'CheckReviewAsync', @($true)))
    $prompt = [PublicUiTest]::Field($window, 'reviewPrompt')
    [PublicUiTest]::Click($prompt.Controls['ReviewYes'])
    Wait-Closed $prompt
    if ([PublicUiTest]::Requests.Count -ne 1 -or [PublicUiTest]::Attempts -ne 1) { throw 'Explicit Yes did not invoke exactly one runner spy' }
    $visibleStart = [PublicUiTest]::Call($window, 'CreateBackendStart', @([string[]]@('review-run', '--request', [PublicUiTest]::Requests[0]), $true))
    if ($visibleStart.FileName -ne $fixtureBackend -or -not $visibleStart.UseShellExecute -or $visibleStart.Arguments -match '\-X utf8' -or $visibleStart.Arguments -notmatch '\-\-data-dir') { throw 'Visible review does not use the packaged backend contract' }
    $scriptPath = Join-Path $testRoot 'development fixture.py'
    [System.IO.File]::WriteAllText($scriptPath, '# Argument-construction fixture only; never executed.')
    [PublicUiTest]::SetField($window, 'backend', $scriptPath)
    [PublicUiTest]::SetField($window, 'python', $fixtureBackend)
    $scriptStart = [PublicUiTest]::Call($window, 'CreateBackendStart', @([string[]]@('ui-status'), $false))
    if ($scriptStart.FileName -ne $fixtureBackend -or $scriptStart.Arguments -notmatch '^\-X utf8 ' -or $scriptStart.Arguments -notmatch '\-\-data-dir') { throw 'Development script contract changed' }
    [PublicUiTest]::SetField($window, 'backend', $fixtureBackend)
    [PublicUiTest]::SetField($window, 'python', $null)
    Write-Output 'PASS: No/Escape are non-AI choices; explicit Yes calls only a spy; packaged review-run uses a visible console.'

    Wait-Task ([PublicUiTest]::Call($window, 'OpenLatestReviewAsync', @()))
    if ([PublicUiTest]::Reports.Count -ne 1 -or -not [PublicUiTest]::Reports[0].StartsWith((Join-Path $data 'reviews'))) { throw 'Validated review result did not reach the document spy' }
    Write-Fixture $data @{ remaining = 98; outside_report = $true }
    Wait-Task ([PublicUiTest]::Call($window, 'OpenLatestReviewAsync', @()))
    if ([PublicUiTest]::Reports.Count -ne 1 -or -not $window.Controls['ReviewStatus'].Text.Contains('開けません')) { throw 'Report outside the data reviews directory was opened' }
    Write-Fixture $data @{ remaining = 98 }
    Write-Output 'PASS: review-result opening is user initiated and rejects files outside the app review directory.'

    $dataAlias = Join-Path $testRoot 'profile junction alias'
    [void](New-Item -ItemType Junction -Path $dataAlias -Target $data)
    $aliasWindow = [PublicUiTest]::Start([System.IO.Path]::GetFullPath($AssemblyPath), $fixtureBackend, $dataAlias)
    Wait-Idle $aliasWindow
    if ([PublicUiTest]::Field($aliasWindow, 'dataDirectory') -ne [PublicUiTest]::Field($window, 'dataDirectory')) { throw 'A data-directory alias retained a different identity' }
    Wait-Task ([PublicUiTest]::Call($aliasWindow, 'OpenLatestReviewAsync', @()))
    if ([PublicUiTest]::Reports.Count -ne 2 -or [PublicUiTest]::Reports[1] -ne [PublicUiTest]::Reports[0]) { throw 'A resolved report from an aliased data directory was rejected' }
    $reportAlias = Join-Path $dataAlias 'reviews\fixture\result.md'
    $resolvedReport = [PublicUiTest]::Call($aliasWindow, 'ValidateReportPath', @([string]$reportAlias))
    if ($resolvedReport -ne [PublicUiTest]::Reports[0]) { throw 'A report alias was not resolved to its real file' }
    $outside = Join-Path $testRoot 'outside review destination'
    [void][System.IO.Directory]::CreateDirectory($outside)
    [System.IO.File]::WriteAllText((Join-Path $outside 'escape.md'), 'Synthetic report outside the reviews directory.')
    $escapeAlias = Join-Path $data 'reviews\escape junction'
    [void](New-Item -ItemType Junction -Path $escapeAlias -Target $outside)
    $rejected = $false
    try { [void][PublicUiTest]::Call($aliasWindow, 'ValidateReportPath', @([string](Join-Path $escapeAlias 'escape.md'))) } catch { $rejected = $true }
    if (-not $rejected) { throw 'A junction escaped the canonical review directory' }
    [PublicUiTest]::Dispose($aliasWindow)
    Write-Output 'PASS: profile/report junction aliases resolve consistently, and a report junction escaping the real reviews directory is rejected.'

    # Supplementary Unicode is outside both the runner's ANSI code page and CP932.
    $startup = Join-Path $data ('fake Startup ' + [char]0xD83E + [char]0xDDEA)
    [PublicUiTest]::SetField($window, 'startupDirectory', $startup)
    if ([PublicUiTest]::Call($window, 'StartupEnabled', @())) { throw 'Startup must default off' }
    [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($true))
    if (-not [PublicUiTest]::Call($window, 'StartupEnabled', @())) { throw 'Startup choice was not saved' }
    [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($false))
    if (Test-Path -LiteralPath (Join-Path $startup 'CodexUsageTray-managed.lnk')) { throw 'Owned startup shortcut was not removed' }
    [System.IO.File]::WriteAllText((Join-Path $startup 'unrelated.txt'), 'keep')
    [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($false))
    if ((Get-Content -LiteralPath (Join-Path $startup 'unrelated.txt') -Raw) -ne 'keep') { throw 'Startup operation changed an unrelated file' }
    $unrelatedShortcut = Join-Path $startup 'CodexUsageTray-managed.lnk'
    [PublicUiTest]::UnownedShortcut([System.IO.Path]::GetFullPath($AssemblyPath), $unrelatedShortcut, (Join-Path $env:WINDIR 'notepad.exe'))
    $preserved = $false
    try { [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($false)) } catch { $preserved = $true }
    if (-not $preserved -or -not (Test-Path -LiteralPath $unrelatedShortcut)) { throw 'An unowned same-name shortcut was modified' }
    Write-Output 'PASS: Unicode startup save/read/removal is opt-in and preserves unowned shortcuts, including Japanese and supplementary-Unicode paths.'
    [PublicUiTest]::Dispose($window)

    $data = Join-Path $testRoot 'ambiguous profile'
    Write-Fixture $data @{ remaining = $null; ambiguous = $true }
    $window = [PublicUiTest]::Start([System.IO.Path]::GetFullPath($AssemblyPath), $fixtureBackend, $data, 150)
    Wait-Idle $window
    $picker = [PublicUiTest]::Field($window, 'clientPicker')
    if (-not $picker) { throw "Ambiguous client picker missing: $($window.Controls['ReviewStatus'].Text); $($window.Controls['MonitorStatus'].Text)" }
    if ($picker.Controls['SelectCodexClient'].Enabled -or $picker.Controls['CodexClientChoices'].SelectedIndex -ne -1) { throw 'Ambiguous clients must require an explicit choice' }
    [PublicUiTest]::Screenshot($picker, (Join-Path $testRoot 'client-selection.png'))
    [PublicUiTest]::Select($picker.Controls['CodexClientChoices'], 1)
    [PublicUiTest]::Click($picker.Controls['SelectCodexClient'])
    Wait-Closed $picker
    $state = Get-Content -LiteralPath (Join-Path $data 'fixture-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.selected_id -ne 'insiders sample' -or -not $window.Controls['ReviewWithAi'].Enabled) { throw 'Client choice was not persisted/refreshed' }
    if ([PublicUiTest]::Attempts -ne 1) { throw 'Client selection launched AI' }
    Write-Output 'PASS: ambiguous detection opens an offscreen nonmodal picker; explicit client ID survives spaces and refreshes status without AI.'

    Write-Fixture $data @{ remaining = 98; configured = $true; slow = $true }
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    $slowTask = [PublicUiTest]::Call($window, 'CheckUsageAsync', @())
    Wait-File (Join-Path $data 'parent.pid')
    Wait-File (Join-Path $data 'child.pid')
    $parentId = [int](Get-Content -LiteralPath (Join-Path $data 'parent.pid') -Raw)
    $childId = [int](Get-Content -LiteralPath (Join-Path $data 'child.pid') -Raw)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    [PublicUiTest]::Click($window.Controls['UsageToggle'])
    while ($window.Controls['StatusTitle'].Text -ne '追加対策は有効です' -and $watch.ElapsedMilliseconds -lt 3000) { Start-Sleep -Milliseconds 20 }
    if ($window.Controls['StatusTitle'].Text -ne '追加対策は有効です' -or $slowTask.IsCompleted) { throw 'Slow quota request blocks the toggle' }
    [PublicUiTest]::Dispose($window)
    Assert-Ended $parentId
    Assert-Ended $childId
    Write-Output 'PASS: slow quota does not block toggles; disposal kills the fixture backend and its descendant.'

    $install = Join-Path $testRoot 'native package'
    [void][System.IO.Directory]::CreateDirectory((Join-Path $install 'backend'))
    Copy-Item -LiteralPath $AssemblyPath -Destination (Join-Path $install 'CodexUsageTray.exe')
    Copy-Item -LiteralPath $fixtureBackend -Destination (Join-Path $install 'backend\CodexUsageBackend.exe')
    $data = Join-Path $testRoot 'native profile'
    Write-Fixture $data @{ remaining = $null }
    $nativeDataAlias = Join-Path $testRoot 'native profile junction'
    [void](New-Item -ItemType Junction -Path $nativeDataAlias -Target $data)
    $nativeExe = Join-Path $install 'CodexUsageTray.exe'
    $native = Start-Process -FilePath $nativeExe -ArgumentList ('--tray --data-dir "' + $data + '"') -WindowStyle Hidden -PassThru
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do { Start-Sleep -Milliseconds 50; $handle = [PublicUiTest]::Window($native.Id) } while ($handle -eq [IntPtr]::Zero -and $watch.ElapsedMilliseconds -lt 10000)
    if ($handle -eq [IntPtr]::Zero -or [PublicUiTest]::IsWindowVisible($handle)) { throw '--tray did not start hidden' }
    [PublicUiTest]::MoveOffscreen($handle)
    $second = Start-Process -FilePath $nativeExe -ArgumentList ('--data-dir "' + $nativeDataAlias + '"') -WindowStyle Hidden -PassThru
    if (-not $second.WaitForExit(5000)) { throw 'Second instance remained running' }
    $watch.Restart()
    do {
        Start-Sleep -Milliseconds 20
        $handle = [PublicUiTest]::Window($native.Id)
    } while (($handle -eq [IntPtr]::Zero -or -not [PublicUiTest]::IsWindowVisible($handle)) -and $watch.ElapsedMilliseconds -lt 5000)
    if (-not [PublicUiTest]::IsWindowVisible($handle)) { throw 'First normal handoff did not restore the hidden native window' }
    [PublicUiTest]::Hide($handle)
    $third = Start-Process -FilePath $nativeExe -ArgumentList ('--tray --data-dir "' + $nativeDataAlias + '"') -WindowStyle Hidden -PassThru
    if (-not $third.WaitForExit(5000) -or [PublicUiTest]::IsWindowVisible($handle)) { throw 'Duplicate --tray should exit without showing the resident' }
    Write-Output 'PASS: a real packaged-style --tray process starts hidden; normal and --tray instances using a junction alias hand off to the same resident.'
} finally {
    if ($window -and -not $window.IsDisposed) { [PublicUiTest]::Dispose($window) }
    if ($aliasWindow -and -not $aliasWindow.IsDisposed) { [PublicUiTest]::Dispose($aliasWindow) }
    foreach ($process in @($native, $second, $third)) {
        if ($process -and -not $process.HasExited) {
            if ($process.MainModule.FileName -ne $nativeExe) { throw 'Refusing to stop a non-fixture process' }
            Stop-Process -Id $process.Id
        }
    }
}
Write-Output "Artifacts: $testRoot"
