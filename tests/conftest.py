"""
conftest.py - shared pytest configuration for the tests/ tree.

Registration of custom markers keeps the qemu contract tests from emitting
PytestUnknownMarkWarning; the markers themselves are still enforced via the
skipif guards in each marked test.
"""

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "qemu: real-QEMU contract tests (qemu-system-xtensa required)",
    )
    config.addinivalue_line(
        "markers",
        'req("ID"): requirement traceability marker read by '
        "tools/check_traceability.py",
    )
