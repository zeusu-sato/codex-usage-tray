# v0.3.0 — Codex + Claude tray monitoring

[Windows x64 download and source](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.3.0). Early beta with a Japanese interface. The sections below preserve earlier release history.

- Adds separate Codex and Claude tray icons with one shared tabbed window and provider-specific state. Local official extension symbols appear at 18% opacity; without an available image, only the number and gauge appear. Images are not bundled.
- Adds experimental Claude metadata reads for **exactly 2.1.263**, using only initialization and `get_usage` controls. Other versions stop before the metadata session starts. Only the global five-hour and weekly windows are included; partial or unsupported responses cannot report current allowance. Model-specific limits and extra usage remain outside the display.
- Preserves known amounts when reset time is absent, without inventing a reset or a forecast for that window. Local salted HMAC account scope separates history without saving raw account metadata; missing identity prevents forecasting. Small reset-time jitter keeps same-cycle history away from reset boundaries, without changing the displayed reset time.
- Routine checks and forecasts use no AI inference. Claude review runs through Codex only after **Yes** and consumes Codex allowance, using the existing best-available-model / maximum-supported-reasoning selection flow. Enabling a reviewed Claude proposal separately targets `CLAUDE.md`; Codex retains `AGENTS.md`.

The Claude control interface is internal and experimental. Local implementation and fixture checks do not establish support for other versions, accounts, or future service behavior. Existing review safeguards and the lack of a general Usage-saving guarantee still apply.

## 日本語

**v0.3.0のWindows x64版とソースを公開しました。** 日本語UIの初期ベータ版です。下記には旧リリースの履歴も残しています。

- Codex・Claudeの2個の通知領域アイコンと、共通タブ画面を追加します。状態は製品別に保存します。インストール済み公式拡張機能のシンボルを不透明度18%で使い、画像がなければ数字とゲージのみ表示します。画像は同梱しません。
- Claudeの内部メタデータ取得は**2.1.263限定**です。他版では取得用起動前に停止し、全体の5時間枠・週間枠が揃わない応答も未確認扱いにします。モデル別制限・追加利用分は対象外です。
- リセット時刻がない枠も既知の残量は表示しますが、その枠の予測はしません。ローカルsaltによるHMACで履歴の連続性を区別し、アカウント情報の原文は保存しません。識別できない場合は予測を保留します。
- 通常監視・概算のAI推論はありません。ClaudeのAI見直しも、**はい**を選んだ場合だけCodexで行い、CodexのUsageを消費します。モデル・推論強度の選択と確認は従来と同じです。候補を別途ONにしたときの適用先はClaudeが`CLAUDE.md`、Codexが`AGENTS.md`です。

内部APIの実験的な対応であり、他のバージョンやアカウント、将来のサービス変更への対応を保証しません。Usage削減を一般的に保証するものでもありません。

---

# v0.2.0 — spending outlook and switch repaint fix

[Windows x64 download and source](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.2.0). This remains an early beta with a Japanese interface.

- Tray and headline colors now estimate whether the recent spending pace will last until reset: green for margin, yellow for caution, red for likely shortage. The number remains the actual reported percentage. A separate outlook label explains the estimate.
- Gray numbers distinguish an unready forecast from unknown quota (`?`). Weekly forecasts need about one hour of observations; five-hour windows need about 30 minutes. Multiple windows use the least favorable outlook.
- Bounded local arithmetic reuses existing five-minute readings, with at most 24 hours / 289 timestamp-percentage pairs per window. It adds no AI inference, network requests, polling, or continuous analysis process. Reset changes, refills, clock reversals, and client changes restart the relevant history.
- Reporting precision and a margin are accounted for. This is a rough projection including idle time; changed work patterns can change the outcome.
- The ON/OFF switch now paints an opaque background every time, preventing old text from showing behind it after a layout or status update.

The existing no-AI monitoring, optional review consent, and optional policy controls are unchanged. See [Privacy](PRIVACY.md) for local history storage and [README](../README.md) for the calculation and limits.

## 日本語

