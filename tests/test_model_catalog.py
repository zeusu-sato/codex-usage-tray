import unittest
from unittest.mock import patch

import model_catalog as catalog
from quota_monitor import QuotaError, request_metadata


def model(name, description="Our most capable model for complex, demanding work.", efforts=("medium", "high", "ultra"), default=False):
    return {"model": name, "displayName": name, "description": description, "hidden": False, "isDefault": default,
            "supportedReasoningEfforts": [{"reasoningEffort": e, "description": e} for e in efforts]}


class ModelCatalogTest(unittest.TestCase):
    def test_official_top_description_wins_without_using_default_or_names(self):
        cheaper = model("gpt-999-mini", "Fast and affordable model.", default=True)
        top = model("unknown-future-name")
        self.assertIs(catalog.highest_model([cheaper, top]), top)

    def test_unknown_future_model_can_replace_astra(self):
        old = model("gpt-6-astra", "Previous-generation model.")
        future = model("next-flagship", "Our most intelligent model for demanding tasks.")
        self.assertIs(catalog.highest_model([old, future]), future)

    def test_ambiguous_or_absent_top_claim_does_not_guess(self):
        for models in ([model("one"), model("two")], [model("default", "Recommended for everyday work.", default=True)]):
            with self.assertRaises(catalog.SelectionError):
                catalog.highest_model(models)

    def test_scoped_superlative_does_not_prove_overall_top_model(self):
        with self.assertRaises(catalog.SelectionError):
            catalog.highest_model([model("small", "Our most capable small model.")])

    def test_advertised_upgrade_prevents_stale_automatic_choice(self):
        old = model("old")
        old["upgrade"] = "new"
        with self.assertRaises(catalog.SelectionError):
            catalog.highest_model([old])

    def test_maximum_supported_effort_ignores_order_and_default(self):
        self.assertEqual(catalog.highest_effort(model("top", efforts=("ultra", "low", "max"))), "ultra")
        self.assertEqual(catalog.highest_effort(model("top", efforts=("high", "xhigh"))), "xhigh")

    def test_unknown_new_effort_never_silently_selects_lower_known_effort(self):
        with self.assertRaises(catalog.SelectionError):
            catalog.highest_effort(model("top", efforts=("ultra", "future-higher")))

    def test_metadata_catalog_handles_pages_and_filters_hidden_models(self):
        hidden = {**model("hidden"), "hidden": True}
        pages = [{"data": [hidden, model("one", "Everyday model.")], "nextCursor": "next"},
                 {"data": [model("top")], "nextCursor": None}]
        with patch.object(catalog, "request_metadata", side_effect=pages) as read:
            self.assertEqual([m["model"] for m in catalog.catalog("binary")], ["one", "top"])
            self.assertEqual(read.call_args.args, ("binary", "model/list", {"limit": 100, "includeHidden": False, "cursor": "next"}))

    def test_complete_catalog_is_required(self):
        with patch.object(catalog, "request_metadata", return_value={"data": [model("one")], "nextCursor": "same"}):
            with self.assertRaises(catalog.SelectionError):
                catalog.catalog("binary")

    def test_unambiguous_selection_does_not_ask_or_invoke_ai(self):
        with patch.object(catalog, "catalog", return_value=[model("future-top")]):
            read = unittest.mock.Mock(side_effect=AssertionError("No input should be needed"))
            selected = catalog.select_for_review("binary", read)
            self.assertEqual(selected["model"], "future-top")
            self.assertEqual(selected["effort"], "ultra")
            read.assert_not_called()

    def test_ambiguous_catalog_requires_explicit_choice_before_any_inference(self):
        with patch.object(catalog, "catalog", return_value=[model("one"), model("two")]):
            selected = catalog.select_for_review("binary", lambda text: "2")
            self.assertEqual(selected["model"], "two")
            self.assertEqual(selected["model_selection"], "explicit_user_selection")
            with self.assertRaises(catalog.SelectionError):
                catalog.select_for_review("binary", lambda text: "q")

    def test_metadata_transport_rejects_model_execution_before_spawning(self):
        with patch("quota_monitor.subprocess.Popen") as popen:
            for forbidden in ("turn/start", "thread/start", "review/start", "mcpServer/tool/call"):
                with self.assertRaises(QuotaError):
                    request_metadata("binary", forbidden)
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
