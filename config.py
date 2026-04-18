import os

# Optional redis import – do NOT crash if the package is absent
try:
    import redis as redis_lib
    _redis_available = True
except ImportError:
    redis_lib = None
    _redis_available = False


class Config:
    """Base configuration – shared by all environments."""

    # ------------------------------------------------------------------ #
    # Security
    # ------------------------------------------------------------------ #
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-CHANGE-IN-PRODUCTION")

    # CSRF
    WTF_CSRF_TIME_LIMIT = None          # Token valid for entire session
    WTF_CSRF_SSL_STRICT = False         # Needed behind reverse proxies
    SESSION_COOKIE_SECURE = False       # Overridden to True in Production
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    _DATABASE_URL = os.environ.get("DATABASE_URL", "")
    if _DATABASE_URL.startswith("postgres://"):
        # SQLAlchemy 1.4+ requires postgresql:// scheme
        _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = _DATABASE_URL or "sqlite:///assessment.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Keep connections alive; important for multi-worker deployments
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
    }

    # ------------------------------------------------------------------ #
    # File / Upload paths  (overridden per-environment if needed)
    # ------------------------------------------------------------------ #
    TEMPLATE_FOLDER = "templates_excel"
    ASSESSMENT_TEMPLATE_FILE = "student_template.xlsx"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024   # 16 MB upload cap

    # ------------------------------------------------------------------ #
    # Pagination
    # ------------------------------------------------------------------ #
    ASSESSMENTS_PER_PAGE = 20

    # ------------------------------------------------------------------ #
    # Auth / Roles
    # ------------------------------------------------------------------ #
    USER_ROLES = [
        ("admin",   "Administrator"),
        ("teacher", "Teacher"),
        ("parent",  "Parent"),
    ]

    DEFAULT_ADMIN_USERNAME  = os.environ.get("DEFAULT_ADMIN_USERNAME",  "admin")
    DEFAULT_ADMIN_PASSWORD  = os.environ.get("DEFAULT_ADMIN_PASSWORD",  "Admin@123")
    DEFAULT_STUDENT_PASSWORD = os.environ.get("DEFAULT_STUDENT_PASSWORD", "Student@123")

    # ------------------------------------------------------------------ #
    # Assessment categories  (WTForms SelectField choices)
    # ------------------------------------------------------------------ #
    ASSESSMENT_CATEGORIES = [
        ("ica1",      "Individual Class Assessment 1 (max 50)"),
        ("ica2",      "Individual Class Assessment 2 (max 50)"),
        ("icp1",      "Individual Class Project 1 (max 50)"),
        ("icp2",      "Individual Class Project 2 (max 50)"),
        ("gp1",       "Group Project/Research 1 (max 50)"),
        ("gp2",       "Group Project/Research 2 (max 50)"),
        ("practical", "Practical Portfolio (max 100)"),
        ("mid_term",  "Mid-Term Exam (max 100)"),
        ("end_term",  "End of Term Exam (max 100)"),
    ]

    # Assessment weights
    ASSESSMENT_WEIGHTS = {
        "ica1":      0.05,
        "ica2":      0.05,
        "icp1":      0.05,
        "icp2":      0.05,
        "gp1":       0.05,
        "gp2":       0.05,
        "practical": 0.10,
        "mid_term":  0.10,
        "end_term":  0.50,
    }

    # Max raw scores per category
    CATEGORY_MAX_SCORES = {
        "ica1": 50, "ica2": 50,
        "icp1": 50, "icp2": 50,
        "gp1":  50, "gp2":  50,
        "practical": 100,
        "mid_term":  100,
        "end_term":  100,
    }

    # Human-readable labels
    CATEGORY_LABELS = {
        "ica1":      "Individual Class Assessment 1",
        "ica2":      "Individual Class Assessment 2",
        "icp1":      "Individual Class Project 1",
        "icp2":      "Individual Class Project 2",
        "gp1":       "Group Project/Research 1",
        "gp2":       "Group Project/Research 2",
        "practical": "Practical Portfolio",
        "mid_term":  "Mid-Term Exam",
        "end_term":  "End of Term Exam",
    }

    # ------------------------------------------------------------------ #
    # Terms
    # ------------------------------------------------------------------ #
    TERMS = [
        ("term1", "Term 1"),
        ("term2", "Term 2"),
        ("term3", "Term 3"),
    ]

    # ------------------------------------------------------------------ #
    # CLASS_LEVELS
    # Keys MUST match what canonical_class_key() normalises to.
    # Using the canonical 'Form X' strings avoids the lookup miss.
    # ------------------------------------------------------------------ #
    CLASS_LEVELS = [
        ("Form 1", "Form 1"),
        ("Form 2", "Form 2"),
        ("Form 3", "Form 3"),
    ]

    # ------------------------------------------------------------------ #
    # Study / Learning Areas
    # ------------------------------------------------------------------ #
    STUDY_AREAS = [
        ("visual_performing_arts", "Visual and Performing Arts"),
        ("home_economics_a",       "Home Economics A"),
        ("home_economics_b",       "Home Economics B"),
        ("home_economics_c",       "Home Economics C"),
        ("home_economics_d",       "Home Economics D"),
        ("home_economics_e",       "Home Economics E"),
        ("home_economics_f",       "Home Economics F"),
        ("business_a",             "Business A"),
        ("business_b",             "Business B"),
        ("business_c",             "Business C"),
        ("business_d",             "Business D"),
        ("science_a",              "Science A"),
        ("science_b",              "Science B"),
        ("general_arts_1",         "General Arts 1"),
        ("general_arts_2",         "General Arts 2"),
        ("general_arts_3a",        "General Arts 3A"),
        ("general_arts_3b",        "General Arts 3B"),
        ("general_arts_4a",        "General Arts 4A"),
        ("general_arts_4b",        "General Arts 4B"),
        ("general_arts_5a",        "General Arts 5A"),
        ("general_arts_5b",        "General Arts 5B"),
        ("general_arts_6a",        "General Arts 6A"),
        ("general_arts_6b",        "General Arts 6B"),
    ]

    # Subjects per study area – populated by admin UI and persisted in DB
    STUDY_AREA_SUBJECTS: dict = {}

    # ------------------------------------------------------------------ #
    # Learning Areas / Subjects
    # ------------------------------------------------------------------ #
    LEARNING_AREAS = [
        ("mathematics",                   "Mathematics"),
        ("social_studies",                "Social Studies"),
        ("general_science",               "General Science"),
        ("english_language",              "English Language"),
        ("ict",                           "ICT"),
        ("physical_education_health",     "Physical Education and Health"),
        ("music",                         "Music"),
        ("additional_mathematics",        "Additional Mathematics"),
        ("biology",                       "Biology"),
        ("chemistry",                     "Chemistry"),
        ("physics",                       "Physics"),
        ("geography",                     "Geography"),
        ("economics",                     "Economics"),
        ("french",                        "French"),
        ("arts_design_studio",            "Arts and Design Studio"),
        ("arts_design_foundation",        "Arts and Design Foundation"),
        ("design_communication_technology", "Design and Communication Technology"),
        ("clothing_textile",              "Clothing and Textile"),
        ("management_in_living",          "Management in Living"),
        ("food_nutrition",                "Food and Nutrition"),
        ("lit_in_english",                "Lit in English"),
        ("christian_religious_studies",   "Christian Religious Studies"),
        ("history",                       "History"),
        ("ghanaian_language",             "Ghanaian Language"),
        ("religious_moral_education",     "Religious and Moral Education"),
        ("government",                    "Government"),
        ("business_management",           "Business Management"),
        ("accounting",                    "Accounting"),
        ("computing_in_business",         "Computing in Business"),
    ]

    # Template category mapping (legacy  kept for backward compat)
    TEMPLATE_CATEGORY_MAPPING = {
        "individual_assignment": "ica",
        "quiz":                  "ica",
        "homework":              "ica",
        "project":               "icp",
        "research_paper":        "icp",
        "group_assignment":      "gp",
        "presentation":          "gp",
        "lab_report":            "practical",
        "midterm_exam":          "mid_term",
        "final_exam":            "end_term",
    }


