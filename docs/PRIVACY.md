# Privacy / プライバシー

This document describes **v0.3.0**, including experimental Claude Code support. This is an independent local Windows application with no project-operated telemetry or analytics endpoint.

## Routine operation

The app launches your installed Codex app server to read quota metadata with `account/rateLimits/read`, after the protocol initialization handshake. The app does not start a conversation or inference turn for quota checks. The installed Codex process may contact its service to obtain that metadata. Local version checks inspect the selected installation without web searches or AI. The API used is described in the [official app-server documentation](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt).

The app does not parse, copy, or request your authentication tokens, passwords, or account credentials. It does not implement its own login or ask you to paste a token. Codex handles authentication through your existing installation. Codex's own network, logging, retention, and telemetry settings remain applicable; “no app analytics” does not mean that Codex operates offline.

### Claude support in v0.3.0

The installed Claude Code **2.1.263** process handles its existing authentication and the network request for usage metadata. The adapter sends only `initialize` and `get_usage` controls with behaviors disabled; it sends no user message or prompt, reads no credential files, and does not call a separate HTTP endpoint. The internal interface is experimental: other versions are rejected before starting the metadata session. Output size, message count, and time are bounded, and the metadata process is cleaned up afterward.

Only global five-hour and weekly quota amounts and reset times leave the adapter, with an optional pseudonymous account scope. The scope is HMAC-SHA256 of bounded account email and, when present, organization, API-provider and token-source **metadata**, using an app-generated 32-byte random salt. Raw account fields are processed only in memory and are not returned, logged, or saved. Token-source metadata describes the authentication source; it is not an authentication token. The salt is local app data, not a provider credential. Missing or invalid account identity prevents history-based forecasting.

The two tray icons may read symbol images from installed official VS Code / Insiders extensions. Images are rendered at 18% opacity, are not uploaded or bundled, and can be absent without preventing numeric quota display.

## Local storage

The default data directory is `%LOCALAPPDATA%\CodexUsageTray`. A custom `--data-dir` keeps the same kinds of files at the chosen path.

In v0.3.0, Codex retains that directory and Claude uses its `providers\claude` subdirectory. Client selection, quota cache, review records, and policy state are separate. The Claude quota cache additionally holds the random scope salt and HMAC identifier; changed scope restarts history. This is pseudonymization, not encryption or guaranteed anonymity.

| Data | Purpose |
| --- | --- |
| Selected client installation, local paths, version and identity reference | Detect the intended client and later changes. Paths can contain your Windows username. |
| Minimal quota snapshot, reset times, fetch timestamps, coarse failure state | Display reported allowance and distinguish current from previous data. |
| Up to 24 hours of timestamp/remaining-percentage pairs, at most 289 per quota window | Estimate whether the observed pace will last until reset. Stored only in the existing quota cache; no prompts or activity contents are collected. |
| Notification signatures and review decisions | Avoid repeating the same notification or automatically starting a declined review. |
| Review requests, reports, evidence, and optional proposals | Let you inspect an explicitly requested AI review and decide whether to enable its proposal. |
| Policy state and instruction-file backups | Apply and remove only the app's owned instructions; preserve the previous file content. |
| Lock files and process identity records | Coordinate local operations and prevent duplicate review runs. |

Files are ordinary local files protected by your Windows account's filesystem permissions; the app does not add encryption. Reports may contain environment details. A backup of `AGENTS.md` can contain your entire pre-existing private instructions. Review those files before sharing them. State, credentials, personal reports, and private backups are not shipped in the source repository or release ZIP.

If you enable login startup, the app also creates its own per-user Startup shortcut. If you enable a reviewed proposal, it writes its owned block to the global Codex `AGENTS.md`, using `CODEX_HOME` when set. Those are separate from the data directory.

The Claude switch instead targets global `CLAUDE.md` under `%USERPROFILE%\.claude`, or `CLAUDE_CONFIG_DIR` when set. Its backup can likewise contain the entire previous file. Enabling one provider's proposal does not enable the other's.

## Only an explicit Yes starts AI

Version changes can open a confirmation, but **No, Escape, and closing that confirmation do not invoke AI**. A direct **Yes** prepares a short-lived request and opens a visible Codex review console. Before inference, the runner reads available-model metadata with `model/list`; uncertain model or reasoning-effort selection requires your choice in that console.

The review itself is an AI task. Its prompt, selected client context, and any material that the review reads can be processed by Codex under your existing account. The review may research official sources and uses your Codex allowance. It uses a `workspace-write` sandbox scoped to the review folder and retains existing approval controls. This is separate from routine quota/version polling, which performs no AI inference or recurring online research.

In v0.3.0, **reviewing Claude Code also runs through Codex and consumes Codex allowance only after Yes**. The confirmation identifies that distinction. It uses the same best-available-model and maximum-supported-reasoning selection flow; uncertain selection requires a choice before inference. Monitoring Claude does not require an AI review.

