"""
conftest.py - shared pytest configuration for the tests/ tree.

Registration of custom markers keeps the qemu contract tests from emitting
PytestUnknownMarkWarning; the markers themselves are still enforced via the
skipif guards in each marked test.
"""

import os

import pytest


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
    config.addinivalue_line(
        "markers",
        "ngspice_run: tests that execute a real transient via libngspice; "
        "these can C-level abort on incompatible system ngspice builds",
    )


def pytest_collection_modifyitems(config, items):
    """Skip real-ngspice transient tests when the CI capability gate is off.

    test_components_library.py runs multi-subcircuit transients through the
    system libngspice. On the ubuntu-latest runner the installed ngspice
    aborts the interpreter inside ngSpice_Command("run") for the DC motor
    B-source model (Fatal Python error: Aborted) -- an uncatchable C-level
    crash. The workflow validates the ngspice bridge separately via its
    dedicated sanity steps, so the full-suite job disables these here.
    """
    if os.environ.get("WOSP_SKIP_NGSPICE_RUN", "").lower() in ("1", "true", "yes"):
        skip = pytest.mark.skip(reason="real ngspice transient skipped on this runner")
        for item in items:
            if "test_components_library.py" in str(item.fspath):
                item.add_marker(skip)
