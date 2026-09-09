# Codex Usage Tray

[日本語](README.ja.md) · [Windows download](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.1.0) · [Privacy](docs/PRIVACY.md)

An unofficial Windows tray app that keeps your reported Codex allowance in view. Hover over its number and gauge for the remaining percentage and reset time; open the window for quota details, client versions, and optional instructions you can review and switch on yourself.

**v0.1.0 is an early beta for Windows x64. The interface is currently Japanese.** This project is independent of OpenAI and is not an official Codex product.

## Get started

1. Install Codex separately and sign in through Codex. The app detects the Codex extension in VS Code / VS Code Insiders, or a `codex.exe` available on `PATH`.
2. Download the Windows x64 ZIP from [Releases](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.1.0), extract the **whole folder**, and run `CodexUsageTray.exe`. Keep its `backend` folder alongside it. The release includes the Python runtime, so you do not need to install Python or Anaconda. Codex itself is not bundled.
3. If more than one supported Codex installation is available, choose the one to monitor. You can change this later with **Codexを選ぶ…**.
4. To keep the number visible, drag its icon from the Windows **^** overflow area into the system tray. Windows controls icon visibility. [Microsoft's taskbar guidance](https://support.microsoft.com/en-us/windows/experience/personalization/customize-the-taskbar-in-windows) explains this setting.

Closing the window keeps the app in the tray. Double-click the icon to reopen it; choose **終了** to exit. Starting the app again opens the existing instance for the same data directory. Login startup is off initially; enable **Windowsログイン時に起動** in the tray menu if wanted. `CodexUsageTray.exe --tray` starts hidden.

## Read the gauge

The app checks quota at startup and every **5 minutes** while running. **更新** or **今すぐ確認** requests a refresh; closely repeated requests are throttled. It uses the installed Codex app server's documented `account/rateLimits/read` method, which supplies rate-limit metadata. These checks do not start an AI conversation or inference turn. [Official app-server documentation](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)

The main number is the smallest remaining percentage among the reported windows of the **Codex** quota bucket. The window shows each reported reset time. Separate model or reserve pools are not combined into that number.

| Display | Meaning |
| --- | --- |
| Green, 30–100% | Reported remaining allowance is at least 30%. |
| Yellow, 10–below 30% | Reported remaining allowance is below 30%. |
| Red, below 10% | Reported remaining allowance is below 10%. |
| `0` | The reported window has no remaining allowance. |
| Gray `?` | Current allowance is unknown, stale, or a server restriction prevents a reliable availability indication. |

An older successful reading may remain in the details, explicitly marked as previous data. The app never assumes a reset means 100% is available. The server may update later than your activity, and the polling interval adds delay. This is a quota snapshot, not a token counter or a prediction of how much work you can finish. Dates and reset times in this release are displayed in **JST (UTC+9)**.

## Version checks and optional AI review

Every **15 minutes**, a local check compares the selected Codex installation with the saved reference. It does not call AI or search the web. The first reference is labeled **監視開始時** (“when monitoring began”): recording a version does **not** establish that it has been reviewed or needs a workaround.

This detects installed client changes. A server-side model, billing, or behavior change without a local update is not detected by this version check; use the manual review action if you notice an unexplained change.

When the client changes, the app alerts you and offers **AIで対策を見直しますか** (“Review the approach with AI?”). You can also choose **AIで見直す…** manually, including before any version change.

- **はい / Yes** is the only action that starts an AI review. It opens a visible Codex console and uses your Codex allowance. The review uses a `workspace-write` sandbox scoped to its review folder and retains the existing approval controls.
- **いいえ / No**, Escape, or closing the confirmation does not start AI. The decline is remembered for that change. You can explicitly request a review again later.
- Before inference, the runner fetches the current `model/list` metadata and aims to use the most capable available model with its maximum supported reasoning effort, at **Standard speed**. The official API provides available models and supported efforts. [Model-list documentation](https://learn.chatgpt.com/docs/app-server#list-models-modellist)
- There is no universal model-quality rank field. Automatic selection requires an unambiguous highest-capability description in the official catalog. Ambiguous descriptions or unknown effort ordering lead to a choice in the console **before inference**. The app does not rank names alphabetically, assume the default is strongest, or silently fall back to a weaker model.

The review produces a report and may propose additional instructions. Choose **見直し結果を開く** to read it. A reference becomes “reviewed” only after a completed result passes the app's checks for its report, evidence records, schema, and matching client identity; starting or merely exiting Codex is insufficient. Those consistency checks do not independently prove the AI's conclusions. AI output still needs your judgment.

## Optional instructions are off by default

The public app starts with **no additional policy** and leaves Codex's normal behavior in place. A review can conclude that no extra instructions are needed. The switch becomes available only when there is an applicable proposal.

After reading the report, switching **追加対策** to **有効** explicitly adds an app-owned, guarded block to your global Codex `AGENTS.md` (`%USERPROFILE%\.codex\AGENTS.md`, or the location set by `CODEX_HOME`). This affects instructions for Codex across projects. Existing user text is preserved and a private backup is saved first. The guard preserves the user's model, reasoning effort, and necessary quality checks.

Switching to **無効** disables the policy and removes only the app's unchanged owned block. If that block was manually edited, the app protects it instead of overwriting it. A changed or unverifiable client, a disabled switch, or a missing/failed guard stops the old policy from applying, including copies in existing conversations. There is no fixed calendar expiry and no automatic reactivation after a client update.

This project makes **no general promise of lower Usage** and does not establish a particular subagent behavior as the cause of excess usage. A proposed instruction is specific to the evidence and environment reviewed.

## Data, troubleshooting, and removal

State is stored under `%LOCALAPPDATA%\CodexUsageTray`: minimal quota snapshots, client preferences and references, notification decisions, review files, and policy records. AGENTS backups can contain your private instructions. These files are not included in the release ZIP. The app does not read or copy credentials; the installed Codex process handles its own login. There is no added app analytics. Codex's own networking, logging, and data settings still apply. See [Privacy](docs/PRIVACY.md).

If the gauge shows `?`, check the selected Codex and its login, use **今すぐ確認**, and inspect the message in the window. An unsupported account, API response, missing client, or unavailable connection can leave the value unknown. This app does not initiate login or require you to paste a token.

To remove the app, first turn off any enabled additional policy and login startup, choose **終了**, then delete the extracted application folder. Remove `%LOCALAPPDATA%\CodexUsageTray` separately only if you no longer need its reports or backups. Move an installation only after disabling startup and any active policy, because those can refer to its executable path. Updates are manual; the app does not update itself or run recurring online research.

## Source and development

The source is [available on GitHub](https://github.com/zeusu-sato/codex-usage-tray) under the [MIT license](LICENSE). The native UI uses Windows Forms / .NET Framework; the backend is Python packaged as a PyInstaller one-directory application. Bundled dependencies retain their own licenses.

To build and run the isolated UI tests on Windows from a source checkout:

```powershell
.\windows\build.ps1
powershell.exe -NoProfile -STA -File .\windows\test-ui.ps1
```

These commands build the UI and exercise a fixture backend. They do not package the production backend or call live AI. See [release notes](docs/RELEASE_NOTES.md) for the scope and limitations of v0.1.0. Please omit quota snapshots, credentials, private instructions, and unredacted review files from public issues.

For a complete portable package, use Windows x64 with CPython 3.13.15 and the .NET Framework compiler:

```powershell
python -m venv .venv
.\packaging\build.ps1 -Python .\.venv\Scripts\python.exe
```

The build installs the pinned tools in `packaging/requirements-build.txt`, runs backend tests, and creates `dist/CodexUsageTray-0.1.0-windows-x64.zip` with `SHA256SUMS.txt`. The Windows workflow also runs UI tests. Both use synthetic review launches; they do not require Codex credentials or run live AI. These tests verify the app's consent and transport behavior, not the accuracy of a future AI review.
