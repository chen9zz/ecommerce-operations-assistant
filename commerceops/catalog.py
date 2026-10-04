"""Self-authored demonstration fixtures, not a real platform policy."""

from copy import deepcopy

DEMO_AT = "2026-10-03T12:00:00+08:00"
CART = [
    {
        "sku": "P1",
        "name": "轻量户外冲锋衣",
        "price": "250.00",
        "quantity": 1,
        "collection": "outdoor",
        "tags": [],
    },
    {
        "sku": "P2",
        "name": "清仓徒步背包",
        "price": "150.00",
        "quantity": 1,
        "collection": "outdoor",
        "tags": ["clearance"],
    },
]
POLICY = {
    "snapshot_id": "demo-v3",
    "discount_rate": "0.90",
    "minimum": "350.00",
    "coupon_amount": "30.00",
    "excluded_tag": "clearance",
    "collection": "outdoor",
    "stackable": False,
    "starts_at": "2026-10-01T00:00:00+08:00",
    "ends_at": "2026-11-01T00:00:00+08:00",
}


def catalog():
    return {
        "shop": {"id": "demo-shop", "name": "山野户外 · 演示店铺"},
        "cart": deepcopy(CART),
        "policy": deepcopy(POLICY),
        "presets": [
            {
                "id": "combination",
                "label": "优惠为什么不能叠加？",
                "question": "P2 为什么没有九折，NEW30 为什么不能叠加？",
                "is_new_customer": True,
                "at": DEMO_AT,
            },
            {
                "id": "unknown",
                "label": "新客信息尚未确认",
                "question": "这笔订单可以使用哪些优惠？",
                "is_new_customer": None,
                "at": DEMO_AT,
            },
            {
                "id": "existing",
                "label": "老客能使用 NEW30 吗？",
                "question": "我是老客，NEW30 为什么无法使用？",
                "is_new_customer": False,
                "at": DEMO_AT,
            },
            {
                "id": "expired",
                "label": "活动到期后会怎样？",
                "question": "为什么九折活动和优惠码都不生效？",
                "is_new_customer": True,
                "at": "2026-11-01T00:00:00+08:00",
            },
        ],
    }
