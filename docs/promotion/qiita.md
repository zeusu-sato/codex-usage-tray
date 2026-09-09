---
title: CodexとClaudeの残量をWindowsのトレイに：AIを使わず消費ペースを色で予測
tags:
  - Codex
  - ClaudeCode
  - Windows
  - Python
  - C#
---

CodexやClaude Codeの残量を見るために、毎回VS Codeのメニューを開くのが面倒でした。Windowsの通知領域に残量が見えていて、「このペースなら次のリセットまで持ちそうか」も分かると便利です。

そこで、**Codex Usage Tray**という非公式Windowsアプリを作りました。**v0.3.0ではClaude Codeにも試験対応**し、2つのトレイアイコンを共通画面で管理できるようにしました。数字は各クライアントが報告する残量、色は最近の消費ペースから計算した見通しです。この記事では、通常の監視でAI推論を使わない構成と、軽量な予測処理の実装を紹介します。

![Demo / テスト用データ：Codexは68%・緑、Claudeは24%・黄。追加対策は両方未設定・OFF](https://raw.githubusercontent.com/zeusu-sato/codex-usage-tray/v0.3.0/docs/images/demo.png)

画像はテスト用の値です。実アカウントの残量や個人の設定は含みません。以下は**v0.3.0時点**の実装です。OpenAI・Anthropicの公式アプリではありません。

## 残量を確認する処理と、AIを動かす処理を分ける

構成はWindows Formsの画面・通知領域アイコンと、Pythonのバックエンドです。画面側は`NotifyIcon`を使い、残量を数字と小さなゲージで描画します。

残量取得には、インストール済みCodexのapp-serverが提供する`account/rateLimits/read`を使います。接続ごとに`initialize`の応答を待って`initialized`を送り、その後で残量を読み取ります。これらのメソッドと初期化手順は[公式app-serverドキュメント](https://learn.chatgpt.com/docs/app-server)に記載されています。

Codexの通常監視で送るメソッドは、次の3つです。

```python
ALLOWED_METHODS = frozenset((
    "initialize",
    "initialized",
    "account/rateLimits/read",
))
```

会話や推論ターンを開始するメソッドは呼びません。残量取得は起動時と5分ごとで、手動更新にも短時間の連打を抑える制限を入れています。[取得処理のソース](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/src/quota_monitor.py)

ログインは既存のCodexに任せます。このアプリが認証トークンを読み取ったり、コピーしたりする処理はありません。ただし、Codex自身は残量を取得するためにサービスへ通信する場合があります。**AI推論を使わないことと、通信しないことは別です。**

## Claude Codeにも対応する：内部制御は版を限定する

Claudeはインストール済みCLIの内部制御 `initialize` と `get_usage` を使います。プロンプトやユーザーメッセージは送らず、追加動作を無効にしたメタデータ取得専用のプロセスを起動し、取得後に終了します。[Claude取得アダプター](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/src/claude_adapter.py)

これは安定した公開APIではないため、**現在の対象はClaude Code 2.1.263だけ**にしました。別の版では取得用の起動前に止め、応答形式が未対応の場合も残量を未確認とします。版が変わった後の残量取得には、アプリ側の対応更新が必要です。

表示対象は**全体の5時間枠と週間枠**で、両方が取得できた場合に少ない残量をトレイへ出します。モデル別の制限や追加利用分は含みません。この数字だけで、すべてのモデルを使えると判断することはできません。

Codex・Claudeの履歴と設定は別々に保存します。Claudeでは、取得時のアカウントメタデータからローカルsalt付きHMACを作り、アカウント切り替え前後の履歴を混ぜません。メールなどの原文はメモリー内で処理し、返却・保存しません。識別できない場合は残量だけを表示し、予測を保留します。[保存データの説明](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/docs/PRIVACY.md)

2つのアイコンには、インストール済みの公式拡張機能にあるシンボルを**不透明度18%**で描き、その前面に白い数字を置きます。16pxでは数字を読み取れることを優先しました。シンボル画像が見つからなければ数字とゲージだけで表示し、元のロゴ資産は同梱しません。

## 数字は残量、色はリセットまでの見通し

残り10%でもリセットまで1時間なら持つかもしれません。一方、90%残っていても、減り方が速くリセットが数日先なら不足しそうです。そのため、色を残量の固定しきい値だけで決めるのはやめました。

基本の計算は、過去の残量差を経過時間で割るだけです。

```python
spent = first_remaining - remaining
rate = spent / elapsed_seconds
projected_use = rate * seconds_until_reset
```

`spent`は消費した割合の**パーセントポイント**です。たとえば100%から90%になったら10ポイント。予測は観測していない将来の使い方まで当てるものではなく、休止時間も含む過去の平均ペースを延ばした目安です。

| 色 | このアプリでの意味 |
| --- | --- |
| 緑 | リセットまで余裕がありそう |
| 黄 | 余裕が小さい、または判定に幅がある |
| 赤 | リセット前に不足しそう、または現在の残量が0 |
| 灰色背景の数字 | 残量は取得できているが、見通しは判定待ち・未確認 |
| 灰色背景の`?` | 現在値が未確認、またはサーバーが利用制限を通知 |

複数のCodex利用枠が返る場合、数字には最も少ない残量を、色には最も注意が必要な見通しを使います。トレイの整数表示は小数点以下を切り捨てています。両者が同じ枠になるとは限らないため、詳細には見通しの対象となる枠も表示します。別のモデル用の利用枠は混ぜません。

## 1%の丸め誤差を無視しない

短い履歴や残量1〜2%付近では、報告値の丸めが判定に響きます。「1%残っている」を正確な残量とみなすと、実際には足りない状況を緑にしてしまう可能性があります。

そこでv0.3.0では、消費量と現在残量の両方に1ポイントの幅を持たせました。これは**このアプリで選んだ保守的な計算上の幅**で、APIの精度保証や統計的な信頼区間ではありません。

履歴・リセット時刻・残量が有効で、残量0などの特別な状態を先に処理した後、色は次のように決めています。[実装全体](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/src/usage_forecast.py)

```python
lower_use = max(0, spent - 1.0) / elapsed_seconds * seconds_until_reset
upper_use = (spent + 1.0) / elapsed_seconds * seconds_until_reset
lower_available = max(0, remaining - 1.0)
upper_available = min(100, remaining + 1.0)

if lower_use > upper_available:
    status = "at_risk"       # 少なめに消費すると見積もっても不足
elif upper_use <= lower_available * 0.8:
    status = "comfortable"   # 保守的に見積もった現在残量の20%以上を残せる
else:
    status = "tight"
```

架空の観測値を使うテストでは、次のようになります。いずれも必要な件数・時間の履歴がある場合です。

| 観測した残量 | 観測期間 | リセットまで | 判定 |
| --- | --- | --- | --- |
| 100% → 96% → 90% | 6時間 | 6日 | 赤 |
| 12% → 11% → 10% | 6時間 | 1時間 | 緑 |
| 2% → 2% → 1% | 1時間 | 20分 | 黄 |

## 履歴を小さく保ち、不明なときは判定を保留する

予測のために取得回数は増やしません。既存の5分ごとの取得結果を、既存の残量キャッシュに保存します。

- 保存する履歴は直近24時間まで、各枠につき最大289件、最大3枠。
- 保存値は時刻と残量。同じ5分区間で手動更新した場合は、最後の1点を置き換える。
- リセットや枠の変更、残量増加、時計の巻き戻り、監視対象の変更時には履歴を区切る。Claudeで同じアカウント・枠のリセット時刻が120秒以内だけ揺れた場合は、旧新リセットがともに2分以上先にある間に限り履歴を維持する。画面には取得したリセット時刻をそのまま表示する。
- 判定には3件以上の記録と、Weeklyでは約1時間、5時間枠では約30分の観測が必要。短い枠でも最短15分は待つ。

24時間は**保存する過去の履歴の上限**です。予測する先は、その枠の次のリセット時刻までになります。

取得失敗・古いデータ・利用制限の通知がある場合は、以前の緑を表示し続けません。リセット予定時刻を過ぎただけで100%に戻ったとも扱いません。複数枠のうち一つでも見通しが未確認なら、「全部余裕あり」という意味の緑にはしません。

この部分は小さな配列の処理と四則演算だけです。学習モデル、追加のネットワーク通信、常時分析専用のプロセスは使いません。

## Windowsのトグルで、裏の文字が透けた

画面ではON/OFFをボタン風の表示からスイッチに変えましたが、更新後の画面でトグルの丸い角の部分に別の文字が見えてしまいました。

実機でコントロールの配置を調べても、文字とスイッチの領域は重なっていませんでした。このアプリでは透明な背景を使うのをやめ、スイッチの背景全体を描画のたびに塗り直すことで解消しました。

```csharp
protected override void OnPaint(PaintEventArgs e)
{
    e.Graphics.Clear(Parent == null ? BackColor : Parent.BackColor);
    // この後で、丸いトラック・つまみ・ON/OFFの文字を描く
}
```

実際には`ControlStyles.Opaque`などの設定と`OnPaintBackground`の処理も合わせています。[スイッチのソース](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/windows/UsageToggle.cs)

短い説明と長い説明を交互に表示するテストを用意し、再配置後もスイッチの四隅がフォームの背景色で塗られることを確認しました。単に静止画がきれいに見えるだけでなく、状態を更新した後の描画も確認するのが大事でした。

## AIを呼ぶのは、ユーザーが見直しを依頼したとき

同じ画面で、15分ごとのローカルなCodex・Claudeのバージョン確認も行います。これもAIを使いません。変更があったときの通知、または手動操作から、**「はい」を選んだ場合だけ**、画面に見えるCodexでAIによる見直しを開始します。**Claudeの見直しにもCodexを使い、このときはCodexのUsageを消費します。**

公開版は追加指示なしで起動します。見直しで追加指示が提案されても、報告書を読んでONにするまでは適用しません。ONにするとアプリ管理の条件付き指示をグローバルな指示ファイル（Codexは`AGENTS.md`、Claudeは`CLAUDE.md`）へ追加するため、プロジェクトをまたいで影響します。対象クライアントの変更を確認した場合は旧対策を適用しない条件にし、更新後に自動で再有効化することも避けています。

クライアントのバージョン一致だけでは、サーバー側の挙動変更までは検知できません。特定のサブエージェント動作がUsage増加の原因だと断定したり、Usage削減を保証したりするアプリではありません。

## 試す・コードを読む

Windows x64向けの初期ベータ版です。UIは日本語、時刻はJST表示です。使う製品の既存クライアントとログインが必要です。Claude監視は2.1.263限定で、AI見直しにはCodexも必要です。

- [ソースコードと日本語README](https://github.com/zeusu-sato/codex-usage-tray/tree/v0.3.0)
- [Windows版ZIP](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.3.0)
- [保存データと削除方法](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/docs/PRIVACY.md)

ZIPはフォルダー全体を展開し、`backend`フォルダーを隣に置いたまま`CodexUsageTray.exe`を起動します。Python実行環境を同梱しているため、利用者によるPythonの別途インストールは不要です。通知領域で常に見えるようにするには、Windowsの`^`内からアイコンをドラッグします。

予測処理を読む場合は、[usage_forecast.py](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/src/usage_forecast.py)と[そのテスト](https://github.com/zeusu-sato/codex-usage-tray/blob/v0.3.0/tests/test_usage_forecast.py)が入口です。開発用Pythonがある環境では、リポジトリのルートから次のように確認できます。テストは架空のデータを使い、実アカウントやAI推論を使いません。

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p test_usage_forecast.py
```

## English overview

Codex Usage Tray is an unofficial Windows tray app showing reported Codex quota and a rough color outlook until reset. Routine monitoring reads metadata through the installed Codex app server; it does not start inference turns. Forecasting reuses bounded local history and simple arithmetic, with allowances for rounding and incomplete data. An optional AI review runs only after the user chooses Yes and does consume Codex allowance. The Windows x64 beta includes its Python runtime; the UI is Japanese and time labels use JST.

開発と記事作成にはCodexを使用しています。本文の仕様説明と計算例は、公開コード・テスト・公式ドキュメントと照合しています。
