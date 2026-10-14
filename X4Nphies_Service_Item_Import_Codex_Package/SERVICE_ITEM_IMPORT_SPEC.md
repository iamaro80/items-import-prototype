# X4Nphies — Enterprise Service Item Import Tool
## Master Implementation Specification for Codex
**Version:** 2.0  
**Target:** Existing X4Nphies healthcare application  
**Goal:** Implement a working, scalable, ERP-independent import engine integrated with the existing Service Item Management UI.

> **Highest-priority rule:** Import all eligible independent records, isolate invalid and runtime-failing records, and produce a complete final report. Never silently create missing references or simulate processing.

## 1. Supplied reference files
- `sources/Pasted text(20261014-200541).txt`: Full application HTML capture (UI and navigation reference).
- `sources/Pasted text (2)(1).txt`: Service Item Management page HTML capture (specific screen reference).
- `sources/Untitled spreadsheet - Sheet1.csv`: Actual sample CSV (49 data rows, 33 columns).

The HTML is a rendered DOM snapshot, **not** frontend source code or a reliable API contract. Inspect the actual repository, backend, and database before implementation. The CSV is a sample fixture, not proof of the destination schema.

## 2. Existing application integration
Observed from supplied HTML:
- X4Nphies application shell, fixed header, left navigation, facility selector, user menu, Arabic/English language option.
- React-style application with Material UI and styled-component classes; inspect package versions in the repository.
- Service Item route family `/NGHA/itemServiceManagment` and view links `/NGHA/itemServiceManagment/viewItem/{id}`.
- Search fields: Hospital Code, Code, Description, Status, Is packages.
- Toolbar: Export, Download Sample, Upload, Add Item, Add Multiple Items, Sync.
- Listing: Chapter, Block, Code, Long description, Short description, Hospital Code, Hospital Description, Alias, Status, Actions; View/Edit and Active/Inactive controls.

Enhance the **existing Upload** action to open the import wizard. Add Import History/Jobs access near the toolbar. Preserve existing operations and visual identity. Reuse actual UI components and localization, including Arabic/RTL. Determine whether Service Items are global, facility-specific, or shared with facility attributes; enforce the actual ownership and permissions model. Never infer API or database behavior from markup alone.

## 3. End-to-end user journey
**Upload → Preview → Map Fields → Configure → Test/Validate → Review Errors → Resolve Missing References → Retest → Confirm → Background Import → Monitor → Final Report → Correct/Retry.**

### 3.1 Upload
CSV and XLSX, drag/drop and file picker, resumable/streamed/chunked upload where appropriate, progress, checksum, metadata, file size and row count. Store securely and durably; do not modify business records. Detect encoding, delimiter, headers and invalid formats. Protect against unsafe files.

### 3.2 Preview
Server-side paginated sample (e.g. 100 rows), original headers, original values, source row numbers, type profiling, null counts, sample distributions, and warnings. Never render the entire large file client-side.

### 3.3 Map fields
Show source column, sample value, suggested destination, type, required status, transformation, reference lookup and mapping status. Support auto-suggestions, manual mappings, aliases, defaults, optional ignore, transformations, conditional rules, saved/versioned templates, and target-field discovery. Preserve original values.

### 3.4 Test Import
Start a **durable asynchronous dry-run** that validates the entire file and stores row-level results. It must **not** modify production Service Items or create references. Show actual persisted progress. Distinguish structural errors, field errors, duplicates, business-rule errors, warnings, and unresolved/ambiguous references.

### 3.5 Review and resolve
Separate Valid, Valid with Warnings, Invalid, Duplicate/Conflict, Pending Reference Resolution, and Excluded views. Export validation issues. Let users resolve grouped missing references (Section 7), retest affected records, and see revised counts.

### 3.6 Confirm and execute
Present a versioned, immutable import plan with source totals, eligible rows, warnings, invalid/unresolved rows, create/update/skip counts, reference creation approvals, import mode and blank update policy. Explicitly confirm. Recheck critical constraints at execution due to possible database changes.

### 3.7 Monitor and report
Durable job monitor, pause/resume/cancel at safe boundaries, status and throughput, persisted counters, reports, and corrected-record reimport. Closing the browser must not stop a job.

