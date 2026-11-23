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
POST /api/v1/shipments/ocean-import/mbl/
```

Before each create it looks the shipment up by MB/L number, so re-running
after a partial failure skips what is already there instead of duplicating it.

## Requirements

- Python 3.9+
- A GoFreight API key (issued by GoFreight — the account cannot generate one
  itself)
- `pip install -r requirements.txt`

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

Verify the key works. Read-only, writes nothing:

```bash
python check.py
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

## Input format

A CSV with one row per shipment. Multi-container shipments put several
values in one cell, comma separated, in matching order:

| column | required | example |
|---|---|---|
| `mbl_no` | yes | `DEMO1000001` |
| `pol` | yes | `SHANGHAI` |
| `pod` | yes | `LOS ANGELES` |
| `hbl_no` | no | `AIC2600A000001` |
| `container_no` | no | `ABCU1000003,ABCU1000004` |
| `seal_no` | no | `S1000003,S1000004` |
| `size_type` | no | `40HC,40HC` |
| `pieces` | no | `1040` |
| `weight` | no | `16744.000` |
| `measurement` | no | `129.720` |
| `eta` | no | `2026-12-12` |

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
payload.py      CSV row -> request body. No network, testable on its own
check.py        Read-only key check
fields.py       Read-only custom field listing
push.py         Main program
dev/            Local mock server
examples/       Sample input
```

## Notes

The field names in `payload.py` follow GoFreight's published examples and
should be checked against the schema in their API reference before a first
production run — a wrong required field name fails the whole batch.

`push.py` prints and exits unless `--go` is passed. Creating shipments is
not reversible from this tool, and deleting them afterwards is considerably
more work than reviewing the preview.
