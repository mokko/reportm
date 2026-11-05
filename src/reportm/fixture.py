"""
fixture - a synthetic bundle, for working on the report without a database.

This box has no route to RIA, so the report has to be developable against
something. The fixture is generated, not copied from real material: it is
public-repo-safe and it deliberately contains the awkward cases —

    101  full metadata, two photos (one landscape, one portrait)
    102  no title, one TIFF that has to be converted
    103  one multimedia record whose file is not an image at all

so `reportm build` exercises conversion, missing title fallback, and the
"unreadable file" path on one run.
"""

from __future__ import annotations

from pathlib import Path

from reportm.bundle import Bundle

OBJECTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<application xmlns="http://www.zetcom.com/ria/ws/module">
  <modules>
    <module name="Object" totalSize="3">
      <moduleItem id="101" hasAttachments="true">
        <dataField dataType="Varchar" name="ObjObjectNumberTxt"><value>I C 7723</value></dataField>
        <dataField dataType="Clob" name="ObjTechnicalTermClb"><value>Speerschleuder</value></dataField>
        <repeatableGroup name="ObjObjectTitleGrp" size="1">
          <repeatableGroupItem id="1101">
            <dataField dataType="Varchar" name="TitleTxt"><value>Speerschleuder mit Ornament</value></dataField>
          </repeatableGroupItem>
        </repeatableGroup>
        <vocabularyReference name="ObjCategoryVoc" id="1" instanceName="ObjCategoryVgr">
          <vocabularyReferenceItem id="4711" name="Waffe">
            <formattedValue language="de">Waffe</formattedValue>
          </vocabularyReferenceItem>
        </vocabularyReference>
        <vocabularyReference name="ObjOrgGroupVoc" id="2" instanceName="ObjOrgGroupVgr">
          <vocabularyReferenceItem id="12" name="Südsee">
            <formattedValue language="de">Südsee</formattedValue>
          </vocabularyReferenceItem>
        </vocabularyReference>
        <repeatableGroup name="ObjDateGrp" size="1">
          <repeatableGroupItem id="1102">
            <dataField dataType="Varchar" name="DateTxt"><value>um 1900</value></dataField>
          </repeatableGroupItem>
        </repeatableGroup>
        <repeatableGroup name="ObjGeograficGrp" size="1">
          <repeatableGroupItem id="1103">
            <vocabularyReference name="PlaceVoc" id="3" instanceName="ObjGeographyVgr">
              <vocabularyReferenceItem id="88" name="Neuguinea">
                <formattedValue language="de">Neuguinea</formattedValue>
              </vocabularyReferenceItem>
            </vocabularyReference>
          </repeatableGroupItem>
        </repeatableGroup>
        <repeatableGroup name="ObjMaterialTechniqueGrp" size="1">
          <repeatableGroupItem id="1104">
            <vocabularyReference name="MaterialVoc" id="4" instanceName="ObjMaterialVgr">
              <vocabularyReferenceItem id="99" name="Holz"/>
            </vocabularyReference>
          </repeatableGroupItem>
        </repeatableGroup>
        <repeatableGroup name="ObjTextOnlineGrp" size="1">
          <repeatableGroupItem id="1105">
            <dataField dataType="Clob" name="TextClb"><value>Schleuder aus Hartholz mit eingeschnitztem Ornament am Ende. Gesammelt während der Expedition 1901/02.</value></dataField>
          </repeatableGroupItem>
        </repeatableGroup>
        <moduleReference name="ObjMultimediaRef" targetModule="Multimedia" multiplicity="1:N">
          <moduleReferenceItem moduleItemId="9001" id="1"/>
          <moduleReferenceItem moduleItemId="9002" id="2"/>
        </moduleReference>
      </moduleItem>
      <moduleItem id="102" hasAttachments="true">
        <dataField dataType="Varchar" name="ObjObjectNumberTxt"><value>I C 9001</value></dataField>
        <dataField dataType="Clob" name="ObjTechnicalTermClb"><value>Trommel</value></dataField>
        <repeatableGroup name="ObjObjectTitleGrp" size="1">
          <repeatableGroupItem id="1201">
            <dataField dataType="Varchar" name="TitleTxt"><value></value></dataField>
          </repeatableGroupItem>
        </repeatableGroup>
        <repeatableGroup name="ObjDateGrp" size="1">
          <repeatableGroupItem id="1202">
            <dataField dataType="Varchar" name="DateFromTxt"><value>vor 1890</value></dataField>
          </repeatableGroupItem>
        </repeatableGroup>
        <moduleReference name="ObjMultimediaRef" targetModule="Multimedia" multiplicity="1:N">
          <moduleReferenceItem moduleItemId="9003" id="1"/>
        </moduleReference>
      </moduleItem>
      <moduleItem id="103">
        <dataField dataType="Varchar" name="ObjObjectNumberTxt"><value>I C 9002</value></dataField>
        <moduleReference name="ObjMultimediaRef" targetModule="Multimedia" multiplicity="1:N">
          <moduleReferenceItem moduleItemId="9004" id="1"/>
        </moduleReference>
      </moduleItem>
    </module>
  </modules>
