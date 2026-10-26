from app.scanner import scan_files


def test_detects_multiple_sensitive_categories():
    source = '''
API_KEY = "sk_demo_12345678901234567890"
DB_PASSWORD = "real-password-123"
user_email = "student@example.com"
phone = "13800138000"
token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"
'''
    result = scan_files([("demo.py", source)], "test-1", "测试")
    categories = {item.category for item in result.findings}
    assert "API Key" in categories
    assert "数据库账号密码" in categories
    assert "邮箱" in categories
    assert "手机号" in categories
    assert "JWT Token" in categories


def test_placeholder_gets_lower_score():
    source = 'API_KEY = "your_key_here"\n'
    result = scan_files([("demo.py", source)], "test-2", "测试")
    assert result.findings
    assert result.findings[0].score < 70


def test_ignores_vendor_directories():
    source = 'API_KEY = "sk_demo_12345678901234567890"\n'
    result = scan_files([("node_modules/pkg/demo.js", source), ("src/main.js", source)], "test-3", "测试")
    assert result.file_count == 1
    assert all("node_modules" not in item.file_name for item in result.findings)


def test_summary_score_decreases_with_risk():
    clean = scan_files([("clean.py", "print('hello')\n")], "test-4", "测试")
    risky = scan_files([("risk.py", 'SECRET_KEY = "abcdef1234567890abcdef123456"\n')], "test-5", "测试")
    assert clean.summary()["score"] == 100
    assert risky.summary()["score"] < 100

