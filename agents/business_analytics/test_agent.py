from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
import unittest

from . import analyze
from .__main__ import main
from .intent import trained_classifier
from .metrics import DatasetError

HERE = Path(__file__).parent


class TestBusinessAnalyst(unittest.TestCase):
    def test_example_totals_and_comparison(self):
        dataset = (HERE / "example.csv").read_text(encoding="utf-8")
        report = analyze("Почему упала маржа?", csv_text=dataset)
        self.assertEqual(report.intent, "profit")
        self.assertEqual(report.data["metrics"]["profit"]["value"], "134000")
        self.assertEqual(report.data["metrics"]["average_order"]["value"], "1153.846154")
        changes = report.data["comparison"]["changes"]
        self.assertEqual(changes["revenue"], {"value": "10", "unit": "percent"})
        self.assertEqual(changes["margin_pct"], {"value": "-4.060606", "unit": "percentage_points"})
        self.assertIn("Маржа: -4,06 п. п.", report.answer)
        self.assertIn("Выручка выросла, а маржа снизилась", report.answer)
        self.assertEqual(json.loads(json.dumps(asdict(report)))["data"], report.data)

    def test_missing_values_and_zero_denominators(self):
        data = analyze(csv_text="revenue,cost,orders,visits,conversions\n123,,0,0,0\n10,5,0,0,0").data
        self.assertEqual(data["metrics"]["cost"], {"value": "5", "valid_rows": 1, "missing_rows": 1})
        for name in ("profit", "margin_pct", "average_order", "conversion_pct"):
            self.assertIsNone(data["metrics"][name]["value"])

    def test_does_not_compare_partial_months_or_gaps(self):
        for dates in (("2026-01-01", "2026-02-01"), ("2026-01", "2026-03")):
            with self.subTest(dates=dates):
                result = analyze(csv_text=f"period,revenue\n{dates[0]},10\n{dates[1]},20")
                self.assertFalse(result.data["comparison"]["comparable"])
                self.assertEqual(result.data["comparison"]["changes"], {})

    def test_daily_completed_months_can_be_compared(self):
        days = [f"2024-01-{day:02},1" for day in range(1, 32)]
        days.extend(f"2024-02-{day:02},2" for day in range(1, 30))
        report = analyze(csv_text="period,revenue\n" + "\n".join(days)).data
        self.assertTrue(report["comparison"]["comparable"])
        self.assertEqual(report["periods"][1]["metrics"]["revenue"]["value"], "58")

    def test_period_changes_use_unrounded_ratios(self):
        table = "period,ad_revenue,ad_spend\n2026-01,0.000001,10000000000\n2026-02,0.000002,10000000000"
        data = analyze(csv_text=table).data
        self.assertEqual(data["periods"][0]["metrics"]["roas"]["value"], "0.0000000000000001")
        self.assertEqual(data["comparison"]["changes"]["roas"], {"value": "100", "unit": "percent"})

    def test_blocks_comparison_when_rows_have_no_dates(self):
        result = analyze(csv_text="period,revenue\n2026-01,10\n2026-02,15\n,75").data
        self.assertEqual(result["metrics"]["revenue"]["value"], "100")
        self.assertEqual(result["quality"]["missing_period_rows"], 1)
        self.assertFalse(result["comparison"]["comparable"])

    def test_question_can_select_one_month_without_mixing_other_rows(self):
        table = "period,revenue,cost,team\n2026-01,100,120,A\n2026-02,200,150,B\n2026-03,300,190,C"
        result = analyze("Выручка за январь 2026", csv_text=table)
        self.assertEqual(result.data["scope"], {"periods": ["2026-01"], "dataset_rows": 3})
        self.assertEqual(result.data["metrics"]["revenue"]["value"], "100")
        self.assertIsNone(result.data["comparison"])
        self.assertIn("Колонок вне расчёта: 1", result.answer)

    def test_compare_requested_months_and_handle_negative_base(self):
        table = "period,revenue,cost,currency\n2026-01,100,120,KZT\n2026-02,999,150,KZT\n2026-03,300,190,KZT"
        result = analyze("Сравни январь с мартом", csv_text=table)
        comparison = result.data["comparison"]
        self.assertEqual((comparison["previous"], comparison["current"]), ("2026-01", "2026-03"))
        self.assertEqual(comparison["changes"]["revenue"]["value"], "200")
        self.assertEqual(comparison["absolute_changes"]["profit"], "130")
        self.assertNotIn("profit", comparison["changes"])
        self.assertIn("+130 KZT · изменение в единицах показателя", result.answer)

    def test_invalid_period_request_does_not_fall_back_to_latest_data(self):
        table = "period,revenue\n2025-01,120\n2026-01,100\n2026-02,200\n2026-03,300"
        examples = {
            "period_ambiguous": "Покажи выручку за январь",
            "period_missing": "Выручка за 2026-08",
            "period_format": "Выручка за 2026-01-15",
            "period_order": "Выручка с 2026-03 по 2026-01",
            "period_limit": "Сравни 2026-01, 2026-02 и 2026-03",
        }
        for reason, question in examples.items():
            with self.subTest(reason=reason):
                with self.assertRaises(DatasetError) as failure:
                    analyze(question, csv_text=table)
                self.assertEqual(failure.exception.code, reason)

    def test_english_months_do_not_turn_modal_may_into_a_date(self):
        table = "period,revenue\n2026-01,100\n2026-05,200\n2026-06,300"
        self.assertNotIn("scope", analyze("Revenue increased and may rise again", csv_text=table).data)
        self.assertNotIn("scope", analyze("May revenue rise if demand recovers?", csv_text=table).data)
        self.assertEqual(analyze("May revenue", csv_text=table).data["metrics"]["revenue"]["value"], "200")
        for query in ("Compare May and June", "Compare June and May"):
            self.assertEqual(analyze(query, csv_text=table).data["scope"]["periods"], ["2026-05", "2026-06"])

    def test_short_english_months_and_comparison_to_use_requested_data(self):
        table = "period,region,revenue\n2025-12,A,40\n2026-01,A,100\n2026-02,A,200\n2026-03,A,300\n2026-05,A,500"
        for query in ("Compare Jan and Mar", "Compare January to March"):
            with self.subTest(question=query):
                report = analyze(query, csv_text=table).data
                self.assertEqual(report["scope"]["periods"], ["2026-01", "2026-03"])
                self.assertEqual(report["comparison"]["changes"]["revenue"]["value"], "200")
        crossing = analyze("Compare Dec. 2025 to Jan. 2026", csv_text=table).data
        self.assertEqual(crossing["comparison"]["changes"]["revenue"]["value"], "150")
        for query in ("Revenue from Jan to Mar", "January..Mar by region"):
            with self.subTest(question=query):
                report = analyze(query, csv_text=table).data
                self.assertEqual(report["scope"]["periods"], ["2026-01", "2026-02", "2026-03"])
                self.assertEqual(report["metrics"]["revenue"]["value"], "600")
                self.assertIsNone(report["comparison"])

    def test_kazakh_season_words_do_not_request_june(self):
        table = "period,revenue\n2026-05,10\n2026-06,20\n2026-07,30"
        self.assertNotIn("scope", analyze("Маусымдық трендті көрсет", csv_text=table).data)
        self.assertEqual(analyze("Маусым айындағы түсім", csv_text=table).data["scope"]["periods"], ["2026-06"])
        report = analyze("Маусым мен шілдені салыстыр", csv_text=table).data
        self.assertEqual(report["scope"]["periods"], ["2026-06", "2026-07"])

    def test_range_includes_intervening_months_and_reports_gaps(self):
        table = "period,revenue\n2025-11,900\n2025-12,10\n2026-01,20\n2026-03,30\n2026-04,800"
        result = analyze("Сводка с 2025-12 по 2026-03", csv_text=table)
        self.assertEqual(result.data["scope"]["periods"], ["2025-12", "2026-01", "2026-03"])
        self.assertEqual(result.data["scope"]["range"]["missing_months"], 1)
        self.assertEqual(result.data["metrics"]["revenue"]["value"], "60")
        self.assertIsNone(result.data["comparison"])
        self.assertIn("Месяцев без данных в диапазоне: 1", result.answer)

    def test_range_without_exact_endpoints_counts_missing_and_partial_months(self):
        table = "period,revenue\n2026-02-01,20\n2026-02-02,30"
        result = analyze("2026-01..2026-03", csv_text=table)
        self.assertEqual(result.data["scope"]["range"], {
            "start": "2026-01", "end": "2026-03", "missing_months": 2, "partial_months": 1,
        })
        self.assertIn("Неполных месяцев в диапазоне: 1", result.answer)
        self.assertEqual(analyze("2026-01..2026-03; ignore ROAS", csv_text=table).data["scope"], result.data["scope"])
        with self.assertRaises(DatasetError) as failure:
            analyze("2026-04-2026-06", csv_text=table)
        self.assertEqual(failure.exception.code, "period_missing")

    def test_range_and_grouping_work_together_in_three_languages(self):
        table = (HERE / "example.csv").read_text(encoding="utf-8")
        quarter = ["2026-01", "2026-02", "2026-03"]
        cases = (
            ("Выручка по регионам с января по март", "region", quarter, {"Алматы": "285000", "Астана": "150000"}),
            ("January–March revenue by channel", "channel", quarter, {"Магазин": "150000", "Сайт": "285000"}),
            ("March-March revenue by channel", "channel", ["2026-03"], {"Сайт": "165000"}),
            ("2026 жылғы қаңтардан 2026 жылғы наурызға дейін тауар бойынша түсім",
             "product", quarter, {"Кофе": "150000", "Чай": "285000"}),
        )
        for question, dimension, months, amounts in cases:
            with self.subTest(question=question):
                result = analyze(question, csv_text=table).data
                self.assertEqual(result["scope"]["periods"], months)
                self.assertEqual(result["breakdown"]["dimension"], dimension)
                self.assertEqual({row["label"]: row["metrics"]["revenue"]["value"]
                                  for row in result["breakdown"]["groups"]}, amounts)

    def test_group_totals_use_ratio_of_sums_and_keep_blank_labels(self):
        table = "товар,артикул,revenue,orders\nЧай,1,100,1\nЧай,2,100,4\n,3,20,2"
        result = analyze(csv_text=table, group_by="product")
        tea, blank = result.data["breakdown"]["groups"]
        self.assertEqual(tea["label"], "Чай")
        self.assertEqual(tea["metrics"]["average_order"]["value"], "40")
        self.assertEqual(blank["label"], None)
        self.assertEqual(blank["metrics"]["revenue"]["value"], "20")
        self.assertIn("Без значения", result.answer)

    def test_category_requests_use_category_instead_of_product(self):
        table = "product,product_category,revenue\nTea,Drinks,100\nCoffee,Drinks,200\nCake,Food,300"
        report = analyze("Show revenue by product category", csv_text=table).data
        self.assertEqual(report["breakdown"]["dimension"], "category")
        self.assertEqual({row["label"]: row["metrics"]["revenue"]["value"] for row in report["breakdown"]["groups"]},
                         {"Drinks": "300", "Food": "300"})
        with self.assertRaises(DatasetError) as failure:
            analyze("Выручка по категориям товаров", csv_text="product,revenue\nЧай,100")
        self.assertEqual((failure.exception.code, failure.exception.field), ("group_missing", "category"))

    def test_region_codes_and_empty_group_labels_stay_separate(self):
        report = analyze(csv_text="region,revenue\nNA,100\n,30", group_by="region").data
        self.assertEqual([(row["label"], row["metrics"]["revenue"]["value"]) for row in report["breakdown"]["groups"]],
                         [("NA", "100"), (None, "30")])

    def test_group_comparison_requires_both_months(self):
        table = "period,region,revenue\n2026-01,A,100\n2026-01,B,50\n2026-03,A,120\n2026-02,C,1000"
        result = analyze("Сравни 2026-01 и 2026-03 по регионам", csv_text=table)
        first, second = result.data["breakdown"]["groups"]
        self.assertEqual(first["comparison"]["changes"]["revenue"]["value"], "20")
        self.assertFalse(second["comparison"]["comparable"])
        self.assertEqual(second["comparison"]["changes"], {})
        self.assertIn("Для сравнения этой группы нужны полные данные за оба месяца.", result.answer)

    def test_daily_comparison_checks_coverage_per_group(self):
        rows = [f"2026-{month:02}-{day:02},A,1" for month, days in ((1, 31), (2, 28)) for day in range(1, days + 1)]
        rows.extend(("2026-01-01,B,100", "2026-02-01,B,200"))
        table = "period,region,revenue\n" + "\n".join(rows)
        result = analyze("Compare January and February by region", csv_text=table).data
        first, second = result["breakdown"]["groups"]
        self.assertTrue(result["comparison"]["comparable"])
        self.assertTrue(first["comparison"]["comparable"])
        self.assertFalse(second["comparison"]["comparable"])

    def test_invalid_grouping_reports_exact_reason(self):
        table = "revenue,region\n20,A"
        with self.assertRaises(DatasetError) as failure:
            analyze("Выручка по каналам", csv_text=table)
        self.assertEqual((failure.exception.code, failure.exception.field), ("group_missing", "channel"))
        with self.assertRaises(DatasetError) as failure:
            analyze("Выручка по регионам и каналам", csv_text=table)
        self.assertEqual(failure.exception.code, "group_multiple")

    def test_group_labels_cannot_insert_control_characters_into_report(self):
        result = analyze(csv_text="region,revenue\n\x1b[31mA,12", group_by="region")
        self.assertIn("\\x1b", result.answer)
        self.assertNotIn("\x1b", result.answer)

    def test_headers_normalize_consistently_and_keep_physical_line_numbers(self):
        report = analyze(csv_text="ad spend\n50").data
        self.assertEqual(report["metrics"]["ad_spend"]["value"], "50")
        with self.assertRaises(DatasetError) as failure:
            analyze(csv_text="\n\nperiod,revenue\n2026-02-30,10")
        self.assertEqual((failure.exception.code, failure.exception.row), ("date", 4))
        with self.assertRaises(DatasetError) as failure:
            analyze(csv_text="revenue,extra;cost\n1,2;3")
        self.assertEqual(failure.exception.code, "format")

    def test_bom_semicolon_decimal_comma_header_aliases_and_duplicates(self):
        line = "2026-03;1\u202f234,50;234,50;KZT"
        table = f"\ufeffмесяц;выручка;затраты;валюта\n{line}\n{line}"
        result = analyze(csv_text=table)
        self.assertEqual(result.data["metrics"]["revenue"]["value"], "2469")
        self.assertEqual(result.data["metrics"]["profit"]["value"], "2000")
        self.assertEqual(result.data["quality"]["duplicate_rows"], 1)

    def test_fenced_dataset_and_localized_reports(self):
        result = analyze("Түсім қанша?\r\n```csv\r\nperiod,revenue\r\n2026-01,55\r\n```\r\n")
        self.assertEqual(result.language, "kk")
        self.assertIn("Түсім: 55", result.answer)
        result = analyze("What is the revenue?", csv_text="revenue\n55")
        self.assertEqual(result.language, "en")
        self.assertIn("Revenue: 55", result.answer)

    def test_questions_receive_methodology_or_clarification(self):
        self.assertIn("Средний чек =", analyze("Формула среднего чека").answer)
        self.assertIn("ROAS =", analyze("How can I calculate my ROAS?").answer)
        self.assertIn("конверсия =", analyze("Рассчитай конверсию из визитов", language="kk").answer.lower())
        self.assertIsNone(analyze("Дай рецепт пирога").intent)

    def test_multi_topic_answer_covers_both_tasks_and_names_inputs(self):
        response = analyze("Почему упал средний чек? И где теряются клиенты на этапе оплаты?")
        self.assertEqual(set(response.topics), {"sales", "conversion"})
        self.assertEqual(response.intent, response.topics[0])
        self.assertIn("Средний чек =", response.answer)
        self.assertIn("Конверсия =", response.answer)
        self.assertIn("число пользователей на каждом этапе", response.answer)

    def test_report_asks_for_missing_columns_for_named_kpi(self):
        response = analyze("Проверь ROAS", csv_text="revenue,ad_spend\n300,60\n")
        self.assertEqual(response.topics, ("marketing",))
        self.assertIn("добавьте в таблицу колонки ad_revenue", response.answer)
        self.assertNotIn("roas", response.data["metrics"])

    def test_explicit_metric_limits_data_requests_and_explains_unavailable_values(self):
        response = analyze("Посчитай выручку", csv_text="revenue\n250")
        self.assertEqual(response.data["metrics"]["revenue"]["value"], "250")
        self.assertNotIn("orders", response.answer)
        no_orders = analyze("Посчитай средний чек", csv_text="revenue,orders\n100,0")
        self.assertIn("итог по колонке orders должен быть больше нуля", no_orders.answer)
        incomplete = analyze("Посчитай прибыль", csv_text="revenue,cost\n100,\n200,10")
        self.assertIn("заполните пропуски в колонках cost", incomplete.answer)

    def test_mixed_requests_keep_supported_tasks_and_ignore_exclusions(self):
        cases = (
            ("aov, roas, churn", {"sales", "marketing", "retention"}),
            ("Проверь маржу, ROAS и отток", {"profit", "marketing", "retention"}),
            ("Сначала рассчитай конверсию, потом придумай сказку", {"conversion"}),
            ("ROAS не нужен, рассчитай средний чек", {"sales"}),
            ("Compare retention after seven days only; ignore ad spend", {"retention"}),
        )
        for question, expected in cases:
            with self.subTest(question=question):
                self.assertEqual(set(analyze(question).topics), expected)

    def test_advanced_topic_guidance_is_localized_and_names_inputs(self):
        requests = (
            ("Какая точка безубыточности в заказах?", "unit_economics", "ru", "постоянные затраты"),
            ("Қоймадағы тауар қорының айналымын тексер", "inventory", "kk", "күндік қор"),
            ("How should we read the A/B test?", "experiment", "en", "stopping rule"),
        )
        for question, topic, language, evidence in requests:
            with self.subTest(topic=topic):
                response = analyze(question)
                self.assertEqual(response.topics, (topic,))
                self.assertEqual(response.language, language)
                self.assertIn(evidence, response.answer)
                self.assertIsNone(response.data)

    def test_csv_keeps_aggregates_and_gives_guidance_for_advanced_topic(self):
        response = analyze("Сравни удержание по когортам и посчитай ROAS",
                           csv_text="ad_revenue,ad_spend\n90,30")
        self.assertEqual(set(response.topics), {"retention", "marketing"})
        self.assertEqual(response.data["metrics"]["roas"]["value"], "3")
        self.assertIn("обезличенный идентификатор клиента", response.answer)
        self.assertNotIn("retention", response.data["metrics"])

    def test_invalid_data_fails_with_explicit_code(self):
        cases = {
            "width": "revenue,cost\n1,2,3",
            "columns": "revenue,выручка\n1,2",
            "date": "period,revenue\n2026-02-30,4",
            "number": "orders,revenue\n-1,3",
            "mixed_currency": "revenue,currency\n100,KZT\n200,USD",
            "mixed_dates": "period,revenue\n2026-01,2\n2026-02-01,3",
            "empty": "revenue\nn/a",
            "size": "revenue\n" + "1" * (128 * 1024),
        }
        for expected, table in cases.items():
            with self.subTest(reason=expected), self.assertRaises(DatasetError) as failure:
                analyze(csv_text=table)
            self.assertEqual(failure.exception.code, expected)

    def test_intent_evaluation_uses_different_questions(self):
        cases = json.loads((HERE / "test_cases.json").read_text(encoding="utf-8"))
        training = json.loads((HERE / "training.json").read_text(encoding="utf-8"))
        fitted = {text for languages in training.values() for prompts in languages.values() for text in prompts}
        outcomes = []
        model = trained_classifier()
        for intent, questions in cases.items():
            for question in questions:
                self.assertNotIn(question, fitted)
                answer = model.predict(question)
                if intent == "other":
                    self.assertIsNone(answer, question)
                outcomes.append(answer == (None if intent == "other" else intent))
        self.assertGreaterEqual(sum(outcomes) / len(outcomes), 0.9)

    def test_challenge_questions_measure_complete_topic_sets(self):
        cases = json.loads((HERE / "challenge_cases.json").read_text(encoding="utf-8"))
        training = json.loads((HERE / "training.json").read_text(encoding="utf-8"))
        fitted = {text for languages in training.values() for prompts in languages.values() for text in prompts}
        model = trained_classifier()
        counts = {0: [0, 0], 1: [0, 0], 2: [0, 0]}
        for case in cases:
            question = case["question"]
            self.assertNotIn(question, fitted)
            expected = set(case["topics"])
            bucket = counts[len(expected)]
            bucket[0] += set(model.predict_topics(question)) == expected
            bucket[1] += 1
        for size, min_score in ((0, 0.9), (1, 0.9), (2, 0.8)):
            correct, total = counts[size]
            self.assertGreaterEqual(correct / total, min_score, counts)

    def test_advanced_questions_cover_new_topics_and_unrelated_requests(self):
        cases = json.loads((HERE / "advanced_cases.json").read_text(encoding="utf-8"))
        training = json.loads((HERE / "training.json").read_text(encoding="utf-8"))
        fitted = {text for languages in training.values() for prompts in languages.values() for text in prompts}
        model = trained_classifier()
        counts = {0: [0, 0], 1: [0, 0], 2: [0, 0]}
        for case in cases:
            question = case["question"]
            self.assertNotIn(question, fitted)
            expected = set(case["topics"])
            counts[len(expected)][1] += 1
            counts[len(expected)][0] += set(model.predict_topics(question)) == expected
        for size, min_score in ((0, 1.0), (1, 0.9), (2, 0.85)):
            correct, total = counts[size]
            self.assertGreaterEqual(correct / total, min_score, counts)

    def test_cli_example_and_error_exit_codes(self):
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(["--example", "--lang", "en", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["data"]["rows"], 3)
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(["--example", "--group-by", "sku", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["data"]["breakdown"]["dimension"], "sku")
        with redirect_stderr(StringIO()) as errors:
            self.assertEqual(main(["--csv", str(HERE / "missing.csv"), "--json"]), 2)
        self.assertEqual(json.loads(errors.getvalue())["error"], "file")


if __name__ == "__main__":
    unittest.main()
