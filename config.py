import os

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database URI - uses PostgreSQL in production via DATABASE_URL environment variable
    # Falls back to SQLite for local development
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL:
        # Fix Render's postgres:// -> postgresql:// compatibility issue for SQLAlchemy 1.4+
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or 'sqlite:///assessment.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # User roles
    USER_ROLES = [
        ('admin', 'Administrator'),
        ('teacher', 'Teacher')
    ]
    
    # Default passwords
    DEFAULT_ADMIN_USERNAME = os.environ.get('DEFAULT_ADMIN_USERNAME', 'admin')
    DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'Admin@123')
    DEFAULT_STUDENT_PASSWORD = os.environ.get('DEFAULT_STUDENT_PASSWORD', 'Student@123')
    
    # Template configuration
    TEMPLATE_FOLDER = 'templates_excel'
    ASSESSMENT_TEMPLATE_FILE = 'student_template.xlsx'
    
    # Template mapping - map your assessment categories to template columns
    TEMPLATE_CATEGORY_MAPPING = {
        'individual_assignment': 'ica',
        'quiz': 'ica',
        'homework': 'ica',
        'project': 'icp',
        'research_paper': 'icp',
        'group_assignment': 'gp',
        'presentation': 'gp',
        'lab_report': 'practical',
        'midterm_exam': 'mid_term',
        'final_exam': 'end_term'
    }
    
    # Assessment categories - updated to match Excel template columns
    ASSESSMENT_CATEGORIES = [
        ('ica1', 'Individual Assessment 1'),
        ('ica2', 'Individual Assessment 2'),
        ('icp1', 'Individual Class Project 1'),
        ('icp2', 'Individual Class Project 2'),
        ('gp1', 'Group Project/Research 1'),
        ('gp2', 'Group Project/Research 2'),
        ('practical', 'Practical Portfolio'),
        ('mid_term', 'Mid-Semester Exam'),
        ('end_term', 'End of Term Exam')
    ]
    
    # Category max scores
    CATEGORY_MAX_SCORES = {
        'ica1': 50.0,
        'ica2': 50.0,
        'icp1': 50.0,
        'icp2': 50.0,
        'gp1': 50.0,
        'gp2': 50.0,
        'practical': 100.0,
        'mid_term': 100.0,
        'end_term': 100.0
    }
    
    # Terms
    TERMS = [
        ('term1', 'Term 1'),
        ('term2', 'Term 2'),
        ('term3', 'Term 3')
    ]
    
    # Study/Learning Areas - Updated to match new structure
    STUDY_AREAS = [
        ('visual_performing_arts', 'VISUAL AND PERFORMING ARTS'),
        ('home_economics_a', 'HOME ECONOMICS A'),
        ('home_economics_b', 'HOME ECONOMICS B'),
        ('home_economics_c', 'HOME ECONOMICS C'),
        ('home_economics_d', 'HOME ECONOMICS D'),
        ('home_economics_e', 'HOME ECONOMICS E'),
        ('home_economics_f', 'HOME ECONOMICS F'),
        ('business_a', 'BUSINESS A'),
        ('business_b', 'BUSINESS B'),
        ('business_c', 'BUSINESS C'),
        ('business_d', 'BUSINESS D'),
        ('science_a', 'SCIENCE A'),
        ('science_b', 'SCIENCE B'),
        ('general_arts_1', 'GENERAL ARTS 1'),
        ('general_arts_2', 'GENERAL ARTS 2'),
        ('general_arts_3a', 'GENERAL ARTS 3A'),
        ('general_arts_3b', 'GENERAL ARTS 3B'),
        ('general_arts_4a', 'GENERAL ARTS 4A'),
        ('general_arts_4b', 'GENERAL ARTS 4B'),
        ('general_arts_5a', 'GENERAL ARTS 5A'),
        ('general_arts_5b', 'GENERAL ARTS 5B'),
        ('general_arts_6a', 'GENERAL ARTS 6A'),
        ('general_arts_6b', 'GENERAL ARTS 6B')
    ]
    
    # Complete Learning Areas/Subjects
    LEARNING_AREAS = [
        ('mathematics', 'Mathematics'),
        ('social_studies', 'Social Studies'),
        ('general_science', 'General Science'),
        ('english_language', 'English Language'),
        ('ict', 'ICT'),
        ('physical_education_health', 'Physical Education and Health'),
        ('music', 'Music'),
        ('additional_mathematics', 'Additional Mathematics'),
        ('biology', 'Biology'),
        ('chemistry', 'Chemistry'),
        ('physics', 'Physics'),
        ('geography', 'Geography'),
        ('economics', 'Economics'),
        ('french', 'French'),
        ('arts_design_studio', 'Arts and Design Studio'),
        ('arts_design_foundation', 'Arts and Design Foundation'),
        ('design_communication_technology', 'Design and Communication Technology'),
        ('clothing_textile', 'Clothing and Textile'),
        ('management_in_living', 'Management in Living'),
        ('food_nutrition', 'Food and Nutrition'),
        ('lit_in_english', 'Lit in English'),
        ('christian_religious_studies', 'Christian Religious Studies'),
        ('history', 'History'),
        ('ghanaian_language', 'Ghanaian Language'),
        ('religious_moral_education', 'Religious and Moral Education'),
        ('government', 'Government'),
        ('business_management', 'Business Management'),
        ('accounting', 'Accounting'),
        ('computing_in_business', 'Computing in Business')
    ]
    
    # Class levels
    CLASS_LEVELS = [
        ('form1', 'Form 1'),
        ('form2', 'Form 2'),
        ('form3', 'Form 3')
    ]
    
    # Assessment weights for final grade calculation - updated for new categories
    ASSESSMENT_WEIGHTS = {
        'ica1': 0.1,
        'ica2': 0.1,
        'icp1': 0.1,
        'icp2': 0.1,
        'gp1': 0.1,
        'gp2': 0.1,
        'practical': 0.15,
        'mid_term': 0.15,
        'end_term': 0.15
    }
    
    # Pagination settings
    ASSESSMENTS_PER_PAGE = 20
    
    # Category display labels - updated to match new categories
    CATEGORY_LABELS = {
        'ica1': 'Individual Assessment 1',
        'ica2': 'Individual Assessment 2',
        'icp1': 'Individual Class Project 1',
        'icp2': 'Individual Class Project 2',
        'gp1': 'Group Project/Research 1',
        'gp2': 'Group Project/Research 2',
        'practical': 'Practical Portfolio',
        'mid_term': 'Mid-Semester Exam',
        'end_term': 'End of Term Exam'
    }
    
    # Study Area Subject Mappings
    STUDY_AREA_SUBJECTS = {
        'visual_performing_arts': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['clothing_textile', 'arts_design_foundation', 'arts_design_studio', 'design_communication_technology', 'music']
        },
        'home_economics_a': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['management_in_living', 'food_nutrition', 'biology', 'economics', 'music']
        },
        'home_economics_b': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['management_in_living', 'clothing_textile', 'biology', 'economics', 'music']
        },
        'home_economics_c': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['management_in_living', 'food_nutrition', 'biology', 'arts_design_studio', 'music']
        },
        'home_economics_d': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['management_in_living', 'clothing_textile', 'biology', 'arts_design_studio', 'music']
        },
        'home_economics_e': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['management_in_living', 'food_nutrition', 'biology', 'french', 'music']
        },
        'home_economics_f': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['management_in_living', 'clothing_textile', 'biology', 'french', 'music']
        },
        'business_a': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['business_management', 'accounting', 'economics', 'additional_mathematics', 'geography']
        },
        'business_b': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['business_management', 'accounting', 'economics', 'computing_in_business', 'geography']
        },
        'business_c': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['business_management', 'accounting', 'economics', 'additional_mathematics', 'french']
        },
        'business_d': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['business_management', 'accounting', 'economics', 'computing_in_business', 'french']
        },
        'science_a': {
            'core': ['mathematics', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['biology', 'chemistry', 'physics', 'additional_mathematics', 'geography', 'economics']
        },
        'science_b': {
            'core': ['mathematics', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['biology', 'chemistry', 'physics', 'additional_mathematics', 'geography', 'french']
        },
        'general_arts_1': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['lit_in_english', 'christian_religious_studies', 'history', 'ghanaian_language', 'french']
        },
        'general_arts_2': {
            'core': ['mathematics', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['geography', 'economics', 'government', 'religious_moral_education', 'additional_mathematics']
        },
        'general_arts_3a': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['history', 'music', 'lit_in_english', 'religious_moral_education', 'ghanaian_language']
        },
        'general_arts_3b': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['history', 'music', 'lit_in_english', 'religious_moral_education', 'french']
        },
        'general_arts_4a': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['music', 'economics', 'geography', 'religious_moral_education', 'ghanaian_language']
        },
        'general_arts_4b': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['music', 'economics', 'geography', 'religious_moral_education', 'french']
        },
        'general_arts_5a': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['music', 'history', 'government', 'ghanaian_language', 'religious_moral_education']
        },
        'general_arts_5b': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['music', 'history', 'government', 'french', 'religious_moral_education']
        },
        'general_arts_6a': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['government', 'economics', 'biology', 'chemistry', 'christian_religious_studies']
        },
        'general_arts_6b': {
            'core': ['mathematics', 'general_science', 'social_studies', 'english_language', 'physical_education_health', 'ict'],
            'electives': ['government', 'economics', 'biology', 'management_in_living', 'christian_religious_studies']
        }
    }


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///assessment.db'


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///assessment_test.db'
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}