# --------------------------------------------------------------------------- #
#  Environment-specific configs
# --------------------------------------------------------------------------- #

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///assessment.db"
    # Override engine options for SQLite (no pool needed)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "connect_args": {"check_same_thread": False},
    }

    SESSION_TYPE = "filesystem"
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///assessment_test.db"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "connect_args": {"check_same_thread": False},
    }
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SESSION_TYPE = "filesystem"


class ProductionConfig(Config):
    DEBUG = False

    # Get database URL and convert postgres:// to postgresql:// if needed
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)

    # Only set if DATABASE_URL is available; otherwise will be caught at app init
    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///assessment.db"

    SESSION_COOKIE_SECURE = True

    # Redis-backed sessions when redis package + REDIS_URL are available
    _redis_url = os.environ.get("REDIS_URL", "")
    if _redis_available and _redis_url:
        SESSION_TYPE  = "redis"
        SESSION_REDIS = redis_lib.from_url(_redis_url)
    else:
        SESSION_TYPE  = "filesystem"
        SESSION_REDIS = None

    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True

    @classmethod
    def validate_production_settings(cls):
        """Validate production settings when config is actually used."""
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL environment variable is required in production. "
                "Set it to a valid PostgreSQL connection string."
            )


config = {
    "development": DevelopmentConfig,
    "testing":     TestingConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}
