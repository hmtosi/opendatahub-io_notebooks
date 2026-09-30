#!/usr/bin/env python3
"""Configure Kale runtime images from Jupyter runtime image metadata."""

from __future__ import annotations

import importlib
import json
import os
import stat
import tempfile
from pathlib import Path

try:
    _json5 = importlib.import_module("json5")
except ModuleNotFoundError:
    # The repository development environment provides the compatible pyjson5
    # implementation, while workbench images provide json5 via JupyterLab.
    _json5 = importlib.import_module("pyjson5")

_JSON5_DECODE_ERROR = getattr(_json5, "Json5Exception", ValueError)
KALE_SETTINGS_SCHEMA_PATH = Path(
    "/opt/app-root/share/jupyter/labextensions/jupyterlab-kubeflow-kale/"
    "schemas/jupyterlab-kubeflow-kale/kale-settings.json"
)


def load_runtime_images(runtime_images_dir: str | os.PathLike[str]) -> tuple[list[str], str | None]:
    """Return unique image names and the current datascience runtime image."""
    images: set[str] = set()
    datascience_images: set[str] = set()

    for config_path in sorted(Path(runtime_images_dir).glob("*.json")):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            image_name = config.get("metadata", {}).get("image_name")
        except (OSError, json.JSONDecodeError, AttributeError) as error:
            print(f"Warning: Could not read runtime image {config_path}: {error}")
            continue

        if not isinstance(image_name, str) or not image_name.strip():
            print(f"Warning: Runtime image {config_path} has no valid metadata.image_name")
            continue

        image_name = image_name.strip()
        images.add(image_name)
        tags = config["metadata"].get("tags", [])
        if isinstance(tags, list) and "datascience" in tags:
            datascience_images.add(image_name)

    if len(datascience_images) > 1:
        print("Warning: Multiple datascience runtime images found; keeping the existing Kale default")
    datascience_image = next(iter(datascience_images)) if len(datascience_images) == 1 else None
    return sorted(images), datascience_image


def load_default_runtime_images(schema_path: str | os.PathLike[str]) -> list[str]:
    """Read Kale's built-in image choices from its installed settings schema."""
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    images = schema["properties"]["runtimeImages"]["default"]
    if not isinstance(images, list) or not all(isinstance(image, str) for image in images):
        raise ValueError("Kale schema runtimeImages default must be a list of strings")
    return images


def configure_kale_runtime_images(
    runtime_images_dir: str | os.PathLike[str],
    settings_path: str | os.PathLike[str],
    schema_path: str | os.PathLike[str] = KALE_SETTINGS_SCHEMA_PATH,
) -> bool:
    """Merge Jupyter runtime image names into Kale's JupyterLab settings."""
    images, datascience_image = load_runtime_images(runtime_images_dir)
    if not images:
        print("No valid runtime images found; keeping the existing Kale settings")
        return False

    settings_file = Path(settings_path)
    try:
        if settings_file.exists():
            settings = _json5.loads(settings_file.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError("Kale settings must contain a JSON object")
        else:
            settings = {}

        existing_images = (
            settings["runtimeImages"] if "runtimeImages" in settings else load_default_runtime_images(schema_path)
        )
        if not isinstance(existing_images, list) or not all(isinstance(image, str) for image in existing_images):
            raise ValueError("Kale runtimeImages must be a list of strings")

        settings["runtimeImages"] = list(dict.fromkeys([*existing_images, *images]))
        default_base_image = settings.get("defaultBaseImage")
        if datascience_image and (
            "defaultBaseImage" not in settings
            or (isinstance(default_base_image, str) and default_base_image.strip() in ("", "ubi9/python-312"))
        ):
            settings["defaultBaseImage"] = datascience_image
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_mode = stat.S_IMODE(settings_file.stat().st_mode) if settings_file.exists() else 0o644

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=settings_file.parent,
            prefix=f".{settings_file.name}.",
            delete=False,
        ) as temporary_file:
            json.dump(settings, temporary_file, indent=2)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)

        temporary_path.chmod(settings_mode)
        temporary_path.replace(settings_file)
    except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError, _JSON5_DECODE_ERROR) as error:
        print(f"Warning: Could not configure Kale runtime images: {error}")
        return False

    print(f"Configured {len(images)} Kale runtime images from Jupyter metadata")
    return True


if __name__ == "__main__":
    runtime_images_dir = os.environ.get(
        "KALE_RUNTIME_IMAGES_DIR", "/opt/app-root/share/jupyter/metadata/runtime-images"
    )
    settings_path = os.environ.get(
        "KALE_SETTINGS_PATH",
        str(Path.home() / ".jupyter/lab/user-settings/jupyterlab-kubeflow-kale/kale-settings.jupyterlab-settings"),
    )
    configure_kale_runtime_images(runtime_images_dir, settings_path)
