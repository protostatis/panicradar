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


def test_release_refreshes_and_verifies_the_trending_scout_pin() -> None:
    release_script = RELEASE_SCRIPT_PATH.read_text()

    assert "TRENDING_SCOUT_IMAGE" in release_script
    assert "TRENDING_SCOUT_IMAGE_ID=$(docker image inspect" in release_script
    assert 'docker run -d --name "$TRENDING_SCOUT_PIN_NEXT_NAME"' in release_script
    assert "--memory 8m --cpus 0.01" in release_script
    assert "--label panicradar.role=trending-scout-image-pin" not in release_script
    assert 'docker inspect --format \'{{.Image}}\' "$TRENDING_SCOUT_PIN_NAME"' in release_script
    assert 'docker tag "$TRENDING_SCOUT_IMAGE_ID" "$TRENDING_SCOUT_IMAGE"' in release_script
    assert "Trending scout pin container is missing" in release_script

    refresh_call = release_script.index("\nrefresh_trending_scout_pin\n")
    system_prune = release_script.index("docker system prune -af")
    post_deploy_prune = release_script.index("docker image prune -af")
    restore_after_system_prune = release_script.index(
        "\nrestore_trending_scout_tag\n", system_prune
    )
    verify_after_system_prune = release_script.index(
        "\nverify_trending_scout_pin\n", system_prune
    )
    restore_after_post_deploy_prune = release_script.index(
        "\nrestore_trending_scout_tag\n", post_deploy_prune
    )
    verify_after_post_deploy_prune = release_script.index(
        "\nverify_trending_scout_pin\n", post_deploy_prune
    )

    assert refresh_call < system_prune
    assert system_prune < restore_after_system_prune < verify_after_system_prune
    assert verify_after_system_prune < post_deploy_prune
    assert post_deploy_prune < restore_after_post_deploy_prune < verify_after_post_deploy_prune
