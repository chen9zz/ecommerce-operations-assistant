"""Bounded diagnosis orchestration: retrieve evidence, then execute approved rules."""

import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from .catalog import CART, POLICY
from .questions import identity_conflict, unsupported_reason
from .rules import evaluate_cart

REQUIRED = {"R1", "R2", "R3", "R4"}
RULE_QUERIES = {
    "R1": "R1 户外商品集合 九折 清仓排除 适用范围",
    "R2": "R2 NEW30 新客 原始商品金额 满350减30 门槛",
    "R3": "R3 D1 D2 优惠组合 互斥 不可叠加",
    "R4": "R4 活动生效时间 2026年10月 有效期 结束时间",
}


class DiagnosisService:
    def __init__(self, retriever, store):
        self.retriever, self.store = retriever, store

    async def diagnose(self, request: dict, parent_id=None, *, customer_confirmed=False):
        started = time.perf_counter()
        cart = request.get("cart") or CART
        # Rule inputs are validated before retrieval so malformed amounts cannot be masked by an outage.
        computed = evaluate_cart(cart, request.get("is_new_customer"), request["at"], POLICY)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "cart": cart,
                    "is_new_customer": request.get("is_new_customer"),
                    "at": request["at"],
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:16]
        result = {
            "id": uuid4().hex,
            "parent_id": parent_id,
            "question": request["question"],
            "decision_context": {
                "is_new_customer": request.get("is_new_customer"),
                "at": request["at"],
                "customer_source": "user_confirmation" if customer_confirmed else "form",
            },
            "status": "unsupported",
            "answer": "首版支持促销活动、清仓排除和优惠组合诊断。请提供相关问题。",
            "backend": self.retriever.backend,
            "knowledge_snapshot": POLICY["snapshot_id"],
            "business_snapshot": "cart-" + fingerprint,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "checks": [],
            "plans": [],
            "missing_fields": [],
            "evidence": [],
            "trace": [],
            "subtotal": computed["subtotal"],
            "recommended_plan": None,
            "warnings": ["自建模拟店铺与规则，非平台现行政策；价格仅含商品金额，不含税费和运费。"],
        }

        def trace(step, detail, since):
            result["trace"].append(
                {
                    "step": step,
                    "detail": detail,
                    "duration_ms": round((time.perf_counter() - since) * 1000, 2),
                }
            )

        trace(
            "绑定业务快照",
            "固定演示店铺 demo-shop，使用 demo-v3 规则；记录商品、资格和业务时间。",
            started,
        )
        conflict = identity_conflict(request["question"], request.get("is_new_customer"))
        active = next(c["result"] == "pass" for c in computed["checks"] if c["rule_id"] == "R4")
        if conflict and not active:
            result["warnings"].append(
                conflict + " 活动未生效，身份不影响本次无优惠结论，无需确认。"
            )
        if customer_confirmed:
            result["warnings"].append(
                "本次按你在继续诊断时明确确认的身份核验，原问题文字保留供追溯。"
            )
        unsupported = unsupported_reason(request["question"], cart)
        if unsupported:
            result["reason_code"], result["answer"] = unsupported
            trace("核对问题范围", result["answer"], started)
        elif conflict and active and not customer_confirmed:
            result.update(
                status="needs_confirmation", answer=conflict, missing_fields=["is_new_customer"]
            )
            trace("核对客户身份", "文字与表单存在冲突，暂停计算并等待明确确认。", started)
        else:
            evidence = {}
            retrieval_failed = False
            try:
                for query in (request["question"], None):
                    if query is None:
                        missing = REQUIRED - evidence.keys()
                        if not missing:
                            break
                        query = "；".join(RULE_QUERIES[k] for k in sorted(missing))
                    begin = time.perf_counter()
                    found = await self.retriever.search(query, mode="mix", limit=6)
                    for item in found:
                        if item.version == POLICY["snapshot_id"] and item.id in REQUIRED:
                            evidence[item.id] = item
                    trace(
                        "检索规则证据",
                        f"本轮返回 {len(found)} 条材料，已覆盖 {len(evidence)}/4 项必要条款。",
                        begin,
                    )
            except Exception:
                retrieval_failed = True
                trace("检索依赖异常", "无法完成证据检索，请检查知识索引或模型服务后重试。", started)
            result["evidence"] = [asdict(evidence[k]) for k in sorted(evidence)]
            missing = REQUIRED - evidence.keys()
            if missing or retrieval_failed:
                result["status"] = "insufficient_evidence"
                result["answer"] = (
                    "当前规则证据不完整，暂不判断优惠资格或推荐方案。请检查知识库后重试。"
                )
                result["warnings"].append(
                    "缺少规则证据：" + "、".join(sorted(missing))
                    if missing
                    else "检索依赖失败，保留已获取材料供核查。"
                )
            else:
                result.update(computed)
                result["status"] = "needs_info" if computed["missing_fields"] else "resolved"
                if computed["missing_fields"]:
                    result["answer"] = (
                        "还需要确认："
                        + "、".join(
                            "客户是否为新客" if x == "is_new_customer" else x
                            for x in computed["missing_fields"]
                        )
                        + "。未知条件不会当作不满足；补充后继续诊断。"
                    )
                else:
                    failures = [c["detail"] for c in computed["checks"] if c["result"] == "fail"]
                    result["answer"] = "；".join(failures) or "已完成优惠条件检查。"
                    rec = next(
                        (p for p in computed["plans"] if p["id"] == computed["recommended_plan"]),
                        None,
                    )
                    if rec:
                        result["answer"] += (
                            f" 在本次已知可用方案中，建议选择 {rec['label']}，商品金额 ¥{rec['total']}。"
                        )
                    else:
                        result["answer"] += " 当前没有可以推荐的活动方案，按原商品金额结算。"
                trace(
                    "执行与证据绑定",
                    "以 Decimal 计算金额，逐项检查资格、排除、互斥和有效时间。",
                    started,
                )
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self.store.save(dict(request, cart=cart), result)
        return result
