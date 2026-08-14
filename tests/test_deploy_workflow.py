"""Regression checks for the release workflow bootstrap."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "deploy.yml"
RELEASE_SCRIPT_PATH = ROOT / "deploy" / "release.sh"


def test_ssh_action_uses_a_short_bootstrap() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    deploy_steps = workflow["jobs"]["deploy"]["steps"]
    ssh_step = next(step for step in deploy_steps if "appleboy/ssh-action" in step["uses"])
    bootstrap = ssh_step["with"]["script"]

    # GitHub rejects action-input expressions at 21,000 characters. Keep a
    # much tighter budget so growth is caught well before that hard limit.
    assert len(bootstrap) < 5_000
    assert "bash deploy/release.sh" in bootstrap
    assert "${{ secrets." not in bootstrap


def test_release_script_is_shell_parseable_and_expression_free() -> None:
    release_script = RELEASE_SCRIPT_PATH.read_text()

    assert "${{" not in release_script
    subprocess.run(
        ["bash", "-n", str(RELEASE_SCRIPT_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )
