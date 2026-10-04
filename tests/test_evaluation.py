import importlib
import json
from pathlib import Path


def test_evaluation_records_per_case_results_and_scope(tmp_path):
    assert (Path(__file__).parents[1] / "commerceops/evaluation.py").exists(), (
        "Evaluation runner missing"
    )
    import asyncio

    from commerceops.retrieval import LexicalRetriever, load_evidence

    output = tmp_path / "evaluation.json"
    evaluation = importlib.import_module("commerceops.evaluation")
    result = asyncio.run(evaluation.run_evaluation(LexicalRetriever(load_evidence()), output))
    assert result["summary"]["total"] >= 16
    assert result["summary"]["failed"] == 0
    assert result["backend"] == "lexical-demo"
    assert "非" in result["scope"]
    assert len(result["cases"]) == result["summary"]["total"]
    assert json.loads(output.read_text())["summary"] == result["summary"]


def test_evaluation_exposes_failures_instead_of_dropping_them(tmp_path):
    assert (Path(__file__).parents[1] / "commerceops/evaluation.py").exists(), (
        "Evaluation runner missing"
    )
    import asyncio

    class Empty:
        backend = "empty-test"

        async def search(self, query, mode="mix", limit=6):
            return []

    result = asyncio.run(
        importlib.import_module("commerceops.evaluation").run_evaluation(
            Empty(), tmp_path / "failed.json"
        )
    )
    assert result["summary"]["failed"] > 0
    assert result["summary"]["passed"] + result["summary"]["failed"] == result["summary"]["total"]
    assert any(c["details"] for c in result["cases"] if not c["passed"])


def test_evaluation_checks_question_answer_and_required_clarification(tmp_path):
    """A correct amount alone must not hide an off-topic answer or needless question."""
    import asyncio

    from commerceops.evaluation import run_evaluation
    from commerceops.retrieval import LexicalRetriever, load_evidence

    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                {
                    "id": "deliberately-wrong-answer-expectation",
                    "request": {
                        "question": "优惠码 VIP50 能用吗？",
                        "is_new_customer": True,
                        "at": "2026-10-03T12:00:00+08:00",
                    },
                    "expected": {
                        "status": "unsupported",
                        "answer_contains": ["THIS MUST NOT APPEAR"],
                        "missing_fields": ["is_new_customer"],
                    },
                }
            ]
        )
    )
    result = asyncio.run(
        run_evaluation(LexicalRetriever(load_evidence()), tmp_path / "out.json", cases)
    )
    assert result["summary"]["failed"] == 1
    details = " ".join(result["cases"][0]["details"])
    assert "answer" in details and "missing_fields" in details
