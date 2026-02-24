#!/usr/bin/env python3
"""
Test script to verify accessibility permissions and basic functionality.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging import setup_logging

logger = setup_logging('test')

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    try:
        from database.models import init_db, get_session
        from tracker.window_monitor import WindowMonitor
        from tracker.activity_processor import ActivityProcessor
        from ai.categorizer import SessionCategorizer
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_accessibility():
    """Test accessibility permissions."""
    print("\nTesting accessibility permissions...")
    try:
        import atomacos
        test = atomacos.NativeUIElement()
        app = test.AXFocusedApplication
        print(f"✓ Accessibility OK - Current app: {app.AXTitle if app else 'Unknown'}")
        return True
    except ImportError:
        print("✗ atomacos not installed")
        print("  Run: pip install atomacos")
        return False
    except Exception as e:
        print("✗ Accessibility permissions not granted")
        print("  Enable in: System Settings > Privacy & Security > Accessibility")
        return False

def test_database():
    """Test database initialization."""
    print("\nTesting database...")
    try:
        from database.models import init_db, get_session, Category

        # Initialize database
        init_db()
        print("✓ Database initialized")

        # Check categories
        db = get_session()
        categories = db.query(Category).all()
        print(f"✓ Found {len(categories)} default categories:")
        for cat in categories:
            print(f"  - {cat.name} ({cat.color_hex})")
        db.close()

        return True
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        return False

def test_api_key():
    """Test if API key is configured."""
    print("\nTesting API configuration...")
    from config.settings import ANTHROPIC_API_KEY

    if ANTHROPIC_API_KEY:
        print(f"✓ API key configured (starts with: {ANTHROPIC_API_KEY[:10]}...)")
        return True
    else:
        print("✗ API key not configured")
        print("  Edit .env and add: ANTHROPIC_API_KEY=your_key_here")
        return False

def main():
    """Run all tests."""
    print("="*50)
    print("Activity Tracker - Environment Test")
    print("="*50)

    results = []

    results.append(("Imports", test_imports()))
    results.append(("Accessibility", test_accessibility()))
    results.append(("Database", test_database()))
    results.append(("API Key", test_api_key()))

    print("\n" + "="*50)
    print("Test Results")
    print("="*50)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {test_name}")

    all_passed = all(result[1] for result in results)

    print("\n" + "="*50)
    if all_passed:
        print("All tests passed! Ready to start tracking.")
        print("\nNext steps:")
        print("1. Start tracking: python3 services/background_runner.py")
        print("2. Start dashboard: python3 dashboard/app.py")
        print("3. Open: http://127.0.0.1:5000")
    else:
        print("Some tests failed. Please fix the issues above.")
    print("="*50)

    sys.exit(0 if all_passed else 1)

if __name__ == '__main__':
    main()
