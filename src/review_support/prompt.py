import json
from client_registry import fingerprint


def build_prompt(reference, current):
    target = fingerprint(current)
    template = {"schema_version": 1, "review_complete": True, "fingerprint": target,
                "summary": "根拠に基づく結論", "instructions": "不要・未検証なら空文字",
                "sources": ["https://official.example/exact-source"],
                "validation": ["確認した項目と結果"], "quality_preserved": True}
    text = f"""ユーザーはCodex Usage Trayで明示的にYesを選び、Usage対策の見直しを依頼しました。
この作業フォルダーに調査結果と必要な対策案を実装してください。回答とレポートは日本語で。

監視の基準（観測記録であり、対策が有効という証明ではない）: {json.dumps(reference, ensure_ascii=False)}
現在の環境: {json.dumps(current, ensure_ascii=False)}

条件:
- 思考の質・精度が最優先。時間は増えてもよい。選択済みの最上位モデル・最大推論強度を維持する。
- モデル、推論強度、必要な文脈、証拠、独立検証を削ってUsageを減らさない。SubAgentの一律禁止や必要な検証の省略を対策にしない。
- 現在の公式情報とローカルの実装・設定を確認する。バージョンの不一致だけでは不具合や改善済みと断定しない。因果関係や節約率を捏造しない。
- 公式側の改善を妨げる古い対策は不要と判断する。固定解除日は設けない。
- 通常の常駐監視にAI推論を導入しない。推論を使う反復ベンチマーク、外部への投稿、認証情報の読み出し・出力は禁止。
- 書き込み対象はこの作業フォルダー。ユーザーのグローバル設定、AGENTS.md、親フォルダーの状態や配布アプリを変更しない。
- 追加指示を提案するなら、根拠・副作用・検証方法をreport.mdに記録し、品質を保つ条件付きの最小限の指示にする。
- instructionsはユーザーが別途ONを選んだときのみ、所有マーカーで囲まれたAGENTS.mdの追加指示として適用される。
- 検証できない対策はinstructionsを空文字にして、その制約と必要な次の手順を報告する。完成した根拠がないならreview_completeをfalseにする。

完了時はこのフォルダーのreport.mdに根拠・結論・変更案・検証・残る制約を記録し、review-result.jsonを以下の構造で保存してください。
sourcesは実際に確認した一次情報のURL、validationは実際の確認結果に置き換えてください。
{json.dumps(template, ensure_ascii=False, indent=2)}

対策が不要と確認できた場合、instructionsは空文字でよいです。終了後、このアプリが成果物の形式と環境の一致を確認します。
アプリが見直し済みと記録することは、AIの結論の正しさを独立して保証するものではありません。
"""
    if current.get("provider") == "claude":
        text = text.replace("AGENTS.md", "CLAUDE.md")
        text = "調査対象はVS Codeで使用するClaude Codeです。調査に使うCodexとは別の製品です。Claude Codeの公式資料と対象実装に基づいて判断してください。\n" + text
    return text


