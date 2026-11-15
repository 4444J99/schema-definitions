"""Tests for bounded per-target failures when CLI inputs are malformed.

A single malformed JSON/YAML input must fail as that target's ordinary FAIL
result -- a bounded one-line parse error -- without aborting the validation
batch or emitting a traceback.
"""

import json
import sys

import pytest

from scripts import validate as validate_script

MINIMAL_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


@pytest.fixture()
def schema_file(tmp_path):
    schema = tmp_path / "minimal.schema.json"
    schema.write_text(json.dumps(MINIMAL_SCHEMA))
    return schema


def run_cli(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["validate.py", *(str(arg) for arg in args)])
    return validate_script.main(), capsys.readouterr()


def write_input(tmp_path, name, text):
    target = tmp_path / name
    target.write_text(text)
    return target


def test_validate_file_reports_bounded_fail_for_malformed_json(tmp_path, schema_file):
    target = write_input(tmp_path, "invalid.json", '{"ok": ')

    ok, errors = validate_script.validate_file(target, schema_file)

    assert ok is False
    assert len(errors) == 1
    assert errors[0].startswith("  cannot load invalid.json: ")
    assert "\n" not in errors[0]


def test_validate_file_reports_bounded_fail_for_malformed_yaml(tmp_path, schema_file):
    pytest.importorskip("yaml")
    target = write_input(tmp_path, "invalid.yaml", "key: [unclosed\n")

    ok, errors = validate_script.validate_file(target, schema_file)

    assert ok is False
    assert len(errors) == 1
    assert errors[0].startswith("  cannot load invalid.yaml: ")
    assert "\n" not in errors[0]


def test_cli_continues_batch_after_malformed_json(tmp_path, schema_file, monkeypatch, capsys):
    invalid = write_input(tmp_path, "invalid.json", '{"ok": ')
    valid = write_input(tmp_path, "valid.json", '{"ok": true}')

    exit_code, captured = run_cli(monkeypatch, capsys, "--schema", schema_file, invalid, valid)

    assert exit_code == 1
    assert "FAIL invalid.json" in captured.out
    assert "cannot load invalid.json" in captured.out
    assert "PASS valid.json" in captured.out
    assert "1 passed, 1 failed" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_cli_malformed_yaml_fails_only_that_target(tmp_path, schema_file, monkeypatch, capsys):
    pytest.importorskip("yaml")
    invalid = write_input(tmp_path, "invalid.yaml", "key: [unclosed\n")
    valid = write_input(tmp_path, "valid.json", '{"ok": true}')

    exit_code, captured = run_cli(monkeypatch, capsys, "--schema", schema_file, invalid, valid)

    assert exit_code == 1
    assert "FAIL invalid.yaml" in captured.out
    assert "PASS valid.json" in captured.out
    assert "1 passed, 1 failed" in captured.out
    assert "Traceback" not in captured.out


def test_cli_valid_inputs_still_pass(tmp_path, schema_file, monkeypatch, capsys):
    first = write_input(tmp_path, "first.json", '{"ok": true}')
    second = write_input(tmp_path, "second.json", '{"ok": false}')

    exit_code, captured = run_cli(monkeypatch, capsys, "--schema", schema_file, first, second)

    assert exit_code == 0
    assert "PASS first.json" in captured.out
    assert "PASS second.json" in captured.out
    assert "2 passed, 0 failed" in captured.out


def test_cli_schema_violation_still_reports_fail(tmp_path, schema_file, monkeypatch, capsys):
    violating = write_input(tmp_path, "violating.json", '{"wrong": 1}')

    exit_code, captured = run_cli(monkeypatch, capsys, "--schema", schema_file, violating)

    assert exit_code == 1
    assert "FAIL violating.json" in captured.out
    assert "0 passed, 1 failed" in captured.out


def test_cli_missing_file_handling_unchanged(tmp_path, schema_file, monkeypatch, capsys):
    missing = tmp_path / "absent.json"

    exit_code, captured = run_cli(monkeypatch, capsys, "--schema", schema_file, missing)

    assert exit_code == 1
    assert f"FAIL {missing}: not found" in captured.out
    assert "Traceback" not in captured.out


def test_cli_ignore_missing_handling_unchanged(tmp_path, schema_file, monkeypatch, capsys):
    missing = tmp_path / "absent.json"

    exit_code, captured = run_cli(monkeypatch, capsys, "--schema", schema_file, "--ignore-missing", missing)

    assert exit_code == 0
    assert f"SKIP {missing}: not found" in captured.out
    assert "0 passed, 0 failed" in captured.out