## 4. Sample CSV schema
**Exact source headers (33):**
```text
Code,ShortDescription,LongDesription,HospitalCode,HospitalDescription,IsListed,IsPackge,Alias,Chapter,Block,CostCenter,SubCostCenter,Department,SubDepatment,Category,TaxCategory,Type,MaterialCost,RegisterNumber,ScientificName,ScientificCode,DescriptionCode,Strength,StrengthUnit,PharmaceuticalForm,AdministrationRoute,PackageTypes,PackageSize,ProductControl,DistributeArea,DiscontinuedDate,PublicPrice,Status
```
49 data rows in the supplied fixture; all `Code` values populated and distinct. `IsListed` and `PublicPrice` are blank in all rows; all `Status` values are `Active`. 47 `DiscontinuedDate` values are populated. These observations must **not** become universal rules.

Aliases: `LongDesription` → LongDescription; `IsPackge` → IsPackage; `SubDepatment` → SubDepartment. Keep source headers intact in staging.

## 5. Proposed logical field mapping
These are **proposed logical names**, not verified database fields. Inspect the actual target schema.

| Source | Logical destination | Handling |
|---|---|---|
| Code | service_code | String business key; preserve leading zeros |
| ShortDescription | name | Text |
| LongDesription | long_description | Text |
| HospitalCode | hospital_code | String |
| HospitalDescription | hospital_description | Text |
| IsListed | is_listed | Nullable boolean |
| IsPackge | is_package | yes/no conversion |
| Alias | alias | Text |
| Chapter | chapter | Reference lookup |
| Block | block | Parent-aware reference lookup |
| CostCenter | cost_center | Reference lookup |
| SubCostCenter | sub_cost_center | Parent-aware reference lookup |
| Department | department | Reference lookup |
| SubDepatment | sub_department | Parent-aware reference lookup |
| Category | category | Reference lookup |
| TaxCategory | tax_category | Percentage or reference lookup |
| Type | service_type | Reference lookup |
| MaterialCost | material_cost | Decimal |
| RegisterNumber | registration_number | String |
| ScientificName | scientific_name | Text |
| ScientificCode | scientific_code | String |
| DescriptionCode | description_code | String |
| Strength | strength | Configurable |
| StrengthUnit | strength_unit | Reference lookup |
| PharmaceuticalForm | pharmaceutical_form | Reference lookup |
| AdministrationRoute | administration_route | Reference lookup |
| PackageTypes | package_type | Reference lookup |
| PackageSize | package_size | Configurable string |
| ProductControl | product_control | Reference lookup |
| DistributeArea | distribution_area | Reference lookup |
| DiscontinuedDate | discontinued_date | Locale-configured date |
| PublicPrice | public_price | Nullable decimal |
| Status | status | Validated selection |

Preserve null distinct from false and zero. Do not turn blank `PublicPrice` into zero or blank `IsListed` into false without explicit policy. `4/11/2025 12:00:00 AM` is ambiguous by locale: require format selection. `Active` with a populated discontinuation date should be a configurable warning, not automatically a blocking error. Support `0%`/`15%` tax values; recognize sample service types including `MedicationCodes`, `Laboratory`, `TransportationSrca` without silently fixing unknown values. Use decimal arithmetic for monetary fields. Update blanks policy: preserve existing / clear / default.

## 6. Validation engine
Store every issue with job ID, source row, field, original/transformed values, rule code, severity, message and suggested correction. Cover:
- Structural: missing/duplicate headers, encoding, malformed CSV, wrong field counts, unsupported files.
- Field: required, type, range, length, boolean, decimal, date, enum.
- Business: conditional requirements, service-type rules, prices, lifecycle/status, facility rules.
- Duplicates: within file, against target, ambiguous matches, concurrency.
- References: absent, ambiguous, inactive, wrong parent.
- Warning versus blocking classification is configurable and explicit.

A record may have multiple issues, but must have **one reconciled final processing outcome**.

## 7. Mandatory user-controlled missing references
Group distinct missing values by reference field, normalized source value, parent context and affected row count. Provide suggestions, search and bulk decisions:
1. **Map to existing** reference.
2. **Propose create new**, requiring authorization/approval.
3. **Leave blank** only if optional and allowed.
4. **Skip affected records**.
5. **Defer** pending resolution.

