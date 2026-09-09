# Announcement draft

Draft for **one bilingual post**. No platform has been selected and this file does not mean a post has been published. Publish only after the repository and v0.2.0 release links are live. Any accompanying screenshot must use fixture values and carry a visible **Demo / テスト用データ** label.

---

I made **Codex Usage Tray**, an unofficial Windows tray app for keeping Codex's reported remaining allowance and reset time in view.

The number shows actual remaining quota; its color estimates whether your recent spending pace will last until reset. Green suggests margin, yellow suggests caution, and red suggests a likely shortage. This rough local calculation reuses the existing readings, adding no AI or network requests.

Quota refreshes every 5 minutes; local version checks run every 15 minutes. Routine monitoring uses no AI inference. If you choose **Yes**, a visible Codex session can review a client change using the most capable currently available model and maximum supported reasoning effort; ambiguous selection is confirmed before inference. You can read its report before enabling any optional instructions.

**v0.2.0 is an early beta: Windows x64, Japanese UI, source + ZIP, no separate Python installation.** It uses your existing Codex installation and login. It starts with no added policy and makes no promise of Usage savings.

[Source](https://github.com/zeusu-sato/codex-usage-tray) · [Windows release](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.2.0)

---

CodexのUsage残量とリセット時刻を通知領域で確認できる、非公式Windowsアプリ **Codex Usage Tray** を作りました。

数字は実残量、色は最近の消費ペースでリセットまで持つかの目安です。緑は余裕あり、黄はペース注意、赤は不足しそう。既存の取得データを使う軽い計算なので、AIも通信も増えません。

残量は5分ごと、ローカルなバージョン確認は15分ごと。通常の監視ではAI推論を使いません。**はい** を選んだ場合だけ、画面に見えるCodexで、その時点の最上位モデル・最大推論強度による見直しを依頼できます。モデル選択が曖昧なら推論前に確認し、報告書を読んでから必要な追加指示を有効にできます。

**v0.2.0はWindows x64・日本語UIの初期ベータ版です。ソースとZIPを公開し、Pythonの別途インストールは不要です。** 既存のCodexとログインを使います。初回は追加対策なしの通常動作で、Usage削減を保証するものではありません。

[ソースコード](https://github.com/zeusu-sato/codex-usage-tray) · [Windows版](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.2.0)
