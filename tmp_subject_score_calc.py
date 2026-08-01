import os
import sys
sys.path.insert(0, os.getcwd())
from template_updater import calculate_scores_from_template

candidates = [
    {'name': 'A1 example', 'raw': {'ica1': 45, 'ica2': 50, 'icp1': 50, 'icp2': 50, 'gp1': 45, 'gp2': 45, 'practical': 45, 'mid_term': 45, 'end_term': 100}},
    {'name': 'B2 example', 'raw': {'ica1': 35, 'ica2': 35, 'icp1': 35, 'icp2': 35, 'gp1': 35, 'gp2': 35, 'practical': 40, 'mid_term': 40, 'end_term': 90}},
    {'name': 'B3 example', 'raw': {'ica1': 30, 'ica2': 30, 'icp1': 30, 'icp2': 30, 'gp1': 30, 'gp2': 30, 'practical': 35, 'mid_term': 35, 'end_term': 80}},
    {'name': 'C5 example', 'raw': {'ica1': 25, 'ica2': 25, 'icp1': 25, 'icp2': 25, 'gp1': 25, 'gp2': 25, 'practical': 30, 'mid_term': 30, 'end_term': 65}},
    {'name': 'C6 example', 'raw': {'ica1': 22, 'ica2': 22, 'icp1': 22, 'icp2': 22, 'gp1': 22, 'gp2': 22, 'practical': 25, 'mid_term': 25, 'end_term': 60}},
    {'name': 'D7 example', 'raw': {'ica1': 18, 'ica2': 18, 'icp1': 18, 'icp2': 18, 'gp1': 18, 'gp2': 18, 'practical': 20, 'mid_term': 20, 'end_term': 50}},
    {'name': 'E8 example', 'raw': {'ica1': 15, 'ica2': 15, 'icp1': 15, 'icp2': 15, 'gp1': 15, 'gp2': 15, 'practical': 15, 'mid_term': 15, 'end_term': 40}},
    {'name': 'F9 example', 'raw': {'ica1': 10, 'ica2': 10, 'icp1': 10, 'icp2': 10, 'gp1': 10, 'gp2': 10, 'practical': 10, 'mid_term': 10, 'end_term': 30}},
]
for c in candidates:
    r = calculate_scores_from_template(c['raw'])
    print(c['name'])
    print(' raw', c['raw'])
    print(' result', r)
    print()
