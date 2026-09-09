"""Select the official catalog's unambiguous flagship at maximum supported effort.

Model names, version numbers, list order, and isDefault are not quality rankings.
If the official description does not identify one flagship, ask in the already
user-opened console before spending any inference Usage.
"""
import re

from quota_monitor import QuotaError, request_metadata


EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
TOP_DESCRIPTION = re.compile(r"^(?:our|the) most (?:capable|intelligent|advanced) model\b", re.I)


class SelectionError(ValueError):
    pass


def clean_text(value, length=500):
    return " ".join(str(value).split())[:length]


def catalog(binary):
    models = []
    cursor = None
    seen = set()
    for _ in range(10):
        params = {"limit": 100, "includeHidden": False}
        if cursor is not None:
            params["cursor"] = cursor
        response = request_metadata(binary, "model/list", params)
        if not isinstance(response.get("data"), list):
            raise SelectionError("モデル一覧を確認できません。AIは起動していません。")
        for model in response["data"]:
            if not isinstance(model, dict) or not isinstance(model.get("model"), str):
                raise SelectionError("未対応のモデル一覧です。AIは起動していません。")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model["model"]):
                raise SelectionError("モデル識別子を確認できません。")
            if model.get("hidden") is True:
                continue
            if "text" not in model.get("inputModalities", ["text", "image"]):
                continue
            if model["model"] in seen:
                raise SelectionError("モデル一覧に重複があります。")
            seen.add(model["model"])
            models.append(model)
        next_cursor = response.get("nextCursor")
        if next_cursor is None:
            if not models:
                raise SelectionError("利用可能なモデルがありません。")
            return models
        if not isinstance(next_cursor, str) or next_cursor == cursor:
            raise SelectionError("モデル一覧の続きを確認できません。")
        cursor = next_cursor
    raise SelectionError("モデル一覧を全件確認できませんでした。")


def highest_model(models):
    candidates = [m for m in models if TOP_DESCRIPTION.search(m.get("description", "").strip())]
    if len(candidates) != 1:
        raise SelectionError("公式カタログから最上位モデルを一意に特定できません。")
    selected = candidates[0]
    # An unresolved advertised upgrade means the old claim may be stale.
    if selected.get("upgrade") and selected["upgrade"] != selected["model"]:
        raise SelectionError("推奨の後継モデルがあります。最上位の確認が必要です。")
    return selected


def efforts(model):
    options = model.get("supportedReasoningEfforts")
    if not isinstance(options, list) or not options:
        raise SelectionError("利用可能な推論強度を確認できません。AIは起動していません。")
    values = []
    for item in options:
        if not isinstance(item, dict) or not isinstance(item.get("reasoningEffort"), str):
            raise SelectionError("未対応の推論強度情報です。")
        value = item["reasoningEffort"]
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", value) or value in values:
            raise SelectionError("推論強度を確認できません。")
        values.append(value)
    return values


def highest_effort(model):
    values = efforts(model)
    if any(v not in EFFORT_ORDER for v in values):
        raise SelectionError("新しい推論強度があるため、最大値の確認が必要です。")
    return max(values, key=EFFORT_ORDER.index)


def choose_number(prompt, count, read_input):
    while True:
        answer = read_input(prompt).strip()
        if not answer or answer.lower() == "q":
            raise SelectionError("AIを起動せず終了しました。")
        if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer) - 1
        print("一覧にある番号、または q を入力してください。")


def select_for_review(binary, read_input=input):
    print("利用可能なモデルと推論強度を確認しています（この照会はAI推論を使いません）。", flush=True)
    try:
        models = catalog(binary)
    except QuotaError:
        raise SelectionError("モデル一覧の取得に失敗しました。AIは起動していません。") from None
    model_choice = "official_top_description"
    try:
        model = highest_model(models)
    except SelectionError as error:
        print(str(error) + " 下位モデルを自動選択せず、一覧を表示します。")
        for index, item in enumerate(models, 1):
            print(f'{index}. {clean_text(item.get("displayName", item["model"]))} [{item["model"]}]')
            print("   " + clean_text(item.get("description", "")))
        model = models[choose_number("最上位として使用するモデル番号（qで中止）: ", len(models), read_input)]
        model_choice = "explicit_user_selection"
    effort_choice = "maximum_supported"
    try:
        effort = highest_effort(model)
    except SelectionError as error:
        print(str(error))
        values = efforts(model)
        for index, item in enumerate(model["supportedReasoningEfforts"], 1):
            print(f'{index}. {item["reasoningEffort"]}: {clean_text(item.get("description", ""))}')
        effort = values[choose_number("最大の推論強度の番号（qで中止）: ", len(values), read_input)]
        effort_choice = "explicit_user_selection"
    return {"model": model["model"], "effort": effort,
            "display_name": clean_text(model.get("displayName", model["model"])),
            "model_selection": model_choice, "effort_selection": effort_choice,
            "official_description": clean_text(model.get("description", ""))}
