"""
Tests run against the generated fixture, not real material: no database, no
credentials, no photographs of other people's objects.

The interesting assertions are the ones about what the report *refuses* — a
broken attachment, an empty title, a second group in an existing job.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from reportm.bundle import Bundle, dump_toml
from reportm.fields import Field, ReportConfig, load_config, resolve
from reportm.fixture import make_fixture
from reportm.render import build, read_objects, scale_image

pypdf = pytest.importorskip("pypdf")

NSMAP = {"m": "http://www.zetcom.com/ria/ws/module"}


@pytest.fixture()
def job(tmp_path: Path) -> Bundle:
    return make_fixture(tmp_path / "testdaten")


@pytest.fixture()
def pdf(job, tmp_path: Path) -> Path:
    out = tmp_path / "report.pdf"
    build(job, out)
    return out


def page_count(path: Path) -> int:
    return len(pypdf.PdfReader(str(path)).pages)


def text_of(path: Path) -> str:
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() for page in reader.pages)


#
# the report
#


def test_one_page_per_object_plus_cover(pdf: Path):
    assert page_count(pdf) == 1 + 3


def test_cover_names_the_group_and_counts(pdf: Path):
    text = text_of(pdf)
    assert "Gruppe: 416397" in text
    assert "Objekt 3" in text or "Objekte: 3" in text


def test_metadata_reaches_the_page(pdf: Path):
    text = text_of(pdf)
    for expected in ["I C 7723", "Speerschleuder mit Ornament", "Neuguinea", "um 1900"]:
        assert expected in text, expected


def test_empty_field_is_dropped_not_shown_as_an_element(job, pdf: Path):
    """Object 102 has a TitleTxt element with no text. It must not appear at all:
    neither as a row, nor — the original bug — as an lxml element repr."""
    text = text_of(pdf)
    assert "Element" not in text
    assert "TitleTxt" not in text


def test_a_title_that_exists_is_shown(job):
    pages, _ = read_objects(job, ReportConfig())
    by_id = {p.item_id: p for p in pages}
    labels_101 = [label for label, _ in by_id["101"].rows]
    labels_102 = [label for label, _ in by_id["102"].rows]
    assert "Titel" in labels_101
    assert "Titel" not in labels_102


#
# images
#


def test_tiff_is_converted_for_the_report(job):
    pages, skipped = read_objects(job, ReportConfig(), max_edge=800)
    by_id = {p.item_id: p for p in pages}
    assert len(by_id["102"].images) == 1
    assert by_id["102"].images[0].suffix == ".jpg"
    assert skipped == 1  # the broken one, and only that one


def test_unreadable_file_is_counted_not_fatal(job):
    pages, skipped = read_objects(job, ReportConfig())
    assert skipped == 1
    by_id = {p.item_id: p for p in pages}
    assert by_id["103"].images == []


def test_media_count_matches_the_photos_shown(job):
    """A page must not claim 'Anzahl Medien 1' above 'Kein Bild vorhanden.'"""
    pages, _ = read_objects(job, ReportConfig())
    for page in pages:
        count_row = [v for k, v in page.rows if k == "Anzahl Medien"]
        if count_row:
            assert int(count_row[0]) == len(page.images)


def test_scaling_respects_max_edge_and_is_cached(job, tmp_path: Path):
    src = job.images_dir / "9001.jpg"
    out = scale_image(src, tmp_path / "scaled", 500)
    assert out is not None and out.is_file()
    from PIL import Image

    with Image.open(out) as im:
        assert max(im.size) == 500
    again = scale_image(src, tmp_path / "scaled", 500)
    assert again == out


def test_scaling_a_non_image_returns_none(tmp_path: Path):
    broken = tmp_path / "broken.jpg"
    broken.write_text("not an image at all", encoding="utf-8")
    assert scale_image(broken, tmp_path / "scaled", 500) is None


def test_exif_orientation_is_applied(tmp_path: Path):
    """A portrait photo tagged 'rotate 90' must reach the report landscape,
    otherwise every phone photo is on its side."""
    from PIL import Image

    src = tmp_path / "portrait.jpg"
    im = Image.new("RGB", (400, 800), (10, 20, 30))
    exif = im.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    im.save(src, exif=exif)
    im.close()

    out = scale_image(src, tmp_path / "scaled", 1000)
    assert out is not None
    with Image.open(out) as scaled:
        assert scaled.width > scaled.height


#
# fields and config
#


def test_resolve_skips_empty_elements(tmp_path: Path):
    from lxml import etree

    node = etree.fromstring(
        b"""<moduleItem xmlns="http://www.zetcom.com/ria/ws/module" id="1">
             <dataField name="ObjObjectNumberTxt"><value>I C 1</value></dataField>
             <dataField name="ObjTechnicalTermClb"><value>  </value></dataField>
           </moduleItem>"""
    )
    assert resolve(node, Field("Nr", ["m:dataField[@name='ObjObjectNumberTxt']/m:value"])) == "I C 1"
    assert resolve(node, Field("Leer", ["m:dataField[@name='ObjTechnicalTermClb']/m:value"])) == ""


def test_first_matching_path_wins(tmp_path: Path):
    from lxml import etree

    node = etree.fromstring(
        b"""<moduleItem xmlns="http://www.zetcom.com/ria/ws/module" id="1">
             <dataField name="B"><value>zweite</value></dataField>
           </moduleItem>"""
    )
    f = Field("X", ["m:dataField[@name='A']/m:value", "m:dataField[@name='B']/m:value"])
    assert resolve(node, f) == "zweite"


def test_config_rejects_a_field_without_paths(tmp_path: Path):
    cfg = tmp_path / "fields.toml"
    cfg.write_text('[[fields]]\nlabel = "Titel"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no paths"):
        load_config(cfg)


def test_config_rejects_a_field_without_label(tmp_path: Path):
    cfg = tmp_path / "fields.toml"
    cfg.write_text('[[fields]]\npaths = ["m:dataField[@name=\'A\']/m:value"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no label"):
        load_config(cfg)


def test_custom_config_limits_the_page(job, tmp_path: Path):
    cfg_file = tmp_path / "fields.toml"
    cfg_file.write_text(
        '[report]\ntitle = "Nur die Nummer"\n\n'
        '[[fields]]\nlabel = "Inventarnummer"\n'
        'paths = ["m:dataField[@name=\'ObjObjectNumberTxt\']/m:value"]\n',
        encoding="utf-8",
    )
    out = tmp_path / "slim.pdf"
    result = build(job, out, cfg=load_config(cfg_file))
    assert result.objects == 4 - 1  # three objects
    text = text_of(out)
    assert "Nur die Nummer" in text
    assert "Neuguinea" not in text


#
# bundle bookkeeping
#


def test_bundle_roundtrip(tmp_path: Path):
    b = Bundle.create(tmp_path / "j", group_id=4711, title="T")
    b.save()
    reopened = Bundle.open(tmp_path / "j")
    assert reopened.meta["group_id"] == 4711
    assert reopened.meta["title"] == "T"


def test_open_rejects_a_directory_that_is_not_a_job(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="bundle.toml"):
        Bundle.open(tmp_path / "empty")


def test_toml_dump_escapes_quotes_and_writes_lists():
    out = dump_toml({"a": 'say "hi"', "b": [1, "x"], "c": True})
    assert 'a = "say \\"hi\\""' in out
    assert 'b = [1, "x"]' in out
    assert "c = true" in out


#
# the command line
#


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "reportm.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_cli_fixture_then_build_then_check(tmp_path: Path):
    made = run_cli("fixture", "-j", "testdaten", cwd=tmp_path)
    assert made.returncode == 0, made.stderr

    built = run_cli("build", "-j", "testdaten", cwd=tmp_path)
    assert built.returncode == 0, built.stderr
    assert (tmp_path / "testdaten" / "testdaten.pdf").is_file()

    checked = run_cli("check", "-j", "testdaten", cwd=tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert "Inventarnummer" in checked.stdout
    assert "dataField" in checked.stdout


def test_cli_refuses_to_overwrite_a_job(tmp_path: Path):
    assert run_cli("fixture", "-j", "x", cwd=tmp_path).returncode == 0
    again = run_cli("fixture", "-j", "x", cwd=tmp_path)
    assert again.returncode == 1
    assert "already exists" in again.stderr


def test_cli_rejects_a_job_name_with_a_path(tmp_path: Path):
    bad = run_cli("fixture", "-j", "../escape", cwd=tmp_path)
    assert bad.returncode == 2
    assert "must not contain a path" in bad.stderr


def test_cli_needs_a_group_to_download(tmp_path: Path):
    out = run_cli("fetch", "-j", "x", cwd=tmp_path)
    assert out.returncode == 1
    assert "-g" in out.stderr


def test_cli_wants_a_job_name(tmp_path: Path):
    out = run_cli(cwd=tmp_path)
    assert out.returncode == 2
    assert "usage" in out.stdout.lower()


def test_cli_build_of_a_missing_job_is_one_line(tmp_path: Path):
    out = run_cli("build", "-j", "nichts", cwd=tmp_path)
    assert out.returncode == 1
    assert out.stderr.startswith("reportm: error:")
    assert "Traceback" not in out.stderr
