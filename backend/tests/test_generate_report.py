"""テストレポート生成 — generate_report のテスト

pytest-json-report の JSON から HTML レポートを組み立てる処理を、
ファイル入出力は tmp_path で隔離して検証する。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_report  # noqa: E402
from generate_report import (  # noqa: E402
    MODULE_LABELS,
    _class_name,
    _duration_ms,
    _module_key,
    _skip_reason,
    _test_name,
    build_report,
    main,
)


def test_entry(nodeid="tests/presentation/test_01_security.py::TestHash::test_hashes_passwords",
               outcome="passed", setup=0.001, call=0.02, teardown=0.0, longrepr=None):
    """pytest-json-report のテスト 1 件分のエントリを組み立てる。"""
    entry = {
        "nodeid": nodeid,
        "outcome": outcome,
        "setup": {"duration": setup},
        "call": {"duration": call},
        "teardown": {"duration": teardown},
    }
    if longrepr is not None:
        entry["call"]["longrepr"] = longrepr
    return entry


def report_data(tests=None, **summary):
    """pytest-json-report のレポート全体を組み立てる。"""
    tests = tests if tests is not None else [test_entry()]
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for t in tests:
        counts[t["outcome"]] = counts.get(t["outcome"], 0) + 1
    counts["total"] = len(tests)
    counts.update(summary)
    return {
        "summary": counts,
        "tests": tests,
        "environment": {"Python": "3.12.1", "Platform": "Windows-11"},
        "created": 1_767_225_600.0,
        "duration": 1.234,
    }


class TestModuleLabels:
    """MODULE_LABELS のテスト"""

    def test_covers_every_presentation_module(self):
        """プレゼンテーションテストの全モジュールに日本語ラベルを持つこと"""
        assert len(MODULE_LABELS) == 8

    def test_each_label_has_the_display_fields(self):
        """各ラベルは表示名・アイコン・説明を備えること"""
        for info in MODULE_LABELS.values():
            assert {"label", "icon", "desc"} <= set(info)


class TestModuleKey:
    """_module_key() のテスト"""

    def test_extracts_the_module_name(self):
        """nodeid からモジュール名を取り出すこと"""
        assert _module_key("tests/presentation/test_01_security.py::T::t") == "test_01_security"

    def test_works_without_a_class(self):
        """クラスを持たない nodeid でも動くこと"""
        assert _module_key("tests/test_config.py::test_defaults") == "test_config"

    def test_bare_filename(self):
        """パスを含まない nodeid でも動くこと"""
        assert _module_key("test_run.py") == "test_run"


class TestClassName:
    """_class_name() のテスト"""

    def test_extracts_the_class(self):
        """nodeid からテストクラス名を取り出すこと"""
        assert _class_name("tests/test_a.py::TestThing::test_x") == "TestThing"

    def test_falls_back_when_there_is_no_class(self):
        """クラスが無ければダッシュを返すこと"""
        assert _class_name("tests/test_a.py::test_x") == "—"


class TestTestName:
    """_test_name() のテスト"""

    def test_humanises_the_test_name(self):
        """test_ 接頭辞とアンダースコアを外して読みやすくすること"""
        assert _test_name("tests/test_a.py::T::test_hashes_passwords") == "hashes passwords"

    def test_handles_parametrised_ids(self):
        """パラメータ付きの nodeid も扱えること"""
        assert _test_name("tests/test_a.py::T::test_side[buy]") == "side[buy]"


class TestSkipReason:
    """_skip_reason() のテスト"""

    def test_extracts_the_reason(self):
        """Skipped: 以降のメッセージを取り出すこと"""
        entry = test_entry(outcome="skipped", longrepr="('f.py', 12, 'Skipped: OANDA 未設定')")
        assert _skip_reason(entry) == "OANDA 未設定')"

    def test_falls_back_without_a_reason(self):
        """理由が無ければダッシュを返すこと"""
        assert _skip_reason(test_entry()) == "—"

    def test_reason_is_truncated(self):
        """長い理由は 120 文字までに切り詰めること（表が崩れない）"""
        entry = test_entry(outcome="skipped", longrepr="Skipped: " + "あ" * 300)
        assert len(_skip_reason(entry)) == 120

    def test_searches_every_phase(self):
        """setup フェーズのスキップ理由も拾うこと"""
        entry = test_entry(outcome="skipped")
        entry["setup"]["longrepr"] = "Skipped: 依存パッケージ未導入"

        assert _skip_reason(entry) == "依存パッケージ未導入"


class TestDurationMs:
    """_duration_ms() のテスト"""

    def test_sums_every_phase(self):
        """setup / call / teardown の合計をミリ秒で返すこと"""
        assert _duration_ms(test_entry(setup=0.001, call=0.002, teardown=0.003)) == 6.0

    def test_missing_phases_count_as_zero(self):
        """フェーズ情報が欠けていても 0 として扱うこと"""
        assert _duration_ms({"nodeid": "x", "outcome": "passed"}) == 0.0

    def test_is_rounded_to_one_decimal(self):
        """小数第 1 位に丸めること"""
        assert _duration_ms(test_entry(setup=0.0001234, call=0, teardown=0)) == 0.1


class TestBuildReport:
    """build_report() のテスト"""

    def test_returns_an_html_document(self):
        """完全な HTML ドキュメントを返すこと"""
        html = build_report(report_data())

        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_shows_the_totals(self):
        """合計・成功・失敗・スキップ件数を表示すること"""
        tests = [test_entry(outcome="passed"), test_entry(outcome="failed"),
                 test_entry(outcome="skipped")]
        html = build_report(report_data(tests))

        assert "すべて (3)" in html
        assert "✓ Passed (1)" in html
        assert "✗ Failed (1)" in html
        assert "― Skipped (1)" in html

    def test_shows_the_pass_rate(self):
        """合格率を百分率で表示すること"""
        tests = [test_entry(outcome="passed")] * 3 + [test_entry(outcome="failed")]
        assert "75%" in build_report(report_data(tests))

    def test_empty_run_does_not_divide_by_zero(self):
        """テストが 0 件でも例外を投げないこと"""
        html = build_report({"summary": {}, "tests": []})

        assert "0%" in html

    def test_reports_success(self):
        """全件成功なら合格を示すこと"""
        html = build_report(report_data([test_entry(outcome="passed")]))

        assert "全テスト PASS" in html

    def test_reports_failures(self):
        """失敗があれば件数を示すこと"""
        tests = [test_entry(outcome="failed"), test_entry(outcome="failed")]
        html = build_report(report_data(tests))

        assert "2 件の失敗" in html
        assert "全テスト PASS" not in html

    def test_includes_the_environment(self):
        """実行環境（Python / プラットフォーム）を載せること"""
        html = build_report(report_data())

        assert "3.12.1" in html
        assert "Windows-11" in html

    def test_environment_falls_back_to_a_dash(self):
        """環境情報が無ければダッシュを表示すること"""
        data = report_data()
        data["environment"] = {}

        assert "—" in build_report(data)

    def test_includes_the_total_duration(self):
        """総実行時間を表示すること"""
        assert "1.23s" in build_report(report_data())

    def test_renders_a_row_per_test(self):
        """テスト 1 件につき 1 行を描画すること"""
        tests = [test_entry(outcome="passed"), test_entry(outcome="failed")]
        html = build_report(report_data(tests))

        assert html.count('data-outcome="passed"') == 1
        assert html.count('data-outcome="failed"') == 1

    def test_rows_carry_the_japanese_module_label(self):
        """行にはモジュールの日本語ラベルを表示すること"""
        html = build_report(report_data())

        assert MODULE_LABELS["test_01_security"]["label"] in html

    def test_unknown_modules_fall_back_to_the_filename(self):
        """ラベル未登録のモジュールはファイル名を表示すること"""
        html = build_report(report_data([test_entry(nodeid="tests/test_brand_new.py::T::test_x")]))

        assert "test_brand_new" in html

    def test_skip_reasons_are_shown(self):
        """スキップ理由を行に添えること"""
        tests = [test_entry(outcome="skipped", longrepr="Skipped: OANDA 未設定")]
        html = build_report(report_data(tests))

        assert "OANDA 未設定" in html

    def test_skip_reasons_are_only_shown_for_skips(self):
        """成功した行にはスキップ理由を出さないこと"""
        tests = [test_entry(outcome="passed", longrepr="Skipped: 出てはいけない")]
        html = build_report(report_data(tests))

        assert "出てはいけない" not in html

    def test_groups_tests_into_module_cards(self):
        """モジュールごとにカードをまとめること"""
        tests = [
            test_entry(nodeid="tests/presentation/test_01_security.py::T::test_a"),
            test_entry(nodeid="tests/presentation/test_06_simulation.py::T::test_b"),
        ]
        html = build_report(report_data(tests))

        assert html.count("module-card") >= 2
        assert MODULE_LABELS["test_06_simulation"]["label"] in html

    def test_failing_modules_are_flagged(self):
        """失敗を含むモジュールのカードに失敗スタイルを当てること"""
        tests = [test_entry(outcome="failed")]
        assert 'module-card card-fail' in build_report(report_data(tests))

    def test_passing_modules_are_flagged(self):
        """全件成功のモジュールは成功スタイルにすること"""
        html = build_report(report_data([test_entry(outcome="passed")]))

        assert 'module-card card-pass' in html
        assert 'module-card card-fail' not in html

    def test_fully_skipped_modules_are_flagged(self):
        """全件スキップのモジュールはスキップスタイルにすること"""
        html = build_report(report_data([test_entry(outcome="skipped")]))

        assert 'module-card card-skip' in html

    def test_durations_are_rendered_in_milliseconds(self):
        """各行に実行時間をミリ秒で表示すること"""
        tests = [test_entry(setup=0.0, call=0.05, teardown=0.0)]
        assert "50.0 ms" in build_report(report_data(tests))

    def test_missing_created_timestamp_uses_now(self):
        """実行日時が無くても現在時刻でレポートを作れること"""
        data = report_data()
        data["created"] = 0

        assert "年" in build_report(data)


class TestMain:
    """main() のテスト"""

    def _write_input(self, tmp_path, data=None):
        path = tmp_path / "results.json"
        path.write_text(json.dumps(data if data is not None else report_data()),
                        encoding="utf-8")
        return path

    def test_writes_the_report(self, tmp_path, monkeypatch, capsys):
        """JSON を読み込んで HTML を書き出すこと"""
        src = self._write_input(tmp_path)
        out = tmp_path / "out" / "test_report.html"
        monkeypatch.setattr(sys, "argv",
                            ["generate_report.py", "-i", str(src), "-o", str(out)])

        assert main() == 0
        assert out.read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")

    def test_creates_the_output_directory(self, tmp_path, monkeypatch, capsys):
        """出力先ディレクトリが無ければ作成すること"""
        src = self._write_input(tmp_path)
        out = tmp_path / "deep" / "nested" / "report.html"
        monkeypatch.setattr(sys, "argv",
                            ["generate_report.py", "-i", str(src), "-o", str(out)])
        main()

        assert out.exists()

    def test_missing_input_returns_an_error_code(self, tmp_path, monkeypatch, capsys):
        """入力 JSON が無ければ 1 を返してメッセージを出すこと"""
        monkeypatch.setattr(sys, "argv",
                            ["generate_report.py", "-i", str(tmp_path / "missing.json")])

        assert main() == 1
        assert "見つかりません" in capsys.readouterr().err

    def test_prints_the_summary(self, tmp_path, monkeypatch, capsys):
        """生成後に集計結果を標準出力へ出すこと"""
        tests = [test_entry(outcome="passed"), test_entry(outcome="failed")]
        src = self._write_input(tmp_path, report_data(tests))
        out = tmp_path / "report.html"
        monkeypatch.setattr(sys, "argv",
                            ["generate_report.py", "-i", str(src), "-o", str(out)])
        main()
        stdout = capsys.readouterr().out

        assert "レポートを生成しました" in stdout
        assert "Passed: 1" in stdout
        assert "Failed: 1" in stdout

    def test_default_paths(self, tmp_path, monkeypatch, capsys):
        """引数なしなら tests/report/ 配下を既定で使うこと"""
        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "tests" / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "results.json").write_text(json.dumps(report_data()), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["generate_report.py"])

        assert main() == 0
        assert (report_dir / "test_report.html").exists()

    def test_output_is_utf8(self, tmp_path, monkeypatch, capsys):
        """日本語ラベルが化けないよう UTF-8 で書き出すこと"""
        src = self._write_input(tmp_path)
        out = tmp_path / "report.html"
        monkeypatch.setattr(sys, "argv",
                            ["generate_report.py", "-i", str(src), "-o", str(out)])
        main()

        assert "セキュリティ" in out.read_text(encoding="utf-8")


class TestModuleEntryPoint:
    """スクリプトとしての体裁のテスト"""

    def test_exposes_main(self):
        """main() を公開すること（バッチから呼ばれる）"""
        assert callable(generate_report.main)

    def test_main_returns_an_exit_code(self, tmp_path, monkeypatch, capsys):
        """終了コードを返すこと（CI が成否を判定できる）"""
        monkeypatch.setattr(sys, "argv",
                            ["generate_report.py", "-i", str(tmp_path / "nope.json")])

        assert isinstance(main(), int)
