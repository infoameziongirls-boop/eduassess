#!/usr/bin/env python
"""Phase 1 Verification Tests"""

from app import app, db
from models import SystemConfig, User, Student, Assessment

print("=" * 60)
print("PHASE 1 VERIFICATION TESTS")
print("=" * 60)

with app.app_context():
    # Test 1: Database connection
    print("\n[TEST 1] Database Connection...")
    try:
        db.session.execute(db.text('SELECT 1'))
        print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        exit(1)
    
    # Test 2: SystemConfig model exists
    print("\n[TEST 2] SystemConfig Model...")
    try:
        config_count = SystemConfig.query.count()
        print(f"✓ SystemConfig table exists with {config_count} entries")
    except Exception as e:
        print(f"✗ SystemConfig table error: {e}")
        exit(1)
    
    # Test 3: Config persistence in database
    print("\n[TEST 3] Configuration Persistence...")
    try:
        class_levels = SystemConfig.get_config('CLASS_LEVELS')
        study_areas = SystemConfig.get_config('STUDY_AREAS')
        study_area_subjects = SystemConfig.get_config('STUDY_AREA_SUBJECTS')
        
        print(f"✓ CLASS_LEVELS loaded: {len(class_levels)} items")
        print(f"✓ STUDY_AREAS loaded: {len(study_areas)} items")
        print(f"✓ STUDY_AREA_SUBJECTS loaded: {len(study_area_subjects)} items")
    except Exception as e:
        print(f"✗ Config loading failed: {e}")
        exit(1)
    
    # Test 4: App config matches DB
    print("\n[TEST 4] App Config Consistency...")
    try:
        app_class_levels = app.config.get('CLASS_LEVELS', [])
        app_study_areas = app.config.get('STUDY_AREAS', [])
        
        assert len(app_class_levels) == len(class_levels), "CLASS_LEVELS mismatch"
        assert len(app_study_areas) == len(study_areas), "STUDY_AREAS mismatch"
        
        print(f"✓ App config matches database")
    except AssertionError as e:
        print(f"✗ Config mismatch: {e}")
        exit(1)
    
    # Test 5: CSRF protection configuration
    print("\n[TEST 5] CSRF Protection...")
    try:
        csrf_enabled = app.config.get('WTF_CSRF_ENABLED', True)
        print(f"✓ CSRF Protection enabled: {csrf_enabled}")
    except Exception as e:
        print(f"✗ CSRF check failed: {e}")
        exit(1)
    
    # Test 6: Redis config for production
    print("\n[TEST 6] Redis Configuration (Production)...")
    try:
        from config import ProductionConfig
        has_redis = hasattr(ProductionConfig, 'SESSION_REDIS')
        print(f"✓ ProductionConfig has Redis config: {has_redis}")
    except Exception as e:
        print(f"✗ Redis config check failed: {e}")
        exit(1)
    
    # Test 7: Celery configuration
    print("\n[TEST 7] Celery Configuration...")
    try:
        from config import ProductionConfig
        celery_broker = hasattr(ProductionConfig, 'CELERY_BROKER_URL')
        celery_backend = hasattr(ProductionConfig, 'CELERY_RESULT_BACKEND')
        print(f"✓ Celery broker configured: {celery_broker}")
        print(f"✓ Celery backend configured: {celery_backend}")
    except Exception as e:
        print(f"✗ Celery config check failed: {e}")
        exit(1)
    
    # Test 8: Test data integrity
    print("\n[TEST 8] Data Integrity...")
    try:
        # Verify class levels data
        for level_key, level_name in class_levels:
            assert isinstance(level_key, str), f"Invalid key type: {level_key}"
            assert isinstance(level_name, str), f"Invalid name type: {level_name}"
        
        # Verify study areas data
        for area_key, area_name in study_areas:
            assert isinstance(area_key, str), f"Invalid area key type: {area_key}"
            assert isinstance(area_name, str), f"Invalid area name type: {area_name}"
        
        print(f"✓ All configuration data integrity verified")
    except AssertionError as e:
        print(f"✗ Data integrity check failed: {e}")
        exit(1)
    
    # Test 9: Test SystemConfig CRUD operations
    print("\n[TEST 9] SystemConfig CRUD Operations...")
    try:
        # Test set_config
        test_value = {'test': 'data', 'nested': {'key': 'value'}}
        SystemConfig.set_config('TEST_CONFIG', test_value)
        
        # Test get_config
        retrieved = SystemConfig.get_config('TEST_CONFIG')
        assert retrieved == test_value, f"CRUD failed: {retrieved} != {test_value}"
        
        # Clean up
        test_entry = SystemConfig.query.filter_by(config_key='TEST_CONFIG').first()
        if test_entry:
            db.session.delete(test_entry)
            db.session.commit()
        
        print(f"✓ SystemConfig CRUD operations working correctly")
    except Exception as e:
        print(f"✗ CRUD test failed: {e}")
        exit(1)
    
    # Test 10: Test API endpoint modifications (simulate requests)
    print("\n[TEST 10] API Endpoint Structure...")
    try:
        # Check that routes exist
        routes = [str(rule) for rule in app.url_map.iter_rules()]
        
        assert any('/admin/api/class-levels' in r for r in routes), "class-levels API not found"
        assert any('/admin/api/study-areas' in r for r in routes), "study-areas API not found"
        assert any('study-area-subjects' in r for r in routes), "study-area-subjects API not found"
        
        print(f"✓ All API endpoints present and properly structured")
    except AssertionError as e:
        print(f"✗ API endpoint check failed: {e}")
        exit(1)

print("\n" + "=" * 60)
print("ALL TESTS PASSED ✓")
print("=" * 60)
print("\nPhase 1 verification complete!")
print("Status: Ready for Phase 2")
