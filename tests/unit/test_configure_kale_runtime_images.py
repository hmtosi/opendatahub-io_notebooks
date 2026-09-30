"""Tests for configuring Kale runtime images from Jupyter metadata."""

from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "jupyter/datascience/ubi9-python-3.12/utils/configure_kale_runtime_images.py"
_SPEC = importlib.util.spec_from_file_location("configure_kale_runtime_images", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
kale_runtime_images = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kale_runtime_images)


def write_runtime_image(path: Path, image_name: object, tags: list[str] | None = None) -> None:
    """Write one Jupyter runtime image metadata file."""
    path.write_text(
        json.dumps({"schema_name": "runtime-image", "metadata": {"image_name": image_name, "tags": tags or []}}),
        encoding="utf-8",
    )


def write_kale_schema(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "properties": {
                    "runtimeImages": {
                        "default": [
                            "python:3.12",
                            "pytorch/pytorch:2.0",
                            "tensorflow/tensorflow:latest",
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_load_runtime_images_deduplicates_and_skips_invalid_metadata(tmp_path: Path) -> None:
    write_runtime_image(tmp_path / "01-pytorch.json", "quay.io/example/pytorch:latest")
    write_runtime_image(tmp_path / "02-datascience.json", " quay.io/example/datascience:latest ", ["datascience"])
    write_runtime_image(tmp_path / "03-duplicate.json", "quay.io/example/datascience:latest")
    write_runtime_image(tmp_path / "04-empty.json", "")
    (tmp_path / "05-malformed.json").write_text("{not-json", encoding="utf-8")

    assert kale_runtime_images.load_runtime_images(tmp_path) == (
        ["quay.io/example/datascience:latest", "quay.io/example/pytorch:latest"],
        "quay.io/example/datascience:latest",
    )


def test_configure_kale_runtime_images_merges_existing_settings(tmp_path: Path) -> None:
    runtime_images_dir = tmp_path / "runtime-images"
    runtime_images_dir.mkdir()
    write_runtime_image(runtime_images_dir / "datascience.json", "quay.io/example/datascience:latest", ["datascience"])
    write_runtime_image(runtime_images_dir / "pytorch.json", "quay.io/example/pytorch:latest")

    settings_path = tmp_path / "settings" / "kale-settings.jupyterlab-settings"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "outputPath": "_kale",
                "enableKaleByDefault": True,
                "runtimeImages": ["quay.io/example/custom:latest", "quay.io/example/datascience:latest"],
            }
        ),
        encoding="utf-8",
    )
    settings_path.chmod(0o664)

    assert kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    expected_settings = {
        "outputPath": "_kale",
        "enableKaleByDefault": True,
        "defaultBaseImage": "quay.io/example/datascience:latest",
        "runtimeImages": [
            "quay.io/example/custom:latest",
            "quay.io/example/datascience:latest",
            "quay.io/example/pytorch:latest",
        ],
    }
    assert json.loads(settings_path.read_text(encoding="utf-8")) == expected_settings
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o664

    assert kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == expected_settings


def test_configure_kale_runtime_images_preserves_custom_default(tmp_path: Path) -> None:
    runtime_images_dir = tmp_path / "runtime-images"
    runtime_images_dir.mkdir()
    write_runtime_image(runtime_images_dir / "datascience.json", "quay.io/example/datascience:new", ["datascience"])
    write_runtime_image(
        runtime_images_dir / "datascience-old.json", "quay.io/example/datascience:old", ["datascience-2025.2"]
    )

    settings_path = tmp_path / "kale-settings.jupyterlab-settings"
    settings_path.write_text(
        json.dumps({"defaultBaseImage": "quay.io/example/custom:latest", "runtimeImages": []}), encoding="utf-8"
    )
    assert kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    assert json.loads(settings_path.read_text(encoding="utf-8"))["defaultBaseImage"] == "quay.io/example/custom:latest"

    settings_path.write_text(json.dumps({"defaultBaseImage": "ubi9/python-312", "runtimeImages": []}), encoding="utf-8")
    assert kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    assert (
        json.loads(settings_path.read_text(encoding="utf-8"))["defaultBaseImage"] == "quay.io/example/datascience:new"
    )


def test_configure_kale_runtime_images_accepts_jupyterlab_json5_settings(tmp_path: Path) -> None:
    runtime_images_dir = tmp_path / "runtime-images"
    runtime_images_dir.mkdir()
    write_runtime_image(runtime_images_dir / "datascience.json", "quay.io/example/datascience:latest")
    schema_path = tmp_path / "kale-settings.json"
    write_kale_schema(schema_path)

    settings_path = tmp_path / "settings" / "kale-settings.jupyterlab-settings"
    settings_path.parent.mkdir()
    settings_path.write_text(
        """{
    // JupyterLab settings files support JSON5.
    outputPath: '_kale',
    enableKaleByDefault: true,
}
""",
        encoding="utf-8",
    )

    assert kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path, schema_path)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "outputPath": "_kale",
        "enableKaleByDefault": True,
        "runtimeImages": [
            "python:3.12",
            "pytorch/pytorch:2.0",
            "tensorflow/tensorflow:latest",
            "quay.io/example/datascience:latest",
        ],
    }


def test_configure_kale_runtime_images_keeps_settings_when_no_images_are_valid(tmp_path: Path) -> None:
    runtime_images_dir = tmp_path / "runtime-images"
    runtime_images_dir.mkdir()
    write_runtime_image(runtime_images_dir / "invalid.json", None)

    settings_path = tmp_path / "kale-settings.jupyterlab-settings"
    original_settings = '{"outputPath": "_kale"}\n'
    settings_path.write_text(original_settings, encoding="utf-8")

    assert not kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    assert settings_path.read_text(encoding="utf-8") == original_settings


def test_configure_kale_runtime_images_keeps_invalid_user_entries(tmp_path: Path) -> None:
    runtime_images_dir = tmp_path / "runtime-images"
    runtime_images_dir.mkdir()
    write_runtime_image(runtime_images_dir / "datascience.json", "quay.io/example/datascience:latest")

    settings_path = tmp_path / "kale-settings.jupyterlab-settings"
    original_settings = '{"runtimeImages": ["quay.io/example/custom:latest", 42]}\n'
    settings_path.write_text(original_settings, encoding="utf-8")

    assert not kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    assert settings_path.read_text(encoding="utf-8") == original_settings


def test_configure_kale_runtime_images_rejects_malformed_settings(tmp_path: Path) -> None:
    runtime_images_dir = tmp_path / "runtime-images"
    runtime_images_dir.mkdir()
    write_runtime_image(runtime_images_dir / "datascience.json", "quay.io/example/datascience:latest")

    settings_path = tmp_path / "kale-settings.jupyterlab-settings"
    original_settings = "{not-json\n"
    settings_path.write_text(original_settings, encoding="utf-8")

    assert not kale_runtime_images.configure_kale_runtime_images(runtime_images_dir, settings_path)
    assert settings_path.read_text(encoding="utf-8") == original_settings
