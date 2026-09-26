"""Scheduled, CI-gated fast-forward of personal main to Epitech main."""

import logging
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

SOURCE = "https://github.com/OmarCodes022/Sensai.git"
DESTINATION = "git@github.com:EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1.git"
MARKER = "/sensai/mirror/last-tested-sha"
HOST_KEY = (
    "github.com ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def git(directory, *args, env=None):
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"git {args[0]} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def mirror(tested_sha, private_key):
    if len(tested_sha) != 40 or any(c not in "0123456789abcdef" for c in tested_sha):
        raise ValueError("Invalid tested commit SHA")
    if not private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
        raise ValueError("Expected an OpenSSH private key in Secrets Manager")

    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        key = directory / "id_ed25519"
        key.write_text(private_key, encoding="utf-8")
        key.chmod(0o600)
        known_hosts = directory / "known_hosts"
        known_hosts.write_text(HOST_KEY, encoding="ascii")
        repository = directory / "repository"
        git(directory, "init", "--quiet", str(repository))
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_SSH_COMMAND": (
                f"ssh -i {shlex.quote(str(key))} -o IdentitiesOnly=yes "
                "-o BatchMode=yes -o StrictHostKeyChecking=yes "
                f"-o UserKnownHostsFile={shlex.quote(str(known_hosts))}"
            ),
        }
        git(repository, "fetch", "--quiet", "--no-tags", SOURCE,
            "refs/heads/main:refs/remotes/personal/main", env=env)
        source = git(repository, "rev-parse", "refs/remotes/personal/main", env=env)
        if source != tested_sha:
            LOG.info("Waiting for CI on current personal main %s", source)
            return {"status": "waiting_for_ci", "source": source}

        git(repository, "fetch", "--quiet", "--no-tags", DESTINATION,
            "refs/heads/main:refs/remotes/epitech/main", env=env)
        target = git(repository, "rev-parse", "refs/remotes/epitech/main", env=env)
        if target == source:
            LOG.info("Epitech main is up to date at %s", source)
            return {"status": "up_to_date", "source": source}
        git(repository, "merge-base", "--is-ancestor", target, source, env=env)
        git(repository, "push", "--porcelain", DESTINATION,
            "refs/remotes/personal/main:refs/heads/main", env=env)
        LOG.info("Mirrored personal main %s to Epitech (was %s)", source, target)
        return {"status": "mirrored", "source": source, "previous": target}


def handler(_event, _context):
    import boto3

    marker = boto3.client("ssm").get_parameter(Name=MARKER)["Parameter"]["Value"]
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["SSH_SECRET_ARN"]
    )["SecretString"]
    return mirror(marker, secret)