</application>
"""

MULTIMEDIA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<application xmlns="http://www.zetcom.com/ria/ws/module">
  <modules>
    <module name="Multimedia" totalSize="4">
      <moduleItem id="9001" hasAttachments="true">
        <dataField dataType="Varchar" name="MulOriginalFileTxt"><value>scan_0001.jpg</value></dataField>
      </moduleItem>
      <moduleItem id="9002" hasAttachments="true">
        <dataField dataType="Varchar" name="MulOriginalFileTxt"><value>scan_0002.jpg</value></dataField>
      </moduleItem>
      <moduleItem id="9003" hasAttachments="true">
        <dataField dataType="Varchar" name="MulOriginalFileTxt"><value>scan_0003.tif</value></dataField>
      </moduleItem>
      <moduleItem id="9004" hasAttachments="true">
        <dataField dataType="Varchar" name="MulOriginalFileTxt"><value>scan_0004.jpg</value></dataField>
      </moduleItem>
      <moduleItem id="9005" hasAttachments="false">
        <dataField dataType="Varchar" name="MulOriginalFileTxt"><value>katalogzettel.tif</value></dataField>
      </moduleItem>
    </module>
  </modules>
</application>
"""

GROUP_ID = 416397


def make_fixture(
    root: Path | str, *, group_id: int | str | None = None, title: str | None = None
) -> Bundle:
    """Write a complete job directory (XML + images) and return its bundle."""
    bundle = Bundle.create(
        root,
        group_id=group_id or GROUP_ID,
        title=title or "Objektbericht (Testdaten)",
    )
    bundle.meta["source"] = "fixture"
    bundle.objects_xml.write_text(OBJECTS_XML, encoding="utf-8")
    bundle.multimedia_xml.write_text(MULTIMEDIA_XML, encoding="utf-8")
    _images(bundle.images_dir)
    bundle.save()
    return bundle


def _images(images_dir: Path) -> None:
    from PIL import Image, ImageDraw

    images_dir.mkdir(parents=True, exist_ok=True)

    _block(images_dir / "9001.jpg", (2400, 1600), (176, 106, 62), "9001")
    _block(images_dir / "9002.jpg", (1200, 2000), (54, 92, 120), "9002")
    im = _block(images_dir / "9003.tif", (1500, 1100), (94, 122, 74), "9003")
    im.close()

    # not an image: the report has to skip it and say so, not crash
    (images_dir / "9004.jpg").write_text(
        "kein Bild, sondern ein Platzhalter fuer einen defekten Anhang\n",
        encoding="utf-8",
    )


def _block(path: Path, size: tuple[int, int], colour: tuple[int, int, int], label: str):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", size, colour)
    draw = ImageDraw.Draw(im)
    w, h = size
    draw.rectangle([w * 0.1, h * 0.1, w * 0.9, h * 0.9], outline=(255, 255, 255), width=8)
    draw.text((w * 0.15, h * 0.15), f"Testbild {label}", fill=(255, 255, 255))
    im.save(path)
    return im
