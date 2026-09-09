# Privacy / プライバシー

This document describes Codex Usage Tray v0.2.0. It is an independent local Windows application. There is no project-operated telemetry or analytics endpoint.

## Routine operation

The app launches your installed Codex app server to read quota metadata with `account/rateLimits/read`, after the protocol initialization handshake. The app does not start a conversation or inference turn for quota checks. The installed Codex process may contact its service to obtain that metadata. Local version checks inspect the selected installation without web searches or AI. The API used is described in the [official app-server documentation](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt).

The app does not parse, copy, or request your authentication tokens, passwords, or account credentials. It does not implement its own login or ask you to paste a token. Codex handles authentication through your existing installation. Codex's own network, logging, retention, and telemetry settings remain applicable; “no app analytics” does not mean that Codex operates offline.

## Local storage

The default data directory is `%LOCALAPPDATA%\CodexUsageTray`. A custom `--data-dir` keeps the same kinds of files at the chosen path.

| Data | Purpose |
| --- | --- |
| Selected Codex installation, local paths, version and identity reference | Detect the intended client and later changes. Paths can contain your Windows username. |
| Minimal quota snapshot, reset times, fetch timestamps, coarse failure state | Display reported allowance and distinguish current from previous data. |
| Up to 24 hours of timestamp/remaining-percentage pairs, at most 289 per quota window | Estimate whether the observed pace will last until reset. Stored only in the existing quota cache; no prompts or activity contents are collected. |
| Notification signatures and review decisions | Avoid repeating the same notification or automatically starting a declined review. |
| Review requests, reports, evidence, and optional proposals | Let you inspect an explicitly requested AI review and decide whether to enable its proposal. |
| Policy state and AGENTS backups | Apply and remove only the app's owned instructions; preserve the previous file content. |
| Lock files and process identity records | Coordinate local operations and prevent duplicate review runs. |

Files are ordinary local files protected by your Windows account's filesystem permissions; the app does not add encryption. Reports may contain environment details. A backup of `AGENTS.md` can contain your entire pre-existing private instructions. Review those files before sharing them. State, credentials, personal reports, and private backups are not shipped in the source repository or release ZIP.

If you enable login startup, the app also creates its own per-user Startup shortcut. If you enable a reviewed proposal, it writes its owned block to the global Codex `AGENTS.md`, using `CODEX_HOME` when set. Those are separate from the data directory.

## Only an explicit Yes starts AI

Version changes can open a confirmation, but **No, Escape, and closing that confirmation do not invoke AI**. A direct **Yes** prepares a short-lived request and opens a visible Codex review console. Before inference, the runner reads available-model metadata with `model/list`; uncertain model or reasoning-effort selection requires your choice in that console.

The review itself is an AI task. Its prompt, selected client context, and any material that the review reads can be processed by Codex under your existing account. The review may research official sources and uses your Codex allowance. It uses a `workspace-write` sandbox scoped to the review folder and retains existing approval controls. This is separate from routine quota/version polling, which performs no AI inference or recurring online research.

Reading a completed report or switching an existing proposal on/off does not itself start another AI review. Enabling a proposal is a separate explicit action after the report is available.

## Removal and sharing

Turn off an enabled policy and login startup, then exit the app before deleting its installation. Local reports and backups remain in the data directory until you remove them yourself. Keep any backups you need. If the app's AGENTS block was edited manually, automatic removal protects the edited text; inspect it yourself before deleting related state.

For a public bug report, prefer the app version, Windows version, selected client type/version, a redacted error message, and reproduction steps. Do not attach your data directory, Codex auth files, private AGENTS contents, or full AI review sessions. Demo screenshots should use fixture data and be labeled **Demo**.

## 日本語

このアプリ独自のアクセス解析やテレメトリー送信先はありません。定期的な残量取得は、インストール済みCodexを通して公式の`account/rateLimits/read`を呼びます。AIの会話・推論ターンは開始しませんが、残量を取得するCodex自身はサービスと通信する場合があります。バージョン確認はローカル処理です。

消費ペースの概算には、既存の5分ごとの取得結果から、各利用枠について最大24時間・289点の時刻と残量だけを保存します。保存先は既存の残量キャッシュです。AI推論、追加の通信、会話内容や作業内容の収集は行いません。

アプリはパスワードや認証トークンを読み取り・コピーせず、ログインも実装しません。既存のCodexが認証を扱い、Codex自身の通信・ログ・データ設定が適用されます。

`%LOCALAPPDATA%\CodexUsageTray`には、対象Codexと監視基準、最小限の残量・時刻、通知への回答、見直し依頼・報告書・根拠・候補、対策状態、操作を調整する記録を保存します。パスにWindowsユーザー名が含まれる場合があります。AGENTSのバックアップには変更前の個人の指示が丸ごと含まれるため、公開しないでください。通常のローカルファイルであり、アプリ独自の暗号化はありません。個人データや認証情報を配布ZIPに同梱しません。

**はい** を明示的に押したときだけ、表示されるCodexコンソールでAI見直しを始めます。**いいえ・Escape・×では開始しません**。AI見直しのプロンプトや調査対象は既存のCodex設定に従って処理され、Usageを消費します。通常の監視とは異なり、見直しでは公式情報のオンライン調査を行う場合があります。報告書を開く操作や、作成済み候補の有効・無効切り替えだけで、新しいAI見直しは始まりません。

追加対策を有効にするとグローバルなCodexの`AGENTS.md`へ管理対象ブロックを追加し、ログイン時起動を有効にするとユーザーのStartupに専用ショートカットを作成します。削除前に両方を無効にしてアプリを終了してください。報告書・バックアップは、不要と判断した後に保存先から別途削除できます。公開Issueに保存先全体や認証ファイル、個人の指示、AIの会話全体を添付しないでください。
