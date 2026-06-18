"""Loading and validation of ``board-config.json``.

The flashing tool's config is a superset of a single ``board-defaults.json``
board entry, so we reuse the canonical firmware schema for the ``values`` and
``flashingRules`` and only add ``type`` (the PlatformIO env to build) and
``tests`` (verification probes). Validation delegates to the shared schema via
a referencing registry, avoiding any duplication of the board ``$defs``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

FLASHER_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = FLASHER_ROOT / "config"
DEFAULTS_SCHEMA_PATH = CONFIG_DIR / "board-defaults.schema.json"
CONFIG_SCHEMA_PATH = CONFIG_DIR / "board-config.schema.json"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "board-config.json"


class ConfigError(ValueError):
    """Raised when ``board-config.json`` is malformed or inconsistent."""


@dataclass(frozen=True)
class ProductionVerifyConfig:
    """Interactive serial checks run after production firmware is flashed."""

    boot_fragments: list[str]
    expected_sensor0_imu: str
    post_boot_delay_seconds: float = 3.0
    boot_timeout_seconds: float = 30.0
    min_wifi_networks: int = 1


BRANDING_KEYS = (
    "VENDOR_NAME",
    "VENDOR_URL",
    "PRODUCT_NAME",
    "UPDATE_ADDRESS",
    "UPDATE_NAME",
)


@dataclass(frozen=True)
class BoardConfig:
    """A validated flashing-tool configuration."""

    path: Path
    board_type: str
    branding: dict[str, str]
    tests: list[str]
    production_verify: ProductionVerifyConfig | None
    values: dict[str, Any]
    flashing_rules: dict[str, Any]
    raw: dict[str, Any]

    @property
    def branding_build_flags(self) -> str:
        return branding_build_flags(self.branding)

    @property
    def firmware_filename(self) -> str:
        return f"{self.branding['UPDATE_NAME']}.bin"


def branding_build_flags(branding: dict[str, str]) -> str:
    """Format branding values as PlatformIO ``-D`` build flags."""
    return " ".join(
        f"-D {key}='\"{branding[key]}\"'" for key in BRANDING_KEYS
    )


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc


def _build_validator() -> Draft202012Validator:
    defaults_schema = _load_json(DEFAULTS_SCHEMA_PATH)
    config_schema = _load_json(CONFIG_SCHEMA_PATH)
    registry = Registry().with_resources(
        [
            ("board-defaults.schema.json", Resource.from_contents(defaults_schema)),
            ("board-config.schema.json", Resource.from_contents(config_schema)),
        ]
    )
    return Draft202012Validator(config_schema, registry=registry)


def validate_config(raw: dict) -> None:
    """Validate a parsed config document against the schema.

    Raises :class:`ConfigError` enumerating every schema violation.
    """
    validator = _build_validator()
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        details = []
        for err in errors:
            where = "/".join(map(str, err.path)) or "(root)"
            details.append(f"  - {where}: {err.message}")
        raise ConfigError(
            "board-config.json failed schema validation:\n" + "\n".join(details)
        )


def load_board_config(
    path: Path | str | None = None, *, flasher_root: Path = FLASHER_ROOT
) -> BoardConfig:
    """Load, validate, and resolve a flashing-tool config file."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = _load_json(config_path)
    validate_config(raw)

    board_type = raw["type"]
    defaults = raw["defaults"]
    if board_type not in defaults:
        available = ", ".join(sorted(defaults)) or "none"
        raise ConfigError(
            f"'type' is {board_type!r} but 'defaults' has no matching entry "
            f"(found: {available})."
        )

    tests = list(raw["tests"])
    missing = [t for t in tests if not (flasher_root / t).is_file()]
    if missing:
        raise ConfigError(
            "Verification probe source(s) not found relative to repo root:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    entry = defaults[board_type]
    production_verify = _parse_production_verify(raw.get("productionVerify"))
    return BoardConfig(
        path=config_path,
        board_type=board_type,
        branding=dict(raw["branding"]),
        tests=tests,
        production_verify=production_verify,
        values=entry["values"],
        flashing_rules=entry["flashingRules"],
        raw=raw,
    )


def _parse_production_verify(raw: object) -> ProductionVerifyConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'productionVerify' must be an object.")
    return ProductionVerifyConfig(
        boot_fragments=list(raw["bootFragments"]),
        expected_sensor0_imu=str(raw["expectedSensor0Imu"]),
        post_boot_delay_seconds=float(raw.get("postBootDelaySeconds", 3)),
        boot_timeout_seconds=float(raw.get("bootTimeoutSeconds", 30)),
        min_wifi_networks=int(raw.get("minWifiNetworks", 1)),
    )
