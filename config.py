import os

class Config:
    """Base configuration"""
    # SECRET_KEY is handled in app.py to avoid conflicts

    # -------------------------------------------------------
    # DATABASE CONFIGURATION
    # Priority: DATABASE_URL env var (Neon) → SQLite (local)
    # -------------------------------------------------------
    DATABASE_URL = os.environ.get('DATABASE_URL', '')

    # Fix 1: Render/Heroku uses 'postgres://' but SQLAlchemy needs 'postgresql://'
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    # Fix 2: Neon requires SSL — add sslmode=require if not already present
    if DATABASE_URL and 'postgresql' in DATABASE_URL and 'sslmode' not in DATABASE_URL:
        DATABASE_URL += '?sslmode=require'

    SQLALCHEMY_DATABASE_URI = DATABASE_URL or 'sqlite:///assessment.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Fix 3: Connection pool settings to handle Neon's free tier idle timeouts
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,       # Test connection before using it
        'pool_recycle': 300,         # Recycle connections every 5 minutes
        'pool_timeout': 30,          # Wait max 30 seconds for a connection
        'connect_args': {
            'connect_timeout': 10    # Timeout connecting to Neon
        } if DATABASE_URL and 'postgresql' in DATABASE_URL else {}
    }

    # User roles
    USER_ROLES = [
        ('admin', 'Administrator'),
        ('teacher', 'Teacher')
    ]

    # Default credentials (override via environment variables in Render)
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

    # Assessment categories
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

    # Study/Learning Areas
    STUDY_AREAS = [
        ('visual_performing_arts', 'Visual and Performing Arts'),
        ('home_economics_a', 'Home Economics A'),
        ('home_economics_b', 'Home Economics B'),
        ('home_economics_c', 'Home Economics C'),
        ('home_economics_d', 'Home Economics D'),
        ('home_economics_e', 'Home Economics E'),
        ('home_economics_f', 'Home Economics F'),
        ('business_a', 'Business A'),
        ('business_b', 'Business B'),
        ('business_c', 'Business C'),
        ('business_d', 'Business D'),
        ('science_a', 'Science A'),
        ('science_b', 'Science B'),
        ('general_arts_1', 'General Arts 1'),
        ('general_arts_2', 'General Arts 2'),
        ('general_arts_3a', 'General Arts 3A'),
        ('general_arts_3b', 'General Arts 3B'),
        ('general_arts_4a', 'General Arts 4A'),
        ('general_arts_4b', 'General Arts 4B'),
        ('general_arts_5a', 'General Arts 5A'),
        ('general_arts_5b', 'General Arts 5B'),
        ('general_arts_6a', 'General Arts 6A'),
        ('general_arts_6b', 'General Arts 6B')
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

    # Assessment weights
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

    # Category display labels
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
    """Development configuration - uses local SQLite"""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///assessment.db'


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///assessment_test.db'
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """Production configuration - uses Neon PostgreSQL via DATABASE_URL"""
    DEBUG = False
    # DATABASE_URL is set as environment variable in Render dashboard

    @classmethod
    def validate_production_settings(cls):
        """Validate required production environment variables at startup."""
        errors = []

        if not os.environ.get('DATABASE_URL'):
            errors.append(
                "DATABASE_URL is not set. Add your Neon PostgreSQL connection string in Render → Environment Variables."
            )

        if not os.environ.get('SECRET_KEY'):
            errors.append(
                "SECRET_KEY is not set. Add a strong secret key in Render → Environment Variables."
            )

        if errors:
            print("\n" + "=" * 60)
            print("PRODUCTION CONFIGURATION ERRORS")
            print("=" * 60)
            for error in errors:
                print(f"  [MISSING] {error}")
            print("=" * 60 + "\n")

            if not os.environ.get('DATABASE_URL'):
                raise RuntimeError(
                    "DATABASE_URL must be set for production. "
                    "Please add it in your Render dashboard under Environment Variables."
                )
        else:
            print("[OK] Production configuration validated successfully.")


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
