"""Conservative, deterministic checks for the supported demo question vocabulary.

This is a bounded input guard, not a general natural-language understanding model.
It never turns a textual assertion into an authoritative business field.
"""

import re
import unicodedata


def normalize(question):
    return unicodedata.normalize("NFKC", question).lower()


def identity_conflict(question, customer):
    assertions = set()
    # Require an explicit assertion; mentioning a new-customer coupon is not an identity claim.
    for clause in re.split(r"[，,。！？!?；;]", normalize(question)):
        if re.search(r"如果|假如|假设|例如|比如|是否|是不是", clause):
            continue
        for match in re.finditer(
            r"(?:我|本人|客户|顾客|买家|又)\s*(?P<neg>不是|并非|非|是|为)\s*(?:一名)?(?P<kind>新|老)(?:客户|客|用户)",
            clause,
        ):
            value = match["kind"] == "新"
            if match["neg"] in {"不是", "并非", "非"}:
                value = not value
            assertions.add(value)
    if len(assertions) > 1:
        return "问题文字中的客户身份互相矛盾，请明确确认本次订单的客户身份。"
    if customer is not None and assertions and customer not in assertions:
        stated = "新客户" if True in assertions else "老客户"
        selected = "新客户" if customer else "老客户"
        return f"客户身份冲突：问题文字表述为{stated}，表单选择为{selected}。请确认后再计算优惠。"
    return None


def unsupported_reason(question, cart):
    """Return an explicit boundary explanation, or None for known promotion language.

    Mixed questions are rejected as a whole rather than silently answering only
    their promotion fragment. Unknown codes fail closed even alongside NEW30.
    """
    text = normalize(question)
    outside = (
        "退款",
        "退货",
        "换货",
        "售后",
        "七天无理由",
        "运费",
        "包邮",
        "物流",
        "配送",
        "发票",
        "天气",
        "股票",
        "导出",
        "客户信息",
        "积分",
        "会员价",
        "refund",
        "return",
        "shipping",
        "delivery",
        "weather",
    )
    topics = [term for term in outside if term in text]
    if topics:
        return (
            "out_of_scope",
            "本次问题涉及“"
            + "、".join(topics)
            + "”，当前不支持核验这些事项，也不会用商品优惠方案代替回答。"
            "请单独询问本演示店铺的 D1 户外九折或 NEW30 新客券。",
        )
    if re.search(
        r"(?:不要|不用|别|无需|不需要)(?:再)?(?:检查|核验|计算|分析|诊断)?(?:任何)?(?:优惠|折扣|促销)",
        text,
    ):
        return ("declined_promotion", "你要求不进行促销诊断，本次不计算或推荐优惠方案。")
    known = {"new30", "d1", "d2", "r1", "r2", "r3", "r4"}
    known.update(normalize(item["sku"]) for item in cart)
    tokens = set(re.findall(r"(?<![a-z0-9_])[a-z][a-z0-9_-]*\d[a-z0-9_-]*(?![a-z0-9_])", text))
    # Also catch letter-only codes when explicitly introduced as a coupon code.
    tokens.update(
        re.findall(r"(?:优惠码|优惠券|券码)\s*[:：为是]?\s*[\"'“‘]?([a-z][a-z0-9_-]*)", text)
    )
    unknown = sorted(tokens - known)
    if unknown:
        return (
            "unknown_code",
            "未收录或无法识别优惠对象“"
            + "、".join(unknown)
            + "”，无法核验其资格或金额。本演示仅支持 D1 户外九折与 NEW30 新客券；"
            "请核对优惠码，当前不会推荐另一张券来代替回答。",
        )
    terms = (
        "优惠",
        "折扣",
        "九折",
        "满减",
        "清仓",
        "叠加",
        "活动",
        "new30",
        "d1",
        "d2",
        "打折",
        "便宜",
        "省钱",
        "划算",
        "减价",
        "discount",
        "coupon",
        "promotion",
    )
    if not any(term in text for term in terms):
        return (
            "unrecognized_question",
            "未识别到支持的促销问题。当前仅核验 D1 户外九折、清仓排除、"
            "NEW30 新客券、优惠组合和活动时间；请说明要核验的优惠或商品。",
        )
    return None
