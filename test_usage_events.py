#!/usr/bin/env python3
import datetime
import unittest

import app


class UsageEventHelpersTest(unittest.TestCase):
    def test_build_usage_event_sanitizes_and_sums_metrics(self):
        analytics_ctx = {
            "request_id": "req-123",
            "user_email": "user@example.org",
            "api_key_owner": "user@example.org",
            "authenticated_via": "api_key",
            "auth_method": "server",
            "endpoint": "/process-url",
            "prompt": "SLTPvM_default.yaml",
            "ocr_only": False,
            "notebook_mode": False,
            "include_wfo": True,
            "include_cop90": True,
        }
        result = {
            "filename": "specimen.jpg",
            "url_source": "https://example.org/specimen.jpg",
            "ocr_info": {
                "gemini-2.5-flash": {
                    "ocr_text": "do not persist this",
                    "tokens_in": 100,
                    "tokens_out": 50,
                    "cost_in": 0.01,
                    "cost_out": 0.02,
                    "total_cost": 0.03,
                    "rates_in": 0.1,
                    "rates_out": 0.2,
                },
            },
            "parsing_info": {
                "model": "gemini-3.1-flash-lite",
                "input": 25,
                "output": 75,
                "cost_in": 0.005,
                "cost_out": 0.006,
            },
            "impact": {
                "total_tokens_all": 250,
                "estimate_watt_hours": 1.5,
                "estimate_grams_CO2": 2.5,
                "estimate_milliliters_water": 3.5,
            },
            "total_request_cost_usd": 0.041,
            "success": {
                "image_available": "True",
                "ocr": "True",
                "llm": "True",
            },
        }

        event = app.build_usage_event(
            analytics_ctx=analytics_ctx,
            result=result,
            status_code=200,
            source_type="url",
            url_source=result["url_source"],
        )

        self.assertEqual(event["request_id"], "req-123")
        self.assertEqual(event["url_host"], "example.org")
        self.assertEqual(event["ocr_tokens_total"], 150)
        self.assertEqual(event["parsing_tokens_total"], 100)
        self.assertEqual(event["total_tokens_all"], 250)
        self.assertTrue(event["success"])
        self.assertNotIn("ocr_text", event["ocr_info"]["gemini-2.5-flash"])

    def test_build_usage_event_marks_url_fetch_failure(self):
        analytics_ctx = {
            "request_id": "req-456",
            "user_email": "user@example.org",
            "api_key_owner": None,
            "authenticated_via": "firebase",
            "auth_method": "user_gemini",
            "endpoint": "/process-url",
            "prompt": "SLTPvM_default.yaml",
            "ocr_only": False,
            "notebook_mode": False,
            "include_wfo": True,
            "include_cop90": True,
        }
        result = {
            "filename": "broken.jpg",
            "ocr_info": {"error": "Failed to fetch URL"},
            "success": {
                "image_available": "False",
                "ocr": "False",
                "llm": "False",
            },
        }

        event = app.build_usage_event(
            analytics_ctx=analytics_ctx,
            result=result,
            status_code=200,
            source_type="url",
            success=False,
            include_in_rollup=False,
            error_type="fetch_failure",
            error_message_safe="Failed to fetch URL",
        )

        self.assertFalse(event["success"])
        self.assertEqual(event["error_type"], "fetch_failure")
        self.assertFalse(event["include_in_rollup"])

    def test_summarize_usage_events_aggregates_counts(self):
        now = datetime.datetime(2026, 5, 12, 12, 0, tzinfo=datetime.timezone.utc)
        events = [
            {
                "event_id": "a",
                "created_at": now,
                "user_email": "one@example.org",
                "auth_method": "server",
                "source_type": "upload",
                "success": True,
                "total_request_cost_usd": 0.10,
                "total_tokens_all": 100,
                "ocr_info": {"gemini-2.5-flash": {"total_cost": 0.02, "total_tokens": 30}},
                "parsing_model": "gemini-3.1-flash-lite",
                "parsing_cost_total_usd": 0.08,
                "parsing_tokens_total": 70,
            },
            {
                "event_id": "b",
                "created_at": now + datetime.timedelta(hours=1),
                "user_email": "two@example.org",
                "auth_method": "user_vertex",
                "source_type": "pdf_page",
                "success": False,
                "total_request_cost_usd": 0.00,
                "total_tokens_all": 0,
                "ocr_info": {},
                "parsing_model": None,
                "parsing_cost_total_usd": 0.0,
                "parsing_tokens_total": 0,
            },
        ]

        summary = app._summarize_usage_events(events)

        self.assertEqual(summary["headline"]["total_events"], 2)
        self.assertEqual(summary["headline"]["failure_count"], 1)
        self.assertEqual(summary["headline"]["total_pdf_pages"], 1)
        self.assertEqual(summary["headline"]["unique_users"], 2)
        self.assertIn("server", summary["auth_method_split"])
        self.assertIn("gemini-2.5-flash", summary["ocr_model_mix"])

    def test_summarize_usage_events_tolerates_malformed_ocr_info(self):
        event = {
            "event_id": "malformed",
            "created_at": datetime.datetime(2026, 5, 12, tzinfo=datetime.timezone.utc),
            "user_email": "one@example.org",
            "success": True,
            "ocr_info": "legacy malformed value",
        }

        summary = app._summarize_usage_events([event])

        self.assertEqual(summary["headline"]["total_events"], 1)
        self.assertEqual(summary["ocr_model_mix"], {})

    def test_daily_rollup_values_are_scoped_by_user_and_day(self):
        event = {
            "created_at": datetime.datetime(2026, 8, 21, 15, 30, tzinfo=datetime.timezone.utc),
            "user_email": "USER@example.org",
            "auth_method": "server",
            "source_type": "pdf_page",
            "endpoint": "/process-pdf-async",
            "success": False,
            "ocr_models": ["gemini-2.5-flash"],
            "parsing_model": "gemini-3.1-flash-lite",
            "total_request_cost_usd": 0.25,
            "total_tokens_all": 500,
        }

        doc_id, values = app._daily_rollup_values(event)

        self.assertTrue(doc_id.endswith("_2026-08-21"))
        self.assertEqual(values["user_email"], "user@example.org")
        self.assertEqual(values["event_count"], 1)
        self.assertEqual(values["failure_count"], 1)
        self.assertEqual(values["total_pdf_pages"], 1)
        self.assertEqual(values["ocr_model_counts"]["gemini-2.5-flash"], 1)

    def test_summarize_daily_rollups_preserves_model_metrics(self):
        rollups = [{
            "date": "2026-08-21",
            "event_count": 3,
            "success_count": 2,
            "failure_count": 1,
            "total_cost_usd": 0.75,
            "total_tokens_all": 1500,
            "total_pdf_pages": 2,
            "auth_method_counts": {"server": 3},
            "auth_method_costs": {"server": 0.75},
            "auth_method_tokens": {"server": 1500},
            "ocr_model_counts": {"gemini-2.5-flash": 3},
            "ocr_model_costs": {"gemini-2.5-flash": 0.15},
            "ocr_model_tokens": {"gemini-2.5-flash": 300},
            "parsing_model_counts": {"gemini-3.1-flash-lite": 3},
            "parsing_model_costs": {"gemini-3.1-flash-lite": 0.60},
            "parsing_model_tokens": {"gemini-3.1-flash-lite": 1200},
        }]

        summary = app._summarize_usage_event_rollups(rollups)

        self.assertEqual(summary["headline"]["total_events"], 3)
        self.assertEqual(summary["headline"]["total_pdf_pages"], 2)
        self.assertEqual(summary["ocr_model_mix"]["gemini-2.5-flash"]["tokens"], 300)
        self.assertEqual(summary["parsing_model_mix"]["gemini-3.1-flash-lite"]["events"], 3)


if __name__ == "__main__":
    unittest.main()
