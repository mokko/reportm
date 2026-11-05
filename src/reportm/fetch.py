"""
fetch - the only part of reportm that talks to MuseumPlus.

It writes a bundle: the two module documents and the attachment of every
multimedia record that has one. Nothing is rendered here, and nothing is
deleted — a fetch that fails halfway leaves a bundle that `reportm build` can
already read, and a second run fills in what is missing.

Offline use: --objects-xml/--multimedia-xml assemble a bundle from documents
that came from somewhere else (a colleague's export, an earlier run), which is
also how the test suite works without a database.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from reportm.bundle import Bundle

GROUPED_OBJECTS = "ObjObjectGroupsRef.__id"
GROUPED_MULTIMEDIA = "MulObjectRef.ObjObjectGroupsRef.__id"
NSMAP = {"m": "http://www.zetcom.com/ria/ws/module"}


@dataclass
class FetchResult:
    bundle: Bundle
    objects: int
    multimedia: int
    downloaded: int
    already_there: int
    no_attachment: int


def fetch(
    group_id: int | str,
    out: Path | str,
    *,
    refresh: bool = False,
    title: str | None = None,
    objects_xml: Path | str | None = None,
    multimedia_xml: Path | str | None = None,
    with_images: bool = True,
) -> FetchResult:
    """Get group data from RIA into `out` and return what was found."""
    if (objects_xml is None) != (multimedia_xml is None):
        raise ValueError(
            "Provide either both --objects-xml and --multimedia-xml, or neither."
        )

    bundle = Bundle.open(out) if (Path(out).expanduser() / "bundle.toml").is_file() \
        else Bundle.create(out, group_id=group_id, title=title)
    if str(bundle.meta.get("group_id")) != str(group_id):
        raise ValueError(
            f"{bundle.root} holds group {bundle.meta.get('group_id')}, not {group_id}. "
            "Use another -j name, or remove that job directory to start over."
        )

    if objects_xml is not None:
        _copy_in(Path(objects_xml).expanduser(), bundle.objects_xml)
        _copy_in(Path(multimedia_xml).expanduser(), bundle.multimedia_xml)
        bundle.meta["source"] = "files"
        bundle.meta["title"] = title or bundle.meta.get("title") or f"Objektbericht Gruppe {group_id}"
        bundle.save()
        return FetchResult(
            bundle=bundle,
            objects=_count(bundle.objects_xml, "Object"),
            multimedia=_count(bundle.multimedia_xml, "Multimedia"),
            downloaded=0,
            already_there=0,
            no_attachment=0,
        )

    objects_doc, multimedia_doc, base_url = _from_ria(group_id, refresh=refresh)
    objects_doc.toFile(path=bundle.objects_xml)
    multimedia_doc.toFile(path=bundle.multimedia_xml)
    bundle.meta["base_url"] = base_url
    bundle.meta["title"] = title or bundle.meta.get("title") or f"Objektbericht Gruppe {group_id}"
    bundle.save()

    downloaded = already = no_att = 0
    if with_images:
        downloaded, already, no_att = _download_attachments(
            bundle, multimedia_doc, force=refresh
        )

    return FetchResult(
        bundle=bundle,
        objects=len(objects_doc),
        multimedia=len(multimedia_doc),
        downloaded=downloaded,
        already_there=already,
        no_attachment=no_att,
    )


def _copy_in(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(f"XML file not found: {src}")
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)


def _count(path: Path, mtype: str) -> int:
    from lxml import etree

    if not path.is_file():
        return 0
    doc = etree.parse(str(path))
    return len(
        doc.xpath(
            f"/m:application/m:modules/m:module[@name='{mtype}']/m:moduleItem",
            namespaces=NSMAP,
        )
    )


def _from_ria(group_id, *, refresh: bool):
    """Search Object and Multimedia for the group. Imports MpApi lazily so that
    building a report never needs the client or its credentials."""
    from mpapi.constants import get_credentials
    from mpapi.sar import Sar

    import requests

    user, pw, base_url = get_credentials()
    sar = Sar(baseURL=base_url, user=user, pw=pw)
    try:
        print(f"* searching Object in group {group_id}", flush=True)
        objects = sar.getByGroup(Id=group_id, module="Object")
        print(f"* searching Multimedia in group {group_id}", flush=True)
        multimedia = sar.getByGroup(Id=group_id, module="Multimedia")
    except requests.RequestException as exc:
        raise ConnectionError(
            f"cannot reach RIA at {base_url} ({exc.__class__.__name__}). "
            "Check the baseURL in ~/.ria, the network, and whether the "
            "MuseumPlus web service is up — then run the same command again: "
            "a failed fetch leaves the job directory as it was."
        ) from exc
    return objects, multimedia, base_url


def _download_attachments(bundle: Bundle, multimedia_doc, *, force: bool = False):
    """Save one file per multimedia record into bundle.images/.

    The file is named after the multimedia id, not after the original name:
    two records can carry the same file name, and the id is what links back to
    the object record.
    """
    from mpapi.client import MpApi
    from mpapi.constants import get_credentials

    user, pw, base_url = get_credentials()
    api = MpApi(baseURL=base_url, user=user, pw=pw)

    items = multimedia_doc.xpath(
        "/m:application/m:modules/m:module[@name='Multimedia']/m:moduleItem",
        namespaces=NSMAP,
    )
    downloaded = already = no_att = 0
    for itemN in items:
        mul_id = itemN.get("id")
        if itemN.get("hasAttachments") != "true":
            no_att += 1
            continue

        names = itemN.xpath(
            "m:dataField[@name='MulOriginalFileTxt']/m:value/text()", namespaces=NSMAP
        )
        suffix = Path(names[0]).suffix if names else ""
        if not suffix:
            suffix = ".jpg"  # RIA is not obliged to tell us; .jpg is the usual case
        dst = bundle.images_dir / f"{mul_id}{suffix}"

        if dst.is_file() and not force:
            already += 1
            print(f"  {dst.name} already there")
            continue

        print(f"  getting {dst.name}", flush=True)
        api.saveAttachment(module="Multimedia", id=int(mul_id), path=dst)
        downloaded += 1

    if no_att:
        print(f"* {no_att} multimedia record(s) without attachment")
    return downloaded, already, no_att
