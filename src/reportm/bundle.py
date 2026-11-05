"""
bundle - the working directory reportm keeps for one group.

A bundle is a plain directory, so it survives a failed run, can be copied,
zipped or inspected by hand:

    <bundle>/
        bundle.toml       what this bundle is (group id, source, options)
        objects.xml       Module document, Object module   (as fetched)
        multimedia.xml    Module document, Multimedia module (as fetched)
        images/           one file per multimedia record: <mulId>.<ext>
        scaled/           report-sized copies written at build time

Nothing in here is ever deleted by reportm; `fetch` only adds or overwrites
when --refresh is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

META_NAME = "bundle.toml"


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_toml(data: dict[str, Any]) -> str:
    """Write a flat dict (scalars and lists of scalars) as TOML.

    tomllib reads TOML but does not write it, and a bundle file is a handful of
    scalars, so this stays here instead of pulling in a writer dependency.
    """
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            items = ", ".join(_toml_scalar(v) for v in value)
            lines.append(f"{key} = [{items}]")
        else:
            lines.append(f"{key} = {_toml_scalar(value)}")
    return "\n".join(lines) + "\n"


@dataclass
class Bundle:
    """Handle on a bundle directory. Create one with create() or open()."""

    root: Path
    meta: dict[str, Any] = field(default_factory=dict)

    #
    # construction
    #

    @classmethod
    def create(
        cls,
        root: Path | str,
        *,
        group_id: int | str,
        base_url: str | None = None,
        title: str | None = None,
        source: str = "ria",
    ) -> "Bundle":
        root = Path(root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        (root / "images").mkdir(exist_ok=True)
        b = cls(root=root, meta={})
        b.meta = {
            "group_id": int(group_id) if str(group_id).isdigit() else str(group_id),
            "title": title or f"Objektbericht Gruppe {group_id}",
            "source": source,
            "fetched": _now(),
            "base_url": base_url or "",
        }
        return b

    @classmethod
    def open(cls, root: Path | str) -> "Bundle":
        root = Path(root).expanduser()
        if not root.is_dir():
            raise FileNotFoundError(f"Bundle directory not found: {root}")
        meta_path = root / META_NAME
        if not meta_path.is_file():
            raise FileNotFoundError(
                f"{root} is not a reportm bundle ({META_NAME} is missing). "
                "Run `reportm fetch` first."
            )
        import tomllib

        with open(meta_path, "rb") as f:
            meta = tomllib.load(f)
        return cls(root=root, meta=meta)

    #
    # files
    #

    @property
    def meta_path(self) -> Path:
        return self.root / META_NAME

    @property
    def objects_xml(self) -> Path:
        return self.root / "objects.xml"

    @property
    def multimedia_xml(self) -> Path:
        return self.root / "multimedia.xml"

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @property
    def scaled_dir(self) -> Path:
        return self.root / "scaled"

    def save(self) -> None:
        self.meta_path.write_text(dump_toml(self.meta), encoding="utf-8")

    def __str__(self) -> str:
        return f"Bundle({self.root}, group={self.meta.get('group_id')})"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