残量の数字はそのままに、最近の消費ペースで次のリセットまで持つかを色で表示します。緑は余裕あり、黄はペースに注意、赤は不足しそう、灰色の数字は判定待ち・見通し未確認です。残量自体が未確認の場合は引き続き`?`を表示します。

Weeklyでは約1時間、5時間枠では約30分の履歴から判定を始めます。既存の5分ごとの取得データだけを使う軽い計算で、AIも通信も取得頻度も増えません。リセットや残量補充などで履歴を区切ります。今後の使い方が変われば見通しも変わる目安です。

ON/OFFトグルの背景を毎回塗り直し、更新前の文字が裏に透けて見える不具合も修正しました。

---

# v0.1.0 — initial beta

Unofficial Codex Usage Tray for **Windows x64**, with a **Japanese interface**. [Download the ZIP or browse the source](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.1.0).

## Included

- Remaining Codex allowance as a tray number and gauge, with reset information on hover and per-window detail in the main window.
- Metadata-only quota checks at startup and every 5 minutes; local client checks every 15 minutes; manual refresh.
- Explicit selection when multiple supported Codex installations are found.
- Change notifications and an optional AI review, started only after **Yes**. Current official model metadata determines the best available model and maximum supported reasoning effort when unambiguous; otherwise the visible console asks before inference. It uses Standard speed, existing approval controls, and a `workspace-write` sandbox scoped to the review folder.
- A readable review report and optional additional instructions. First run uses native Codex behavior with no added policy. Only a separate ON action applies a reviewed proposal to an app-owned, guarded global AGENTS block.
- Single instance per data directory, hidden `--tray` startup, and opt-in Windows login startup.
- A ZIP containing the native Windows Forms UI and a PyInstaller one-directory backend. End users do not need a separate Python installation. Existing Codex and its login are required.

## Limits of this release

- Initial observation is labeled as a monitoring reference, not a verified workaround. There is no universal Usage-saving claim or established causal claim about subagent behavior.
- Quota is a delayed server snapshot, not a live token meter. Unknown/stale data uses `?`; reset times do not create assumed 100% readings. The headline reflects the lowest reported Codex window, without combining unrelated pools.
- The UI and confirmation dialogs are Japanese. Date/time labels currently use JST (UTC+9).
- Windows controls tray icon visibility. Drag the icon out of **^** to keep it visible.
- Additional instructions affect global Codex guidance only after the user enables a proposal. Changed or unverifiable clients stop an old policy from applying. There is no calendar expiry or automatic baseline approval.
- No app self-update, automatic AI retries, weaker-model fallback, or recurring online research. The explicitly requested AI review can use online research and consumes Codex allowance.
- Account/client/API combinations that cannot provide the supported metadata remain unknown. Codex is not bundled.

See [Privacy](PRIVACY.md) for local files, AI consent, and removal. Application code is MIT licensed; bundled dependencies retain their own licenses. This is an independent project, not an OpenAI release.

## 日本語

**Windows x64・日本語UIの初期ベータ版**です。通知領域にCodexの残量とゲージを表示し、5分ごとの残量取得、15分ごとのローカルなバージョン確認、手動更新に対応します。Pythonの別途インストールは不要です。Codex本体のインストールとログインは必要です。

通常の監視ではAIを使いません。変更通知または手動操作から **はい** を選んだときだけ、利用可能な最上位モデル・最大推論強度での見直しを依頼します。公式カタログだけでは選べない場合は、推論前にコンソールで選択を求めます。**いいえ・Escape・×ではAIを開始しません**。

初回は追加対策なしでCodexの通常動作を使います。見直し結果を読み、必要な候補をユーザーが有効にした場合だけ、グローバルAGENTSへ条件付き指示を追加します。初回の監視基準を「対策済み」とは扱わず、Usage削減も保証しません。

残量には反映遅れがあり、未確認時は`?`を表示します。時刻はJSTです。常時表示には **^** 内からアイコンをドラッグしてください。ログイン時起動は任意で、アプリの更新は手動です。
