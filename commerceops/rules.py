"""Deterministic demo promotion rules; money never passes through float.

Discounts round once per cart line (quantity included), half-up to cents.
The coupon threshold uses the original cart subtotal. Unknown eligibility
remains distinct from rejection and prevents a final recommendation.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _decimal(value, field, maximum=Decimal("1000000")):
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError(f"{field} 必须是有效的十进制数字字符串")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} 不是有效金额") from exc
    if not number.is_finite() or number < 0 or number > maximum:
        raise ValueError(f"{field} 必须为范围内的非负有限数字")
    if number.as_tuple().exponent < -6:
        raise ValueError(f"{field} 精度最多为六位小数")
    return number


def _time(value, field):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError(f"{field} 必须是带时区的 ISO8601 时间")
    try:
        parsed = datetime.fromisoformat(value)
        aware = parsed.tzinfo is not None and parsed.utcoffset() is not None
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须是带时区的 ISO8601 时间") from exc
    if not aware:
        raise ValueError(f"{field} 必须包含时区")
    return parsed


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{field} 必须是非空文本，且不超过 200 字符")
    return value


def _money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _check(rule, state, code, detail):
    return {
        "rule_id": rule,
        "result": "unknown" if state is None else "pass" if state else "fail",
        "reason_code": code,
        "detail": detail,
        "evidence_ids": [rule],
    }


def evaluate_cart(cart: list[dict], is_new_customer: bool | None, at: str, policy: dict) -> dict:
    """Evaluate one bounded cart against a complete policy snapshot.

    Missing collection/tags and customer status are business unknowns.
    Invalid amounts, quantities, dates or policy shape raise ValueError.
    No input is mutated; the returned dictionary is directly JSON-safe.
    """
    if type(is_new_customer) not in (bool, type(None)):
        raise ValueError("is_new_customer 必须为布尔值或 null")
    if not isinstance(policy, dict):
        raise ValueError("policy 必须是规则快照对象")
    required = {
        "snapshot_id",
        "discount_rate",
        "minimum",
        "coupon_amount",
        "excluded_tag",
        "collection",
        "stackable",
        "starts_at",
        "ends_at",
    }
    if required - policy.keys():
        raise ValueError("policy 缺少字段：" + ", ".join(sorted(required - policy.keys())))
    _text(policy["snapshot_id"], "snapshot_id")
    excluded_tag = _text(policy["excluded_tag"], "excluded_tag")
    collection = _text(policy["collection"], "collection")
    rate = _decimal(policy["discount_rate"], "discount_rate", Decimal("1"))
    minimum = _money(_decimal(policy["minimum"], "minimum"))
    coupon = _money(_decimal(policy["coupon_amount"], "coupon_amount"))
    if type(policy["stackable"]) is not bool:
        raise ValueError("stackable 必须为布尔值")
    now = _time(at, "at")
    start = _time(policy["starts_at"], "starts_at")
    end = _time(policy["ends_at"], "ends_at")
    if start >= end:
        raise ValueError("活动开始时间必须早于结束时间")
    active = start <= now < end
    if not isinstance(cart, list) or not 1 <= len(cart) <= 100:
        raise ValueError("购物车必须包含 1 至 100 项商品")

    checks, missing, item_states = [], [], []
    subtotal, discounted = ZERO, ZERO
    for index, item in enumerate(cart):
        prefix = f"cart[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} 必须是商品对象")
        sku = _text(item.get("sku"), f"{prefix}.sku")
        _text(item.get("name"), f"{prefix}.name")
        price = _money(_decimal(item.get("price"), f"{prefix}.price"))
        quantity = item.get("quantity")
        if type(quantity) is not int or not 1 <= quantity <= 10000:
            raise ValueError(f"{prefix}.quantity 必须是 1 至 10000 的整数")
        item_collection, tags = item.get("collection"), item.get("tags")
        if item_collection is not None:
            _text(item_collection, f"{prefix}.collection")
        if tags is not None:
            if not isinstance(tags, list) or len(tags) > 100:
                raise ValueError(f"{prefix}.tags 必须是文本列表或 null")
            for tag in tags:
                _text(tag, f"{prefix}.tags")
        line = price * quantity
        subtotal += line
        if not active:
            state, code, detail = (
                False,
                "OUTSIDE_WINDOW",
                f"{sku} 对应活动未生效，不再核验商品范围和标签。",
            )
        elif tags is not None and excluded_tag in tags:
            state, code, detail = (
                False,
                "EXCLUDED_TAG",
                f"{sku} 含排除标签 {excluded_tag}，不参加商品折扣。",
            )
        elif item_collection is not None and item_collection != collection:
            state, code, detail = (
                False,
                "OUTSIDE_COLLECTION",
                f"{sku} 不属于活动范围 {collection}。",
            )
        elif item_collection is None or tags is None:
            state, code, detail = (
                None,
                "MISSING_ITEM_SCOPE",
                f"{sku} 的活动范围或商品标签缺失，暂不能确认商品折扣。",
            )
            if item_collection is None:
                missing.append(f"{prefix}.collection")
            if tags is None:
                missing.append(f"{prefix}.tags")
        else:
            state, code, detail = (
                True,
                "ITEM_ELIGIBLE",
                f"{sku} 属于 {collection} 且无排除标签，参加商品折扣。",
            )
        item_states.append(state)
        discounted += _money(line * rate) if state is True else line
        checks.append(_check("R1", state, code, detail))

    if not active:
        coupon_state, code = False, "OUTSIDE_WINDOW"
        detail = "活动未生效，新客券不可用，无需补充客户身份。"
    elif subtotal < minimum:
        coupon_state, code = False, "BELOW_MINIMUM"
        detail = f"原价合计 {subtotal:.2f} 元，未达到 {minimum:.2f} 元门槛。"
    elif is_new_customer is None:
        coupon_state, code = None, "MISSING_NEW_CUSTOMER"
        detail = f"原价合计 {subtotal:.2f} 元达到门槛，但新客身份尚未确认。"
        missing.append("is_new_customer")
    elif not is_new_customer:
        coupon_state, code, detail = (
            False,
            "NOT_NEW_CUSTOMER",
            "已确认非新客，不满足新客优惠券资格。",
        )
    else:
        coupon_state, code = True, "COUPON_ELIGIBLE"
        detail = f"已确认新客，原价合计 {subtotal:.2f} 元达到 {minimum:.2f} 元门槛。"
    checks.append(_check("R2", coupon_state, code, detail))
    stackable = policy["stackable"]
    checks.append(
        _check(
            "R3",
            stackable,
            "STACK_ALLOWED" if stackable else "STACK_FORBIDDEN",
            "商品折扣与新客券允许叠加。" if stackable else "商品折扣与新客券禁止叠加，须分别比较。",
        )
    )
    checks.append(
        _check(
            "R4",
            active,
            "ACTIVE" if active else "OUTSIDE_WINDOW",
            "查询时间处于活动有效期内（含起点、不含终点）。"
            if active
            else (
                "活动尚未开始，活动优惠不可用。" if now < start else "活动已结束，活动优惠不可用。"
            ),
        )
    )

    discount_state = None if None in item_states else any(item_states)
    if not active:
        discount_state = coupon_state = False
    if not stackable or discount_state is False or coupon_state is False:
        combined_state = False
    elif discount_state is None or coupon_state is None:
        combined_state = None
    else:
        combined_state = True

    plans = []
    for plan_id, label, state, amount in [
        ("D1", "商品活动折扣", discount_state, discounted),
        ("D2", "新客满减券", coupon_state, max(ZERO, subtotal - coupon)),
        ("D1+D2", "商品折扣与新客券叠加", combined_state, max(ZERO, discounted - coupon)),
    ]:
        plans.append(
            {
                "id": plan_id,
                "label": label,
                "eligible": state,
                "total": f"{amount:.2f}" if state is True else None,
            }
        )
    available = [p for p in plans if p["eligible"] is True]
    recommended = None
    if active and not missing and available:
        recommended = min(available, key=lambda p: Decimal(p["total"]))["id"]
    return {
        "checks": checks,
        "plans": plans,
        "missing_fields": missing,
        "subtotal": f"{subtotal:.2f}",
        "recommended_plan": recommended,
    }