Parent-aware lookups: Chapter → Block; Cost Center → Sub Cost Center; Department → Sub Department. Matching a label under the wrong parent is invalid. Test Import **never creates** references. At execution, recheck approved reference uniqueness, create idempotently, persist resolved ID, then process dependents. If creation fails, block/fail only dependent rows and continue unrelated work. Audit all decisions and approvals. Retest after resolution changes.

## 8. Mandatory partial-success import
**Default: import all eligible independent records and report the rest.**

Classification: Valid, Valid with Warnings, Invalid, Pending Reference Resolution, Duplicate/Conflict, Excluded.

Offer import modes:
- Import all eligible records (default).
- Include warning-only records according to configured policy.
- Import selected eligible records.
- Strict mode: block until errors resolved.

Blocking-invalid records must not be imported. Unresolved mandatory references must not be imported. A failing row must not roll back unrelated committed rows. Use transaction savepoints, smaller retry units or equivalent. On bulk failure, isolate offending records and retry bounded subsets; do not endlessly retry permanent errors. Runtime database conflicts must be logged and isolated. System-wide outages can safely pause jobs.

Final states: **Completed Successfully**, **Completed with Errors**, **Failed**, **Cancelled**. Mixed success is normally **Completed with Errors**.

## 9. Create/update modes
Support Create Only, Update Only, Upsert, Skip Existing. Define business-key uniqueness in the **verified** facility/organization scope; never assume `Code` globally unique. Resolve duplicate source keys with explicit policy. On updates, blank means preserve / clear / default as configured. Require confirmation for destructive changes. Enforce uniqueness and idempotency.

## 10. Architecture and durable data
Logical components:
- Upload and durable object/file storage.
- Streaming parser and staging.
- Mapping and transformation engine.
- Validation engine and reference resolver.
- Durable queue/scheduler.
- Background import workers.
- Progress monitoring and reporting.

Logical persistent entities:
- `ImportJob`: owner, facility, source checksum, state, mode, counters, mapping/validation versions, timestamps.
- `ImportStagingRecord`: original and transformed values, row number, eligibility, processing outcome, destination ID.
- `ImportMapping`: mappings, rules, transformations, template version.
- `ImportReferenceResolution`: source value, parent, decision, approval, resolved ID.
- `ImportValidationIssue`: row, field, rule, severity, explanation.
- `ImportBatch`: bounded work unit, lease, attempts, checkpoint, counts, timestamps.
- `ImportAuditEvent`: user and system decisions, state transitions, approvals.
- Optional separate `ImportExecution` linked to logical job.

Choose existing project infrastructure when appropriate. Implement durable queues, worker leasing/crash recovery, atomic checkpoints where feasible, idempotent writes, bounded retries, concurrency controls, tenant isolation and audit logs. Reconcile writes and job state if they reside in different transactional systems.

## 11. Performance and operational isolation
Architect for hundreds of thousands to millions of rows, not browser-side loops or one giant transaction. Example: 1,000,000 records / 500 per batch = 2,000 batches (batch size configurable). Use streaming I/O, bulk reference lookups, indexes, bounded memory, short transactions, worker concurrency limits, connection caps, backpressure, throttling and off-peak scheduling. Do not claim zero performance impact or million-record capacity without measurements.

## 12. Job monitoring
Show job ID, file, facility, submitter, mode, total, validated, created, updated, warning-success, skipped, failed, pending, percentage, batch, throughput, elapsed time, ETA, current status, recent errors. Support pause, resume, cancel, retry failures, report downloads. Use polling/SSE/WebSockets appropriate to codebase; data must be persisted, not simulated. Cancellation stops future work at safe boundaries without undoing committed records.

## 13. Final reports and corrected retry
Provide summary counts and detailed CSV/XLSX error report. Fields: source row, Code, ShortDescription, failed field, original value, error type, message, suggested correction, processing status, retry eligibility, job ID. Preserve multiple issues per record and original 33 source columns in a **failed-records reimport file**. Escape spreadsheet formula-like values in exported files. Allow correcting and uploading only unsuccessful records; reuse mappings when suitable, retest, and link retry job to original. Never duplicate successful records.

