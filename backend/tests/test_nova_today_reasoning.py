import unittest

from app.core.nova.today.reasoning import is_self_contained_math_request, readable_calculation


SCHOOL_QUESTION = (
    "A school has a $7,200 budget and must buy exactly 20 devices. Laptops cost $450 each; "
    "tablets cost $250 each. The school needs at least 12 laptops. The supplier gives a "
    "10% discount, then charges 8% sales tax on the discounted price. What is the greatest "
    "number of laptops the school can buy without exceeding its budget? Show your calculations, "
    "explain why one additional laptop would exceed the budget, and explain the solution to a sixth-grade student."
)


class ReasoningRoutingTests(unittest.TestCase):
    def test_self_contained_questions(self):
        for text in [
            SCHOOL_QUESTION,
            "A club has $950 and needs 10 items costing $50 or $120 each. Calculate the maximum expensive items.",
            "Calculate the total cost of 7 books at $12 each after a 15% discount.",
            "Solve 3x + 2 = 14 and explain each step.",
            "A train travels 180 miles in 3 hours. Calculate its average speed.",
        ]:
            with self.subTest(text=text):
                self.assertTrue(is_self_contained_math_request(text))

    def test_fresh_facts_and_browsing_are_not_bypassed(self):
        for text in [
            "Search the web for the best supplier prices for 20 laptops under $7200.",
            "Calculate the cost of 20 laptops using current supplier prices under $7200.",
            "Find suppliers for 20 devices priced $250 to $450 each.",
            "Who won the NBA game yesterday, 120 to 110?",
            "What is Anthony Edwards current status?",
            "What is the weather in Minneapolis today?",
            "Explain the school enrollment process.",
            "Calculate grant eligibility with 20 employees and a $7200 budget.",
            "Calculate how much tax I legally owe on $7200 with a $250 deduction.",
        ]:
            with self.subTest(text=text):
                self.assertFalse(is_self_contained_math_request(text))

    def test_math_text_is_readable_without_changing_the_values(self):
        text = r"**Budget:** \(194.4x + 4860 \leq 7200\). \(x \leq \frac{2340}{194.4} \approx 12.04\). \(7400 \times 0.9 \times 1.08 = 7192.80\)."
        out = readable_calculation(text)
        self.assertEqual(out, "Budget: 194.4x + 4860 ≤ 7200. x ≤ (2340)/(194.4) ≈ 12.04. 7400 × 0.9 × 1.08 = 7192.80.")
        self.assertEqual(readable_calculation(r"\frac{1}{\frac{2}{3}}"), "(1)/((2)/(3))")

    def test_plain_text_and_unknown_notation_are_preserved(self):
        text = "12 laptops, 8 tablets, total $7,192.80, $7.20 remaining."
        self.assertEqual(readable_calculation(text), text)
        self.assertEqual(readable_calculation(r"\sqrt{x}"), r"\sqrt{x}")

    def test_formatting_remains_text_not_html(self):
        self.assertEqual(readable_calculation("**<script>danger()</script>**"), "<script>danger()</script>")


if __name__ == "__main__":
    unittest.main()