Reading a completed report or switching an existing proposal on/off does not itself start another AI review. Enabling a proposal is a separate explicit action after the report is available.

## Removal and sharing

Turn off an enabled policy and login startup, then exit the app before deleting its installation. Local reports and backups remain in the data directory until you remove them yourself. Keep any backups you need. If the app's AGENTS block was edited manually, automatic removal protects the edited text; inspect it yourself before deleting related state.

For a public bug report, prefer the app version, Windows version, selected client type/version, a redacted error message, and reproduction steps. Do not attach your data directory, Codex auth files, private AGENTS contents, or full AI review sessions. Demo screenshots should use fixture data and be labeled **Demo**.

## 日本語

Claude Codeの試験対応を含む**v0.3.0**について説明しています。

このアプリ独自のアクセス解析やテレメトリー送信先はありません。定期的な残量取得は、インストール済みCodexを通して公式の`account/rateLimits/read`を呼びます。AIの会話・推論ターンは開始しませんが、残量を取得するCodex自身はサービスと通信する場合があります。バージョン確認はローカル処理です。

Claude対応は、インストール済み**2.1.263**の内部`initialize` / `get_usage`制御だけを使います。追加動作を無効にし、プロンプト・ユーザーメッセージは送りません。他の版では取得用起動前に停止します。認証はClaude自身が扱い、アプリは認証ファイルを読まず、独自のHTTP取得も行いません。出力・時間に上限を設け、終了時に取得用プロセスを片付けます。安定した公開APIではありません。

Claudeでは全体の5時間枠・週間枠だけを取得し、メールと任意の組織・API提供元・認証元のメタデータから、メモリー上でHMAC-SHA256の識別値を作ります。アプリが生成した32バイトのランダムsaltを使い、**アカウント情報の原文は返却・ログ出力・保存しません**。認証元の名称はトークンそのものではありません。saltも認証情報ではなく、ローカル生成データです。識別できない場合は履歴からの予測を行いません。

消費ペースの概算には、既存の5分ごとの取得結果から、各利用枠について最大24時間・289点の時刻と残量だけを保存します。保存先は既存の残量キャッシュです。AI推論、追加の通信、会話内容や作業内容の収集は行いません。

アプリはパスワードや認証トークンを読み取り・コピーせず、ログインも実装しません。既存のCodexが認証を扱い、Codex自身の通信・ログ・データ設定が適用されます。

`%LOCALAPPDATA%\CodexUsageTray`には、対象Codexと監視基準、最小限の残量・時刻、通知への回答、見直し依頼・報告書・根拠・候補、対策状態、操作を調整する記録を保存します。パスにWindowsユーザー名が含まれる場合があります。AGENTSのバックアップには変更前の個人の指示が丸ごと含まれるため、公開しないでください。通常のローカルファイルであり、アプリ独自の暗号化はありません。個人データや認証情報を配布ZIPに同梱しません。

Claudeの状態は、その下の`providers\claude`に分けて保存します。残量キャッシュにはsalt・HMAC識別値・上限付き履歴も保存し、アカウントの変更時には履歴を区切ります。これは仮名化であり、暗号化や完全な匿名性を保証するものではありません。通知領域のシンボルはインストール済み公式拡張機能から読み、不透明度18%で表示します。画像の送信・同梱はせず、見つからなければ数字とゲージだけを表示します。

**はい** を明示的に押したときだけ、表示されるCodexコンソールでAI見直しを始めます。**いいえ・Escape・×では開始しません**。AI見直しのプロンプトや調査対象は既存のCodex設定に従って処理され、Usageを消費します。通常の監視とは異なり、見直しでは公式情報のオンライン調査を行う場合があります。報告書を開く操作や、作成済み候補の有効・無効切り替えだけで、新しいAI見直しは始まりません。

**Claudeの対策見直しにもCodexを使い、はいを選んだ場合だけCodexのUsageを消費します。** 確認画面でその区別を示し、従来と同じ最上位モデル・最大推論強度の選択手順を使います。選択が曖昧なら推論前に確認します。通常のClaude監視にAI見直しは必要ありません。

追加対策を有効にするとグローバルなCodexの`AGENTS.md`へ管理対象ブロックを追加し、ログイン時起動を有効にするとユーザーのStartupに専用ショートカットを作成します。削除前に両方を無効にしてアプリを終了してください。報告書・バックアップは、不要と判断した後に保存先から別途削除できます。公開Issueに保存先全体や認証ファイル、個人の指示、AIの会話全体を添付しないでください。

Claudeの候補を別途有効にした場合は、`%USERPROFILE%\.claude`（または`CLAUDE_CONFIG_DIR`）の`CLAUDE.md`が対象です。製品ごとのスイッチは独立しています。CLAUDEのバックアップにも元の私的な指示が含まれます。