## 14. Security and localization
Authentication, role-based import/approval access, facility/tenant isolation, secure storage, file validation, upload limits, audit, sensitive-data-safe logs, retention/deletion, safe downloads. Reuse existing English/Arabic translation mechanism and RTL conventions. Ensure accessible and responsive wizard.

## 15. Logical API operations
Discover existing APIs first. Implement equivalent endpoints/actions for: create job; upload chunks/stream; file metadata; preview; target field discovery; mapping save; start validation; validation status/issues; unresolved references; resolution decisions/approvals; retest; immutable plan; confirm import; job progress; pause/resume/cancel; download reports; create retry job. Use established auth, pagination and error formats.

## 16. Testing
Automate:
- CSV fixture parses 49 rows and 33 exact headers.
- Header aliases, quoted delimiters, Unicode, nulls, leading zeros, malformed rows.
- Mapping and type conversion, nullable booleans, decimal, ambiguous dates, blank update policies.
- Duplicate keys, reference lookups, hierarchy, missing reference approvals, concurrency.
- Test Import has **no production business writes**.
- Mixed-validity import commits eligible rows and reports every rejected row.
- Runtime failure isolation, retry idempotency, worker crash recovery, pause/resume/cancel, browser disconnect.
- Final outcome counts reconcile with source rows; multiple issues do not double-count.
- Corrected-record reimport does not duplicate successes.
- UI wizard, existing toolbar regression, English/Arabic and RTL.

## 17. Performance benchmarks
Generate synthetic 33-column datasets at 1,000; 10,000; 100,000; 1,000,000 rows. Measure upload, parsing, validation, import throughput, peak memory, CPU, DB I/O, transaction duration, worker recovery, and concurrent interactive request latency. Record hardware, DB configuration, worker count, batch size and data characteristics. Never present synthetic data as the supplied fixture. Report actual results and limitations.

## 18. Acceptance criteria
1. Existing X4Nphies Service Item page and actions still work; Upload opens wizard.
2. Facility context and permissions enforced.
3. Source CSV parses 49 records, 33 columns and preserves original values.
4. Mapping handles aliases and all columns can be mapped or explicitly ignored if allowed.
5. Async Test Import validates entire file with no production Service Item/reference writes.
6. Row-level issues, warnings, duplicates and missing references are visible and exportable.
7. User can map/create-with-approval/skip/defer missing references; hierarchical context enforced.
8. Retest refreshes eligibility; immutable confirmed import plan recorded.
9. Valid independent rows import despite invalid rows; failures isolated.
10. Background workers, durable state, safe retry and crash recovery are real.
11. Browser can close; progress and final reports remain available.
12. Final counts reconcile; mixed outcomes use Completed with Errors.
13. Failed records downloadable, correctable, retestable and safely reimportable.
14. Performance results are measured, not asserted.

## 19. Implementation phases for Codex
**Phase 1 — Repository discovery:** inspect frontend, Service Item source, Upload behavior, API clients, DB models, facility ownership, permissions, existing queue, deployment and tests. Report confirmed facts and open decisions.

**Phase 2 — Architecture:** propose data model, queue, staging, validation, reference resolution, partial-success transaction strategy, endpoints, UI integration, observability and test strategy. Ask approval for essential business decisions.

**Phase 3 — Foundation:** upload, persistent jobs, parser, staging, preview, mapping.

**Phase 4 — Validation:** asynchronous Test Import, issues, duplicates, reference detection, validation UI.

**Phase 5 — Resolution:** grouped missing-reference decisions, approvals, retest.

**Phase 6 — Execution:** immutable plan, background workers, batches, partial success, idempotency, recovery, pause/resume/cancel.

**Phase 7 — Monitoring/reporting:** Import History, progress, downloadable errors, retry workflow.

**Phase 8 — Verification:** unit, integration, UI, regression, failure recovery, scalability benchmarks; evidence against acceptance criteria.

## 20. Final directive
Implement a **working feature integrated into the existing application**, not a standalone mockup. Inspect the codebase before choosing frameworks, endpoints, schemas or business rules. Preserve current UI conventions. Never silently create missing references, never change production business data during Test Import, never block valid independent rows because others fail, never fake progress, and never claim scalability without measurement. Deliver code, migrations, tests, deployment instructions, documented assumptions and an acceptance checklist.
