"""test_ci_workflow.py - the CI workflow must parse and target this branch.

R10/CO-14: the workflow YAML must parse with the pinned PyYAML and its push
trigger must include the release branch `baseline-fix` - "targets the
branch" for this repository - and actually run the suite. PyYAML reads the
bare `on:` key as boolean True (YAML 1.1), which the loader below handles.
"""
import os

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "cosim-ci.yml")
RELEASE_BRANCH = "baseline-fix"


def _load():
    with open(WORKFLOW, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), type(data)
    trigger = data.get("on", data.get(True))
    assert trigger, "workflow has no 'on:' trigger"
    return data, trigger


@pytest.mark.req("CO-14")
def test_workflow_parses_as_yaml():
    data, trigger = _load()
    assert "jobs" in data, sorted(data)
    assert "push" in trigger, sorted(trigger)


@pytest.mark.req("CO-14")
def test_push_trigger_targets_the_release_branch():
    _, trigger = _load()
    branches = (trigger.get("push") or {}).get("branches") or []
    assert RELEASE_BRANCH in branches, branches


def test_push_runs_the_suite():
    data, _ = _load()
    job = data["jobs"]["cosim-test-matrix"]
    runs = " ".join(str(step.get("run", "")) for step in job["steps"])
    assert "run_tests" in runs, runs[:300]
