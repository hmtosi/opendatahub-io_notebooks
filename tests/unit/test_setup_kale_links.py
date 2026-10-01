"""Dashboard link exports from the RHOAI Kale startup scripts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [
    REPO_ROOT / "jupyter" / image / "ubi9-python-3.12" / "setup-kale.sh" for image in ("baseline", "datascience")
]
ORIGIN = "https://dashboard.example.com"
PUBLIC_ENDPOINT = f"{ORIGIN}/external/elyra/test-project"
NOTEBOOK_ARGS = '--ServerApp.tornado_settings={"hub_host":"https://unrelated.example.com"}'
RUN_LINK = f"{ORIGIN}/develop-train/pipelines/runs/{{namespace}}/runs/{{run_id}}"
UPLOAD_LINK = f"{ORIGIN}/develop-train/pipelines/definitions/{{namespace}}/{{pipeline_id}}/{{version_id}}/view"


def source_setup_script(
    script: Path,
    tmp_path: Path,
    endpoint: str | None,
    *,
    fallback: bool = False,
    overrides: dict[str, str] | None = None,
    notebook_args: str | None = NOTEBOOK_ARGS,
) -> dict[str, str]:
    """Source the actual script against a synthetic operator-style runtime mount."""
    runtimes = tmp_path / "runtimes"
    data = runtimes / "..data"
    data.mkdir(parents=True)
    if endpoint is not None:
        filename = "odh_dsp.json" if fallback else "Pipeline.json"
        (data / filename).write_text(json.dumps({"metadata": {"public_api_endpoint": endpoint}}), encoding="utf-8")
        (runtimes / filename).symlink_to(data / filename)

    # The Python helper configures KFP separately; this test checks shell exports.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_stub = bin_dir / "python3"
    python_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_stub.chmod(0o755)

    source = script.read_text(encoding="utf-8").replace("/opt/app-root/runtimes/", f"{runtimes}/")
    test_script = tmp_path / "setup-kale.sh"
    test_script.write_text(source, encoding="utf-8")
    env = os.environ.copy()
    env.update({"HOME": str(tmp_path), "PATH": f"{bin_dir}:{env['PATH']}"})
    env.pop("KALE_RUN_LINK", None)
    env.pop("KALE_UPLOAD_LINK", None)
    env.pop("NOTEBOOK_ARGS", None)
    if notebook_args is not None:
        env["NOTEBOOK_ARGS"] = notebook_args
    env.update(overrides or {})
    result = subprocess.run(
        ["bash", "-c", 'source "$1" >/dev/null 2>&1; env -0', "bash", str(test_script)],
        env=env,
        capture_output=True,
        check=True,
    )
    return dict(item.decode().split("=", 1) for item in result.stdout.split(b"\0") if item)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.parts[-3])
@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (PUBLIC_ENDPOINT, True),
        (f"{PUBLIC_ENDPOINT}/", True),
        ("https://pipeline.example.com/", False),
        (f"{ORIGIN}/api/service/pipelines/test-project/runs", False),
        ("https://dashboard.example.com:bad/external/elyra/test-project", False),
        ("https://dashboard.example.com:65536/external/elyra/test-project", False),
        ("https://user@dashboard.example.com/external/elyra/test-project", False),
        ("https://dashboard..example.com/external/elyra/test-project", False),
        (None, False),
        ("not-a-url", False),
    ],
)
def test_dashboard_links(script: Path, tmp_path: Path, endpoint: str | None, expected: bool) -> None:
    environment = source_setup_script(script, tmp_path, endpoint)
    assert environment.get("KALE_RUN_LINK") == (RUN_LINK if expected else None)
    assert environment.get("KALE_UPLOAD_LINK") == (UPLOAD_LINK if expected else None)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.parts[-3])
def test_dashboard_links_with_port(script: Path, tmp_path: Path) -> None:
    origin = "https://dashboard.example.com:8443"
    environment = source_setup_script(script, tmp_path, f"{origin}/external/elyra/test-project")
    assert environment["KALE_RUN_LINK"] == f"{origin}/develop-train/pipelines/runs/{{namespace}}/runs/{{run_id}}"
    assert environment["KALE_UPLOAD_LINK"] == (
        f"{origin}/develop-train/pipelines/definitions/{{namespace}}/{{pipeline_id}}/{{version_id}}/view"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.parts[-3])
@pytest.mark.parametrize(
    ("overrides", "expected_run", "expected_upload"),
    [
        (
            {"KALE_RUN_LINK": "https://custom.example.com/run", "KALE_UPLOAD_LINK": ""},
            "https://custom.example.com/run",
            UPLOAD_LINK,
        ),
        (
            {"KALE_RUN_LINK": "", "KALE_UPLOAD_LINK": "https://custom.example.com/upload"},
            RUN_LINK,
            "https://custom.example.com/upload",
        ),
    ],
)
def test_fallback_runtime_and_user_overrides(
    script: Path,
    tmp_path: Path,
    overrides: dict[str, str],
    expected_run: str,
    expected_upload: str,
) -> None:
    environment = source_setup_script(
        script,
        tmp_path,
        PUBLIC_ENDPOINT,
        fallback=True,
        overrides=overrides,
    )
    assert environment["KALE_RUN_LINK"] == expected_run
    assert environment["KALE_UPLOAD_LINK"] == expected_upload


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.parts[-3])
@pytest.mark.parametrize("trailing_slash", [False, True])
def test_dashboard_route_from_elyra_runtime_without_hub_host(
    script: Path, tmp_path: Path, trailing_slash: bool
) -> None:
    environment = source_setup_script(
        script,
        tmp_path,
        f"{ORIGIN}/external/elyra/test-project{'/' if trailing_slash else ''}",
        fallback=True,
        notebook_args="--ServerApp.port=8888\n                  --ServerApp.base_url=/notebook/test-project/workbench",
    )
    assert environment["KALE_RUN_LINK"] == RUN_LINK
    assert environment["KALE_UPLOAD_LINK"] == UPLOAD_LINK
