# GoFreight Shipment Importer

Bulk-creates ocean import shipments in [GoFreight](https://gofreight.com)
through its REST API, instead of keying them in one at a time.

Built for a freight forwarding operation that receives 60–90 shipments per
vessel. Each one used to be created by hand in the GoFreight web UI — the
same twenty-odd fields, sixty times a sailing. This reads a CSV and creates
them in one run.

## What it does

One API call per shipment creates the master bill, its containers and its
house bill together:

```
POST /api/v1/shipments/ocean-import/mbl
```

Before each create it looks the shipment up by MB/L number, so re-running
after a partial failure skips what is already there instead of duplicating it.

## Requirements

- Python 3.9+
- A GoFreight API key (issued by GoFreight — the account cannot generate one
  itself)
- Your office ref, which `lookup.py offices` will list
- `pip install -r requirements.txt`

Request bodies are built against GoFreight's published OpenAPI specification.
Three fields are required per shipment: `mbl_no`, `office_ref` and
`estimated_arrival_date`. Ports are UN/LOCODE (`CNSHA`, not `SHANGHAI`), and
each container needs `container_no` and a `container_size_ref` that already
exists in the account. Shipper, consignee and notify party are set on the
house bill and reference trade partner records rather than free-text names.

## Setup

The key is read from the `GOFREIGHT_API_KEY` environment variable. It is
never read from a file in the repo and never passed on the command line.

Windows (PowerShell), once:

```powershell
[Environment]::SetEnvironmentVariable("GOFREIGHT_API_KEY","<your key>","User")
```

Open a new terminal afterwards — an existing one will not see it.

macOS / Linux:

```bash
export GOFREIGHT_API_KEY='<your key>'
```

## Usage

On Windows, `START.bat` wraps the steps below in a menu — check the key, look
up refs, convert a report, preview, create. Creating for real is behind a
typed confirmation rather than a menu number.



Verify the key works. Read-only, writes nothing:

```bash
python check.py
```

Look up the refs the request body needs. All read-only:

```bash
python lookup.py offices           # office_ref
python lookup.py sizes             # container_size_ref
python lookup.py packages          # package_unit_ref
python lookup.py partners ACME     # shipper_ref / consignee_ref / notify_ref
```

List the account's custom fields, also read-only:

```bash
python fields.py
```

Preview what would be sent. This is the default — nothing leaves your machine:

```bash
python push.py examples/shipments.csv
```

Create the shipments for real:

```bash
python push.py examples/shipments.csv --go
```

Results are appended to `push_log.csv` with the `ref` GoFreight returns for
each shipment, so a run can be audited or reversed afterwards.

## From an existing report

`from_report.py` converts the Excel report produced by the upstream document
tool into the CSV this expects, resolving port names to UN/LOCODE and merging
split bills (one master, several house bills) into a single row:

```bash
python from_report.py _report.xlsx --eta 2026-12-05 --vessel "CMA CGM SWORDFISH" --voyage EXX0G0E
```

ETA is supplied on the command line because the booking list carries no
arrival date and every shipment on a sailing shares one. Port names are
resolved through `locodes.csv`, which is a plain table to extend rather than
code to edit; names that cannot be resolved are left empty and reported
rather than guessed.

## Input format

A CSV with one row per shipment. Multi-container shipments put several
values in one cell, comma separated, in matching order:

| column | required | example |
|---|---|---|
| `mbl_no` | yes | `DEMO1000001` |
| `eta` | yes | `2026-12-12` |
| `pol` | no | `CNSHA` |
| `pod` | no | `USNYC` |
| `vessel_name` | no | `DEMO VESSEL` |
| `voyage` | no | `EXX011E` |
| `hbl_no` | no | `AIC2600A000001` |
| `container_no` | no | `ABCU1000003,ABCU1000004` |
| `seal_no` | no | `S1000003,S1000004` |
| `container_size_ref` | no | `40HC,40HC` |
| `package` | no | `520,520` |
| `weight` | no | `8372.000,8372.000` |
| `measurement` | no | `64.860,64.860` |
| `shipper_ref` | no | trade partner ref |
| `consignee_ref` | no | trade partner ref |
| `notify_ref` | no | trade partner ref |
| `description` | no | `TENT` |
| `mark` | no | `N/M` |

`package`, `weight` and `measurement` are the totals for the shipment. On a
multi-container shipment GoFreight expects them on the first container only,
with the remaining containers left empty — filling each container, or the
totals row, produces incorrect printed documents. Values already split per
container (`520,520`) are summed rather than rejected.

`weight_unit` defaults to KG and `measurement_unit` to CBM; both are sent
explicitly so the account default cannot reinterpret the numbers.

See `examples/shipments.csv`. Anything that can produce this CSV can feed
the importer — the field mapping lives in `payload.py` and nothing else
depends on where the data came from.

## Developing without credentials

`dev/mock_gofreight.py` is a local stand-in that speaks the same endpoints,
so the full path can be exercised before a key exists:

```bash
python dev/mock_gofreight.py            # terminal 1

export GOFREIGHT_BASE_URL=http://127.0.0.1:8900   # terminal 2
export GOFREIGHT_API_KEY=LOCAL-TEST
python push.py examples/shipments.csv --go
```

## Layout

```
gofreight.py    API client — auth, requests, error handling
lookup.py       Read-only lookups for office, container size and partner refs
from_report.py  Converts the upstream Excel report into this CSV
START.bat       Windows menu wrapper for the steps above
locodes.csv     Port name -> UN/LOCODE table, extend as needed
payload.py      CSV row -> request body. No network, testable on its own
check.py        Read-only key check
fields.py       Read-only custom field listing
push.py         Main program
dev/            Local mock server
examples/       Sample input
```

## Notes

The create endpoint accepts an array, so several shipments can go in one
call. This sends one per call on purpose: a rejected shipment is then
attributable to a single row rather than failing a batch. Rows whose data is
invalid are reported and skipped without being sent at all.

`push.py` prints and exits unless `--go` is passed. Creating shipments is
not reversible from this tool, and deleting them afterwards is considerably
more work than reviewing the preview.
