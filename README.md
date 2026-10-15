# Service Item Import Tool — Interactive Prototype

Standalone Django application for demonstrating a real Service Item import workflow. It uses local SQLite data and does **not** connect to X4Nphies, Odoo, or a production system. The visual shell is inspired by the supplied X4Nphies HTML captures while remaining clearly labeled as a prototype.

## Stack

Python 3.12+, Django 5.2 LTS, SQLite, Django templates, locally bundled Bootstrap 5 and Bootstrap Icons, custom CSS, vanilla JavaScript, Python `csv`, and `openpyxl`. One Django management-command worker processes validation and imports in the background. No Docker, Redis, Celery, or frontend build pipeline is required.

## Start locally

```bash
./setup.sh
./run.sh
```

In another terminal:

```bash
./run_worker.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The worker must remain running for Test Import and final import. Uploaded files, job state, issues, and Service Items persist if the browser closes or the web server restarts.

## Demonstration walkthrough

1. Open **Demo Administration** and select **Load supplied CSV**. This stages the original 49-row, 33-column file without editing it. Browser upload is also available under **Import Service Items**.
2. Review the paginated original values. Open **Map Fields** to accept or change suggestions. The three source spellings `LongDesription`, `IsPackge`, and `SubDepatment` map to their correctly named target fields. Choose text transformations or save/reuse a mapping template.
3. In **Configure**, choose Create Only, Update Only, Create or Update, or Skip Existing. Choose the blank-update policy and **explicitly select** how dates such as `4/11/2025` should be interpreted.
4. Run **Test Import**. It validates every row in the worker and writes no Service Items or master references. Review row issues and download the validation issue CSV.
5. Open **Resolve references**. The seeded fixtures deliberately omit `QA test block` and `(1234532) - zzzzzzzzzzzz`. Map a value to an existing reference, approve creation of a new demo reference, skip, or defer. Retest after decisions. New references are only created during confirmed import.
6. Review the create/update/skipped/pending counts on **Confirm** and select **Import eligible records**. The worker writes eligible items in separate transactions, continues after independent row failures, and persists real progress. Imported records appear under **Service Items**.
7. Open **Final results** for summary, detailed errors, and original-column failed-records CSV. Upload a corrected file through **Upload corrected records** to reuse its mapping and link the retry to the prior job.
8. Open **Import History** to revisit either job.

For a clear partial-success demonstration, use **Load mixed-validity CSV** in Demo Administration after the original import. `demo_data/mixed_validity.csv` is explicitly synthetic and separate from the unchanged supplied CSV. It contains valid rows, an invalid decimal, an unknown reference, a duplicate code, and a code that updates an existing item. The default policy imports eligible rows and reports the rest.

## Reset

Use **Demo Administration → Reset to first-run state**, typing `RESET DEMO`, or run:

```bash
./reset_demo.sh
```

Reset deletes all prototype import jobs and history, uploaded media files, Service Items, saved mapping templates, references, and facilities. It then restores exactly the two starter facilities and deterministic reference fixtures from setup. It preserves the original package files and synthetic CSV. Wait for any running import to finish or cancel it before resetting. It does not alter another application or database.

## Tests

```bash
.venv/bin/python manage.py test core
.venv/bin/python manage.py check
```

The automated workflow tests cover exact sample headers and aliases, 49-row staging, dry-run isolation, reference decisions and approval, partial success, pause/resume, report export, corrected retry, worker idempotency, and primary view rendering. The code uses Django migrations in `core/migrations/`.

## Business rules and editable locations

- Business key: facility + service code, enforced by a database unique constraint.
- Tax category: reference label, preserving `0%` and `15%` source strings.
- Date interpretation: selected per job; never guessed from ambiguous source text.
- Blank values remain distinct from false or zero. On update, use Preserve, Clear, or Default.
- One source row has one final outcome, even if it has several issues. Warning successes count as created or updated once.
- Reference matching considers the parent for Block, Sub Cost Center, and Sub Department.
- User decisions are stored and audited; missing references are never silently created.

Field definitions and aliases are in `core/schema.py`. Validation and import rules are in `core/engine.py`. Worker execution and progress checkpoints are in `core/management/commands/run_import_worker.py`. Page templates are in `templates/core/`; theme tokens are at the start of `static/css/theme.css`.

## Prototype limits

This is a local, single-worker demonstration. It has no production authentication, facility authorization, retention policy, or deployment hardening. SQLite and the management-command queue are suitable for the supplied dataset and local demonstrations; no million-row capacity or high-concurrency claim is made. The interface is English-first, with layout and strings organized for future Arabic/RTL work. The edit form exposes common descriptive fields; full field maintenance remains part of the import workflow. Benchmarking larger synthetic datasets is optional and should be reported with measured hardware and timing before making performance claims.
