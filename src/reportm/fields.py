"""
fields - which metadata ends up on the report page.

Every field is a German label plus one or more XPath expressions, evaluated
relative to an Object moduleItem. Several paths are the point: instances differ
in which field carries a value, so the first path that produces something wins.
That keeps a report usable on a record that has no title but a Sachbegriff.

The list is a default, not a promise — the field names of an instance come from
its data definition, which `reportm fields` can print. Override the list with
--fields FILE:

    [report]
    title = "Objektbericht"

    [[fields]]
    label = "Inventarnummer"
    paths = ["m:dataField[@name='ObjObjectNumberTxt']/m:value"]
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

NSMAP = {"m": "http://www.zetcom.com/ria/ws/module"}


@dataclass
class Field:
    label: str
    paths: list[str] = dc_field(default_factory=list)
    kind: str = "xpath"  # "xpath" | "mul_count"
    join: str = "; "


DEFAULT_FIELDS: list[Field] = [
    Field(
        label="Inventarnummer",
        paths=[
            "m:dataField[@name='ObjObjectNumberTxt']/m:value",
            "m:repeatableGroup[@name='ObjObjectNumberGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='InventarNrSTxt']/m:value",
        ],
    ),
    Field(
        label="Titel",
        paths=[
            "m:repeatableGroup[@name='ObjObjectTitleGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='TitleTxt']/m:value",
        ],
    ),
    Field(
        label="Sachbegriff",
        paths=["m:dataField[@name='ObjTechnicalTermClb']/m:value"],
    ),
    Field(
        label="Objektart",
        paths=[
            "m:vocabularyReference[@name='ObjCategoryVoc']"
            "/m:vocabularyReferenceItem/@name"
        ],
    ),
    Field(
        label="Organisationseinheit",
        paths=[
            "m:vocabularyReference[@name='ObjOrgGroupVoc']"
            "/m:vocabularyReferenceItem/@name"
        ],
    ),
    Field(
        label="Datierung",
        paths=[
            "m:repeatableGroup[@name='ObjDateGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='DateTxt']/m:value",
            "m:repeatableGroup[@name='ObjDateGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='DateFromTxt']/m:value",
        ],
    ),
    Field(
        label="Geografie",
        paths=[
            "m:repeatableGroup[@name='ObjGeograficGrp']/m:repeatableGroupItem"
            "/m:vocabularyReference[@name='PlaceVoc']/m:vocabularyReferenceItem/@name",
            "m:repeatableGroup[@name='ObjGeograficGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='DetailsTxt']/m:value",
        ],
    ),
    Field(
        label="Material/Technik",
        paths=[
            "m:repeatableGroup[@name='ObjMaterialTechniqueGrp']/m:repeatableGroupItem"
            "/m:vocabularyReference[@name='MaterialVoc']/m:vocabularyReferenceItem/@name",
            "m:repeatableGroup[@name='ObjMaterialTechniqueGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='MaterialTechniqueTxt']/m:value",
        ],
    ),
    Field(
        label="Beschreibung (online)",
        paths=[
            "m:repeatableGroup[@name='ObjTextOnlineGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='TextClb']/m:value",
        ],
    ),
    Field(
        label="Erwerbsnotiz",
        paths=[
            "m:repeatableGroup[@name='ObjAcquisitionNotesGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='TextClb']/m:value",
        ],
    ),
    Field(label="Anzahl Medien", kind="mul_count"),
]


@dataclass
class ReportConfig:
    title: str | None = None
    subtitle: str | None = None
    fields: list[Field] = dc_field(default_factory=lambda: list(DEFAULT_FIELDS))


def load_config(path: Path | str | None) -> ReportConfig:
    """Read a --fields TOML, falling back to the built-in list."""
    if path is None:
        return ReportConfig()
    import tomllib

    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Field config not found: {p}")
    with open(p, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    cfg = ReportConfig()
    report = data.get("report", {})
    cfg.title = report.get("title")
    cfg.subtitle = report.get("subtitle")

    if "fields" in data:
        fields: list[Field] = []
        for i, entry in enumerate(data["fields"]):
            label = entry.get("label")
            if not label:
                raise ValueError(f"Field #{i + 1} in {p} has no label")
            kind = entry.get("kind", "xpath")
            paths = list(entry.get("paths", []))
            if kind == "xpath" and not paths:
                raise ValueError(f"Field '{label}' in {p} has no paths")
            fields.append(
                Field(label=label, paths=paths, kind=kind, join=entry.get("join", "; "))
            )
        if not fields:
            raise ValueError(f"{p} defines an empty [[fields]] list")
        cfg.fields = fields
    return cfg


def resolve(itemN, field: Field, *, mul_count: int = 0, max_chars: int = 1500) -> str:
    """Value of one field for one Object moduleItem, or "" if it has none."""
    if field.kind == "mul_count":
        return str(mul_count)

    for path in field.paths:
        try:
            found = itemN.xpath(path, namespaces=NSMAP)
        except Exception:
            continue
        values: list[str] = []
        for node in found:
            if isinstance(node, str):
                text = node  # an @attribute result is already a string
            elif hasattr(node, "itertext"):
                text = "".join(node.itertext())
            else:
                text = str(node)
            text = " ".join(text.split())
            if text:
                values.append(text)
        if values:
            joined = field.join.join(values)
            if max_chars and len(joined) > max_chars:
                joined = joined[:max_chars].rstrip() + " …"
            return joined
    return ""


def value_fields(cfg: ReportConfig) -> list[Field]:
    return [f for f in cfg.fields if f.kind != "mul_count"]
