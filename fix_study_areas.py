# fix_study_areas.py
# Run once: python fix_study_areas.py

from app import app
from models import SystemConfig, db

CORE_SUBJECTS = [
    'mathematics',
    'general_science',
    'social_studies',
    'english_language',
    'physical_education_health',
    'ict',
]

STUDY_AREA_ELECTIVES = {
    'science_a':              ['biology', 'chemistry', 'physics', 'additional_mathematics'],
    'science_b':              ['biology', 'chemistry', 'physics', 'additional_mathematics'],
    'business_a':             ['accounting', 'business_management', 'computing_in_business'],
    'business_b':             ['accounting', 'business_management', 'computing_in_business'],
    'business_c':             ['accounting', 'business_management', 'computing_in_business'],
    'business_d':             ['accounting', 'business_management', 'computing_in_business'],
    'home_economics_a':       ['food_nutrition', 'clothing_textile', 'management_in_living'],
    'home_economics_b':       ['food_nutrition', 'clothing_textile', 'management_in_living'],
    'home_economics_c':       ['food_nutrition', 'clothing_textile', 'management_in_living'],
    'home_economics_d':       ['food_nutrition', 'clothing_textile', 'management_in_living'],
    'home_economics_e':       ['food_nutrition', 'clothing_textile', 'management_in_living'],
    'home_economics_f':       ['food_nutrition', 'clothing_textile', 'management_in_living'],
    'general_arts_1':         ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_2':         ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_3a':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_3b':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_4a':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_4b':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_5a':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_5b':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_6a':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'general_arts_6b':        ['history', 'geography', 'economics', 'government', 'lit_in_english'],
    'visual_performing_arts': ['music', 'arts_design_studio', 'arts_design_foundation'],
}

if __name__ == '__main__':
    with app.app_context():
        sas = {}
        for area_key, electives in STUDY_AREA_ELECTIVES.items():
            sas[area_key] = {
                'core': CORE_SUBJECTS,
                'electives': electives,
            }
        SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
        app.config['STUDY_AREA_SUBJECTS'] = sas

        print("✓ STUDY_AREA_SUBJECTS written correctly to database.")
        print(f"  {len(sas)} study areas configured.")
        for k, v in sas.items():
            print(f"  {k}: {len(v['core'])} core, {len(v['electives'])} electives")
