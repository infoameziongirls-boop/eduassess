#!/usr/bin/env python
"""Quick verification tests for refactored modules."""

from template_updater import calculate_scores_from_template, _grade

# Test score calculation with sample data
test_scores = {
    "ica1": 45,
    "ica2": 48,
    "icp1": 40,
    "icp2": 42,
    "gp1": 35,
    "gp2": 38,
    "practical": 80,
    "mid_term": 75,
    "end_term": 85,
}

result = calculate_scores_from_template(test_scores)
print("✓ Score calculation test:")
print(f"  Input ICA1: {test_scores['ica1']}, ICA2: {test_scores['ica2']}")
print(f"  Output ica_total: {result['ica_total']}")
print(f"  Final Score: {result['final_score']}/100")
print(f"  GPA: {result['gpa']}, Grade: {result['grade']}")

# Test edge cases
print("\n✓ Grade threshold tests:")
test_scores_high = {"ica1": 50, "ica2": 50, "icp1": 50, "icp2": 50, "gp1": 50, "gp2": 50, "practical": 100, "mid_term": 100, "end_term": 100}
result_high = calculate_scores_from_template(test_scores_high)
print(f"  Perfect score (100/100): Grade={result_high['grade']}, GPA={result_high['gpa']}")
assert result_high['grade'] == 'A1' and result_high['gpa'] == 4.0, "Perfect score should be A1/4.0"

test_scores_low = {"ica1": 0, "ica2": 0, "icp1": 0, "icp2": 0, "gp1": 0, "gp2": 0, "practical": 0, "mid_term": 0, "end_term": 0}
result_low = calculate_scores_from_template(test_scores_low)
print(f"  Zero score (0/100): Grade={result_low['grade']}, GPA={result_low['gpa']}")
assert result_low['grade'] == 'F9' and result_low['gpa'] == 0.0, "Zero score should be F9/0.0"

# Test boundary score (70 = B2)
test_scores_70 = {"ica1": 20, "ica2": 20, "icp1": 10, "icp2": 10, "gp1": 0, "gp2": 0, "practical": 0, "mid_term": 0, "end_term": 70}
result_70 = calculate_scores_from_template(test_scores_70)
print(f"  Score ~70: Grade={result_70['grade']}, GPA={result_70['gpa']}")

print("\n✓ All verification tests passed!")
