import os
import sys
sys.path.insert(0, os.getcwd())
from template_updater import calculate_scores_from_template

candidates = {
    'C4': {'ica1': 28, 'ica2': 28, 'icp1': 28, 'icp2': 28, 'gp1': 28, 'gp2': 28, 'practical': 35, 'mid_term': 35, 'end_term': 70},
    'C5': {'ica1': 26, 'ica2': 26, 'icp1': 26, 'icp2': 26, 'gp1': 26, 'gp2': 26, 'practical': 30, 'mid_term': 30, 'end_term': 65},
    'C6': {'ica1': 25, 'ica2': 25, 'icp1': 25, 'icp2': 25, 'gp1': 25, 'gp2': 25, 'practical': 30, 'mid_term': 30, 'end_term': 65},
    'D7': {'ica1': 20, 'ica2': 18, 'icp1': 20, 'icp2': 18, 'gp1': 20, 'gp2': 18, 'practical': 40, 'mid_term': 41, 'end_term': 50},
    'E8': {'ica1': 15, 'ica2': 15, 'icp1': 15, 'icp2': 15, 'gp1': 15, 'gp2': 15, 'practical': 15, 'mid_term': 15, 'end_term': 40},
    'F9': {'ica1': 10, 'ica2': 10, 'icp1': 10, 'icp2': 10, 'gp1': 10, 'gp2': 10, 'practical': 10, 'mid_term': 10, 'end_term': 30},
    'A1': {'ica1': 45, 'ica2': 50, 'icp1': 50, 'icp2': 50, 'gp1': 45, 'gp2': 45, 'practical': 45, 'mid_term': 45, 'end_term': 100},
    'B2': {'ica1': 35, 'ica2': 35, 'icp1': 35, 'icp2': 35, 'gp1': 35, 'gp2': 35, 'practical': 40, 'mid_term': 40, 'end_term': 90},
    'B3': {'ica1': 30, 'ica2': 30, 'icp1': 30, 'icp2': 30, 'gp1': 30, 'gp2': 30, 'practical': 35, 'mid_term': 35, 'end_term': 80},
}
for grade, raw in candidates.items():
    result = calculate_scores_from_template(raw)
    print(grade, raw, '->', result['final_score'], result['grade'], result['gpa'])
