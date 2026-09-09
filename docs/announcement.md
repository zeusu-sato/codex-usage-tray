# Codex + Claude Usage — v0.3.0

Platform copy and publication evidence: [promotion/README.md](promotion/README.md).

**Update: v0.3.0 adds Claude Code support.** I made **Codex Usage Tray**, an unofficial Windows tray app, to check allowance without reopening the usage menus in VS Code.

It now shows Codex and Claude in two tray icons, with faint provider symbols behind readable percentages. Color gives a rough outlook from recent spending: green for margin until reset, yellow for caution, red for a likely shortage, gray while the outlook is unavailable. It reuses five-minute readings; routine monitoring and the arithmetic use no AI inference. Weekly forecasts need about an hour of history; five-hour windows need about 30 minutes.

One window contains both providers' quotas, local version checks, and separate optional instruction switches. AI review starts only after **Yes** and consumes Codex allowance, even for a Claude review. Proposed instructions remain off until you enable them. No promise of quota savings.

**Claude support is experimental and pinned to Claude Code 2.1.263**, using its internal metadata controls. It covers global five-hour and weekly windows only, excluding model-specific limits and extra usage. Unsupported versions pause Claude quota reads.

**Windows x64 beta, Japanese UI, JST times.** Source and a Windows ZIP are available; no separate Python installation is needed. The app uses your installed clients and logins and is independent of OpenAI and Anthropic. Feedback on tray readability and the usefulness of the outlook would be welcome.

[Source](https://github.com/zeusu-sato/codex-usage-tray) · [Windows ZIP](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.3.0) · [New demo — synthetic data](https://raw.githubusercontent.com/zeusu-sato/codex-usage-tray/v0.3.0/docs/images/demo.png)

---

**v0.3.0でClaude Code対応を追加しました。** CodexとClaudeの残量をWindowsの通知領域に並べて表示します。数字は取得した残量、色は最近のペースでリセットまで持つかの概算です。通常の監視と計算はAI推論を使いません。

共通画面で両方の残量・バージョン・任意の対策を管理できます。「はい」を押した場合だけCodexのUsageを使うAI見直しを開始し、追加指示は自分でONにするまで適用しません。

Claudeは2.1.263限定の試験対応で、全体の5時間枠・週間枠が対象です。モデル別制限や追加利用分は含まず、未確認の版では取得を停止します。Windows x64・日本語UI・JST表示のベータ版です。

Post text prepared with AI assistance / 告知文の作成にAIを使用しています。
