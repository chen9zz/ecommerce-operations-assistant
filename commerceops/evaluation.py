"""Reproducible synthetic business regression; this is not a model quality benchmark."""

import json
import math
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .service import DiagnosisService
from .storage import Store


async def run_evaluation(retriever, output_path: Path, cases_path: Path | None = None):
    cases = json.loads(
        (cases_path or Path(__file__).parent / "data/evaluation_cases.json").read_text()
    )
    results = []
    with tempfile.TemporaryDirectory(prefix="commerceops-eval-") as directory:
        service = DiagnosisService(retriever, Store(Path(directory) / "eval.sqlite3"))
        for case in cases:
            begin = time.perf_counter()
            errors = []
            actual = {}
            try:
                actual = await service.diagnose(case["request"])
                expected = case["expected"]
                for key in (
                    "status",
                    "recommended_plan",
                    "subtotal",
                    "missing_fields",
                    "reason_code",
                ):
                    if key in expected and actual[key] != expected[key]:
                        errors.append(f"{key}: expected {expected[key]!r}, got {actual[key]!r}")
                for phrase in expected.get("answer_contains", []):
                    if phrase not in actual["answer"]:
                        errors.append(f"answer missing expected phrase {phrase!r}")
                for plan_id, total in expected.get("totals", {}).items():
                    plan = next((p for p in actual["plans"] if p["id"] == plan_id), {})
                    if plan.get("total") != total:
                        errors.append(f"{plan_id} expected {total!r}, got {plan.get('total')!r}")
                if actual["status"] in {"resolved", "needs_info"}:
                    if not {"R1", "R2", "R3", "R4"} <= {e["id"] for e in actual["evidence"]}:
                        errors.append("missing required policy evidence")
            except Exception as exc:
                errors.append(f"execution failed ({type(exc).__name__})")
            results.append(
                {
                    "id": case["id"],
                    "question": case["request"]["question"],
                    "expected_status": case["expected"]["status"],
                    "actual_status": actual.get("status", "error"),
                    "passed": not errors,
                    "details": errors,
                    "duration_ms": round((time.perf_counter() - begin) * 1000, 2),
                }
            )
    latencies = sorted(c["duration_ms"] for c in results)
    total = len(results)
    passed = sum(c["passed"] for c in results)
    report = {
        "status": "completed",
        "backend": retriever.backend,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "自建模拟规则与固定购物车的业务回归检查，非真实商家收益、非大模型问答质量或生产性能评测。",
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4),
            "p50_ms": latencies[math.ceil(total * 0.5) - 1],
            "p95_ms": latencies[math.ceil(total * 0.95) - 1],
        },
        "cases": results,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output_path)
    return report
