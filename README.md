# reportm

## A PDF report of the objects in a MuseumPlus group

Give it a group id, get a multipage PDF: one page per object, with the metadata
fields you chose and the object's photos.

```
reportm -j photo -g 416397
```

The **job name** (`-j`) is the report's name, its directory and its file name, so
several reports can sit next to each other — `-j photo`, `-j zeichnungen`,
`-j ausstellung2027`. Everything a job needs is kept in its own directory:

```
photo/
    bundle.toml      what this job is: group id, source, fetch date, title
    objects.xml      Object module, exactly as fetched
    multimedia.xml   Multimedia module, exactly as fetched
    images/          one file per multimedia record: <mulId>.<ext>
    scaled/          report-sized copies, written at build time
    photo.pdf        the report
```

## Why it is two steps

Fetching needs the database; rendering does not.

```
reportm fetch -j photo -g 416397    # only download into photo/
reportm build -j photo              # only render photo/photo.pdf
```

That split is not decoration. The data is downloaded once and the report is
rebuilt as often as wanted afterwards — on a machine that has no access to RIA
at all, which is exactly where the layout gets developed. `build` never opens a
socket and never needs credentials; it reads the job directory.

For the same reason `reportm fetch` accepts `--objects-xml` and
`--multimedia-xml`, so a job can be assembled from documents that came from
somewhere else.

## Install

```
git clone https://github.com/mokko/reportm.git
cd reportm
pip install .
```

Needs `MpApi` (from git), `lxml`, `requests`, `Pillow`, `reportlab`, and the RIA
credentials in `~/.ria` (`user`, `pw`, `baseURL`), the same file MpApi's own
commands read.

## Usage

```
reportm -j JOB -g GROUPID [--base DIR] [--title T] [--config FILE]
                          [--max-edge PX] [--max-images N] [--pdf FILE]
                          [--refresh] [--no-images]

reportm fetch -j JOB -g GROUPID [...]     download only
reportm build -j JOB [...]                render only (no database access)
reportm check -j JOB [--config FILE]      which fields actually find data
reportm fixture -j JOB                    write a synthetic job, no database
```

| | |
|---|---|
| `-j JOB` | report name; also its directory and PDF file name |
| `-g GROUPID` | MuseumPlus group id (not needed by `build`/`check`/`fixture`) |
| `--base DIR` | where the job directory goes (default: `.`) |
| `--max-edge PX` | longest edge of the image copy that goes into the PDF (default 1800) |
| `--max-images N` | at most this many photos per object |
| `--refresh` | re-fetch data and re-download photos that are already there |
| `--no-images` | metadata only |

Typical run:

```
reportm -j photo -g 416397
# * searching Object in group 416397
# * 43 object(s), 61 multimedia record(s) -> photo
# * photos: 61 downloaded, 0 already there, 3 record(s) without attachment
# * 43 object(s), 58 photo(s) -> photo/photo.pdf
```

## Which metadata ends up on the page

`reportm check -j photo` prints, for every configured field, how many objects it
found something for, followed by every field name the downloaded data actually
contains:

```
* 43 object(s) in photo/objects.xml

configured fields:
  ok     43/43  Inventarnummer
  ok     43/43  Titel
  ~      12/43  Datierung
  --      0/43  Erwerbsnotiz

field names present in the data (for writing a --config):
  dataField        ObjObjectNumberTxt  (43)
  repeatableGroup  ObjObjectTitleGrp  (43)
  ...
```

A field that resolves for nobody (`--`) is a wrong XPath, not empty data — fix
it in a config rather than wondering why the report is thin:

```toml
[report]
title = "Objektbericht Foto"

[[fields]]
label = "Inventarnummer"
paths = ["m:dataField[@name='ObjObjectNumberTxt']/m:value"]

[[fields]]
label = "Datierung"
paths = [
  "m:repeatableGroup[@name='ObjDateGrp']/m:repeatableGroupItem/m:dataField[@name='DateTxt']/m:value",
  "m:repeatableGroup[@name='ObjDateGrp']/m:repeatableGroupItem/m:dataField[@name='DateFromTxt']/m:value",
]
```

Each field takes a list of paths; the first one that produces something wins,
because instances differ in which field carries a value. `kind = "mul_count"`
is the one built-in field that is not a path — it counts the object's photos.
The default list is in `src/reportm/fields.py`.

## Behaviour worth knowing

- **Nothing is deleted, ever.** `fetch` only adds; photos already on disk are
  kept unless `--refresh`. A second run completes an interrupted first one.
- **It refuses to mix groups.** Fetching a different group id into an existing
  job directory is an error, not a merge.
- **Photos are keyed on the multimedia id, not the file name**, because two
  records can share an original file name and one object can have several
  photos.
- **EXIF orientation is applied and CMYK/16-bit files are converted** before
  scaling; portrait photos otherwise arrive sideways, and TIFFs fail to save.
- **A file that is not an image is skipped and counted**, not fatal — a broken
  attachment should not cost you the report. The count goes to stderr.
- **The PDF is written last.** Scaling happens before the document is opened, so
  a failure leaves no half-written report.

## Testing without a database

`reportm fixture -j testdaten` writes a synthetic job — three objects, one full
record, one without a title, one without a usable photo, plus a deliberately
broken attachment and a TIFF that has to be converted:

```
reportm fixture -j testdaten
reportm build -j testdaten
reportm check -j testdaten
```

The fixture is generated, not copied from real material, so it is safe to keep
in the repository. `pytest` runs the same file.
