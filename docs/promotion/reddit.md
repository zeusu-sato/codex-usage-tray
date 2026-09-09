I made **Codex Usage Tray**, an unofficial Windows tray app, because I wanted to check my remaining Codex quota without reopening the usage menu in VS Code.

It shows Codex's reported remaining percentage and reset time. Color gives a rough outlook based on recent spending: green for some margin until reset, yellow for caution, red for a likely shortage. It reuses five-minute quota readings; the calculation and routine monitoring use no AI inference. Weekly forecasts need about an hour of history, and changed work patterns can change the outlook.

It also checks the installed Codex version locally. An optional AI review starts only if you choose **Yes**, and that review consumes Codex allowance. Any proposed instructions stay off until you enable them yourself. There is no promise of quota savings.

**v0.2.0 is an early Windows x64 beta, with a Japanese UI and JST time labels.** Source and a Windows ZIP are available; no separate Python installation is needed. It uses your installed Codex and existing login. I'm looking for feedback on tray readability and whether the color estimate is useful in day-to-day coding.

[Source](https://github.com/zeusu-sato/codex-usage-tray) · [Windows ZIP](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.2.0) · [Demo screenshot — synthetic data](https://raw.githubusercontent.com/zeusu-sato/codex-usage-tray/v0.2.0/docs/images/demo.png)

---

Codexの残量を見るために毎回VS Codeのメニューを開くのが面倒で、Windowsの通知領域に表示する非公式アプリを作りました。数字はCodexが報告する残量、色は最近のペースでリセットまで持つかの目安です。通常の監視と計算はAI推論を使いません。

Codexのバージョン確認もでき、「はい」を選んだ場合だけUsageを使うAI見直しを開始します。追加指示は自分で有効にするまで適用されません。Windows x64・日本語UI・日本時間表示の初期ベータ版です。トレイの見やすさや予測の使い勝手について感想をいただけるとうれしいです。

Post text prepared with AI assistance / 告知文の作成にAIを使用しています。
