"""Behavioral contract for monetary and eligibility decisions."""

import copy
import importlib.util
import json
import unittest

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
CART = [
    {
        "sku": "P1",
        "name": "户外外套",
        "price": "250.00",
        "quantity": 1,
        "collection": "outdoor",
        "tags": [],
    },
    {
        "sku": "P2",
        "name": "清仓背包",
        "price": "150.00",
        "quantity": 1,
        "collection": "outdoor",
        "tags": ["clearance"],
    },
]
AT = "2026-10-15T12:00:00+08:00"


class RuleTests(unittest.TestCase):
    def evaluate(self, cart=None, customer=True, at=AT, policy=None):
        self.assertIsNotNone(
            importlib.util.find_spec("commerceops.rules"), "The domain rule evaluator must exist"
        )
        from commerceops.rules import evaluate_cart

        return evaluate_cart(
            copy.deepcopy(CART if cart is None else cart),
            customer,
            at,
            copy.deepcopy(POLICY if policy is None else policy),
        )

    def plans(self, result):
        return {p["id"]: p for p in result["plans"]}

    def test_clearance_exception_and_original_subtotal_coupon(self):
        r = self.evaluate()
        p = self.plans(r)
        self.assertEqual(r["subtotal"], "400.00")
        self.assertEqual(p["D1"]["total"], "375.00")
        self.assertEqual(p["D2"]["total"], "370.00")
        self.assertFalse(p["D1+D2"]["eligible"])
        self.assertIsNone(p["D1+D2"]["total"])
        self.assertEqual(r["recommended_plan"], "D2")
        item_checks = [c for c in r["checks"] if c["rule_id"] == "R1"]
        self.assertEqual(len(item_checks), 2)
        self.assertIn("P1", item_checks[0]["detail"])
        self.assertIn("P2", item_checks[1]["detail"])
        self.assertEqual([c["result"] for c in item_checks], ["pass", "fail"])
        self.assertEqual({c["rule_id"] for c in r["checks"]}, {"R1", "R2", "R3", "R4"})
        self.assertTrue(all(c["evidence_ids"] == [c["rule_id"]] for c in r["checks"]))
        json.dumps(r, allow_nan=False)

    def test_unknown_new_customer_does_not_choose_known_but_worse_plan(self):
        r = self.evaluate(customer=None)
        self.assertTrue(self.plans(r)["D1"]["eligible"])
        self.assertIsNone(self.plans(r)["D2"]["eligible"])
        self.assertIsNone(r["recommended_plan"])
        self.assertIn("is_new_customer", r["missing_fields"])
        self.assertEqual(next(c for c in r["checks"] if c["rule_id"] == "R2")["result"], "unknown")

    def test_returning_customer_gets_item_discount(self):
        r = self.evaluate(customer=False)
        self.assertFalse(self.plans(r)["D2"]["eligible"])
        self.assertEqual(r["recommended_plan"], "D1")

    def test_coupon_threshold_inclusive_original_price(self):
        for price, eligible, total in [("350.00", True, "320.00"), ("349.99", False, None)]:
            with self.subTest(price=price):
                r = self.evaluate(cart=[dict(CART[0], price=price)])
                self.assertEqual(self.plans(r)["D2"]["eligible"], eligible)
                self.assertEqual(self.plans(r)["D2"]["total"], total)

    def test_time_window_start_inclusive_end_exclusive_and_equivalent_offsets(self):
        for at, active in [
            (POLICY["starts_at"], True),
            ("2026-09-30T16:00:00Z", True),
            (POLICY["ends_at"], False),
            ("2026-09-30T15:59:59Z", False),
        ]:
            with self.subTest(at=at):
                r = self.evaluate(at=at)
                self.assertEqual(
                    next(c for c in r["checks"] if c["rule_id"] == "R4")["result"],
                    "pass" if active else "fail",
                )
                if not active:
                    self.assertIsNone(r["recommended_plan"])
                    self.assertTrue(all(p["eligible"] is False for p in r["plans"]))

    def test_missing_tags_or_collection_is_unknown_and_not_recommended(self):
        for field in ["tags", "collection"]:
            cart = copy.deepcopy(CART)
            cart[0].pop(field)
            with self.subTest(field=field):
                r = self.evaluate(cart=cart)
                self.assertIsNone(self.plans(r)["D1"]["eligible"])
                self.assertIsNone(r["recommended_plan"])
                self.assertTrue(any(field in f for f in r["missing_fields"]))
                self.assertEqual(r["checks"][0]["result"], "unknown")

    def test_explicit_empty_tags_is_eligible(self):
        self.assertTrue(self.plans(self.evaluate())["D1"]["eligible"])

    def test_known_scope_exclusion_does_not_require_tags(self):
        r = self.evaluate(cart=[dict(CART[0], collection="home", tags=None)])
        self.assertFalse(self.plans(r)["D1"]["eligible"])
        self.assertEqual(r["checks"][0]["result"], "fail")

    def test_quantities_and_decimal_rounding(self):
        r = self.evaluate(cart=[dict(CART[0], price="0.15", quantity=3)], customer=False)
        self.assertEqual(r["subtotal"], "0.45")
        self.assertEqual(self.plans(r)["D1"]["total"], "0.41")

    def test_coupon_never_creates_negative_payable_amount(self):
        p = dict(POLICY, minimum="0.00", coupon_amount="30.00")
        r = self.evaluate(cart=[dict(CART[0], price="10.00")], policy=p)
        self.assertEqual(self.plans(r)["D2"]["total"], "0.00")

    def test_explicit_stackable_policy_combines_discount_then_coupon(self):
        r = self.evaluate(policy=dict(POLICY, stackable=True))
        self.assertEqual(self.plans(r)["D1+D2"]["total"], "345.00")
        self.assertEqual(r["recommended_plan"], "D1+D2")

    def test_invalid_price_inputs_are_rejected(self):
        for price in [
            "-0.01",
            "NaN",
            "Infinity",
            "-Infinity",
            "1e999999",
            "invalid",
            True,
            None,
            1.5,
        ]:
            with self.subTest(price=price), self.assertRaises(ValueError):
                self.evaluate(cart=[dict(CART[0], price=price)])

    def test_invalid_quantities_are_rejected(self):
        for quantity in [True, False, 1.0, "1", 0, -1, None, 1000000000000]:
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.evaluate(cart=[dict(CART[0], quantity=quantity)])

    def test_invalid_cart_shapes_are_rejected(self):
        for cart in [
            [],
            {},
            [None],
            [dict(CART[0], tags="clearance")],
            [dict(CART[0], tags=[True])],
            [dict(CART[0], collection=5)],
            [dict(CART[0], sku="")],
        ]:
            with self.subTest(cart=cart), self.assertRaises(ValueError):
                self.evaluate(cart=cart)

    def test_invalid_customer_type_is_not_coerced(self):
        for customer in [0, 1, "false", "true", {}]:
            with self.subTest(customer=customer), self.assertRaises(ValueError):
                self.evaluate(customer=customer)

    def test_invalid_or_naive_timestamps_are_rejected(self):
        for at in ["2026-10-01", "2026-10-01T00:00:00", "yesterday", None]:
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.evaluate(at=at)

    def test_invalid_policies_are_rejected(self):
        updates = [
            {"discount_rate": "1.01"},
            {"discount_rate": "-0.1"},
            {"discount_rate": "NaN"},
            {"minimum": "-1"},
            {"coupon_amount": "Infinity"},
            {"stackable": "false"},
            {"starts_at": POLICY["ends_at"]},
            {"ends_at": "2026-10-01"},
            {"excluded_tag": ""},
            {"collection": None},
        ]
        for update in updates:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.evaluate(policy=dict(POLICY, **update))
        with self.assertRaises(ValueError):
            self.evaluate(policy={})


if __name__ == "__main__":
    unittest.main()
