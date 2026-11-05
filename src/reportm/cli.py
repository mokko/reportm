"""
reportm - a PDF report of the MuseumPlus objects in a group, with their photos.

    reportm -j photo -g 416397          fetch the group, write photo/photo.pdf
    reportm fetch -j photo -g 416397    only download into photo/
    reportm build -j photo              only render photo/photo.pdf (offline)

The job name decides the directory and the report file, so several reports can
live side by side: -j photo, -j zeichnungen, -j ausstellung2027.

Fetching needs the database, rendering does not; keeping them apart means a
report can be rebuilt as often as wanted on a machine that has no access.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportm import __version__

USAGE = """\
reportm -j JOB -g GROUPID [options]    download the group, render the PDF
reportm fetch -j JOB -g GROUPID        download only
reportm build -j JOB                   render only (no database access)
reportm check -j JOB                   which configured fields find data
reportm fixture -j JOB                 write a synthetic job (no database)

The files of a job:
    <base>/<job>/bundle.toml     what this job is
    <base>/<job>/objects.xml     Object module, as fetched
    <base>/<job>/multimedia.xml  Multimedia module, as fetched
    <base>/<job>/images/         one file per multimedia record
    <base>/<job>/<job>.pdf       the report
"""


def _job_name(value: str) -> str:
    """A job is a directory name: keep it one, and keep it predictable."""
    name = value.strip()
    if not name:
        raise argparse.ArgumentTypeError("job name must not be empty")
    if name in (".", "..") or "/" in name or "\\" in name:
        raise argparse.ArgumentTypeError(f"job name must not contain a path: {value!r}")
    return name


def _add_selection(p: argparse.ArgumentParser) -> None:
    """The options that say which job is meant. Added to the main parser and to
    every subcommand, so both `reportm -j x -g 1` and `reportm build -j x` work."""
    p.add_argument(
        "-j", "--job", type=_job_name,
        help="name of this report; also its directory and file name",
    )
    p.add_argument("-g", "--group", help="group id in MuseumPlus")
    p.add_argument(
        "--base", default=".", help="directory the job directory goes into (default: .)"
    )
    p.add_argument("--title", help="report title (default: Objektbericht Gruppe <id>)")
    p.add_argument(
        "--config", help="field configuration (TOML); see the `check` command"
    )
    p.add_argument(
        "--max-edge", type=int, default=1800,
        help="longest edge of the scaled image copy, in pixels (default: 1800)",
    )
    p.add_argument("--max-images", type=int, help="at most this many photos per object")


def _add_download(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--refresh", action="store_true",
        help="re-fetch the data and re-download photos that are already there",
    )
    p.add_argument("--no-images", action="store_true", help="metadata only, no photos")
    p.add_argument(
        "--objects-xml", help="skip RIA: read the Object module XML from this file"
    )
    p.add_argument(
        "--multimedia-xml", help="skip RIA: read the Multimedia module XML from this file"
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reportm",
        description=(
            "Download the objects of a MuseumPlus group and write a PDF report "
            "with their metadata and photos. German: Objektbericht einer Gruppe."
        ),
        epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"reportm {__version__}")
    _add_selection(p)
    _add_download(p)
    p.add_argument("--pdf", help="output PDF (default: <job>/<job>.pdf)")

    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    f = sub.add_parser(
        "fetch",
        help="download only: group data and photos into the job directory",
        description="Download everything a report needs into the job directory. "
        "Runs again incrementally: files that are already there are kept unless "
        "--refresh is given.",
    )
    _add_selection(f)
    _add_download(f)

    b = sub.add_parser(
        "build",
        help="render only: job directory to PDF, without database access",
        description="Render the report from a job directory. Never touches the "
        "network, so it can be run and re-run anywhere.",
    )
    _add_selection(b)
    b.add_argument("--pdf", help="output PDF (default: <job>/<job>.pdf)")

    c = sub.add_parser(
        "check",
        help="show which configured fields actually find data",
        description="Read a job directory and report, per configured field, for how "
        "many objects it produced a value — plus every field name the data does "
        "contain. Run this before trusting a --config.",
    )
    _add_selection(c)

    x = sub.add_parser(
        "fixture",
        help="write a synthetic job, including the awkward cases (no database)",
        description="Generate a job with made-up objects and images so a report can "
        "be built on a machine without database access.",
    )
    _add_selection(x)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.job:
        parser.print_help()
        return 2
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except Exception as exc:  # one clear message, not a traceback
        print(f"reportm: error: {exc}", file=sys.stderr)
        return 1


def _job_dir(args) -> Path:
    return Path(args.base).expanduser() / args.job


def _require_group(args) -> None:
    if not args.group:
        raise ValueError(
            f"--group/-g is required to download job '{args.job}'. "
            "`build` and `check` do not need it — they read existing files."
        )


def _dispatch(args) -> int:
    from reportm.bundle import Bundle

    job_dir = _job_dir(args)
    exists = (job_dir / "bundle.toml").is_file()

    if args.command == "fixture":
        from reportm.fixture import make_fixture

        if job_dir.exists():
            raise FileExistsError(
                f"{job_dir} already exists — refusing to overwrite a job directory. "
                "Pick another -j, or remove it by hand."
            )
        bundle = make_fixture(job_dir, group_id=args.group, title=args.title)
        print(f"* test job written to {bundle.root}")
        print(f"* now: reportm build -j {args.job}")
        return 0

    if args.command == "check":
        return _cmd_check(args, Bundle.open(job_dir))

    if args.command == "build":
        return _cmd_build(args, Bundle.open(job_dir), job_dir)

    if args.command == "fetch":
        _require_group(args)
        return _cmd_fetch(args, Bundle.open(job_dir) if exists else None, job_dir)

    # no subcommand: download, then render
    _require_group(args)
    bundle = _fetch(args, Bundle.open(job_dir) if exists else None, job_dir)
    if bundle is None:
        return 1
    return _cmd_build(args, bundle, job_dir)


#
# commands
#


def _cmd_fetch(args, bundle, job_dir: Path) -> int:
    return 0 if _fetch(args, bundle, job_dir) is not None else 1


def _fetch(args, bundle, job_dir: Path):
    from reportm.fetch import fetch

    result = fetch(
        args.group,
        job_dir,
        refresh=args.refresh,
        title=args.title,
        objects_xml=args.objects_xml,
        multimedia_xml=args.multimedia_xml,
        with_images=not args.no_images,
    )
    print(
        f"* {result.objects} object(s), {result.multimedia} multimedia record(s) "
        f"-> {result.bundle.root}"
    )
    if args.objects_xml is None and not args.no_images:
        print(
            f"* photos: {result.downloaded} downloaded, {result.already_there} already "
            f"there, {result.no_attachment} record(s) without attachment"
        )
    if result.objects == 0:
        print(
            f"reportm: group {args.group} contains no objects — check the id",
            file=sys.stderr,
        )
        return None
    return result.bundle


def _cmd_build(args, bundle, job_dir: Path) -> int:
    from reportm.fields import load_config
    from reportm.render import build

    cfg = load_config(args.config)
    out = Path(args.pdf) if args.pdf else job_dir / f"{args.job}.pdf"
    _report(
        build(
            bundle,
            out,
            cfg=cfg,
            max_edge=args.max_edge,
            max_images=args.max_images,
            title=args.title,
        )
    )
    return 0


def _cmd_check(args, bundle) -> int:
    from reportm.fields import load_config, resolve
    from reportm.render import NSMAP, _image_files

    from lxml import etree

    if not bundle.objects_xml.is_file():
        raise FileNotFoundError(f"No object data in job: {bundle.objects_xml}")
    items = etree.parse(str(bundle.objects_xml)).xpath(
        "/m:application/m:modules/m:module[@name='Object']/m:moduleItem", namespaces=NSMAP
    )
    if not items:
        raise ValueError(f"{bundle.objects_xml} contains no Object moduleItems")

    cfg = load_config(args.config)
    print(f"* {len(items)} object(s) in {bundle.objects_xml}")
    print()
    print("configured fields:")
    for f in cfg.fields:
        if f.kind == "mul_count":
            found = sum(
                1
                for i in items
                if _image_files(
                    bundle.images_dir,
                    i.xpath(
                        "m:moduleReference[@name='ObjMultimediaRef']/m:moduleReferenceItem"
                        "/@moduleItemId",
                        namespaces=NSMAP,
                    ),
                )
            )
        else:
            found = sum(1 for i in items if resolve(i, f))
        mark = "ok " if found == len(items) else ("-- " if found == 0 else "~  ")
        print(f"  {mark}{found:>4}/{len(items)}  {f.label}")

    print()
    print("field names present in the data (for writing a --config):")
    seen_data: dict[str, int] = {}
    seen_group: dict[str, int] = {}
    for i in items:
        for name in i.xpath(".//m:dataField/@name", namespaces=NSMAP):
            seen_data[name] = seen_data.get(name, 0) + 1
        for name in i.xpath("./m:repeatableGroup/@name", namespaces=NSMAP):
            seen_group[name] = seen_group.get(name, 0) + 1
    for name, n in sorted(seen_data.items()):
        print(f"  dataField        {name}  ({n})")
    for name, n in sorted(seen_group.items()):
        print(f"  repeatableGroup  {name}  ({n})")
    return 0


def _report(result) -> None:
    print(f"* {result.objects} object(s), {result.images} photo(s) -> {result.path}")
    if result.skipped:
        print(
            f"* skipped {result.skipped} file(s) that are not readable images",
            file=sys.stderr,
        )
    if result.without_image:
        print(f"* {result.without_image} object(s) have no photo")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
