# Soup HFL pilot: examples and usage

Status: Companion to the [implementation thesis](../thesis/SOUP-HFL-MODEL-TRAINING.md),
2026-09-29. This guide documents an isolated experiment. HARQIS does not yet
implement the proposed local-provider switch, dataset exporter, evaluator,
shadow mode, or promotion controls. The commands below operate Soup directly.

## 1. Inspect the examples

The [example directory](../examples/soup-hfl/README.md) contains public synthetic
data, a minimal training configuration, and a chat request. No real corpus data
or secrets are included. The three training rows illustrate meaningful work,
mechanical activity, and a bounded fix. The request uses a different synthetic
event; one example request is not a held-out evaluation suite.

Training uses the ChatML `messages` shape, with assistant content containing
the JSON entry as a string. This format is documented by
[Soup](https://trysoup.dev/docs/data-formats). The example system message is
deliberately short; real comparisons must use the exact versioned
[Git prompt](../../workflows/hfl/prompts/ingest_git.md) in all arms.

Expected shape for meaningful work:

```json
{
  "skip": false,
  "moment": "Adds a retry path for failed digest delivery",
  "what_happened": "The example project adds retries for failed digest delivery. It also adds a test for retry exhaustion.",
  "why_it_stayed": "",
  "possible_use": "standup",
  "tags": ["example-project", "delivery", "retry"]
}
```

An empty `why_it_stayed` avoids inventing the operator's motivation. A commit
subject describing a feature does not prove a successful production rollout.

## 2. Prepare an isolated experiment

Prerequisites: Git checkout, Python 3.10–3.12, sufficient disk/RAM, network access
for initial package/model downloads, and a compatible training backend. The
example targets CUDA with 4-bit training; CPU and Apple configurations need
their own backend choices. Windows command syntax below does not establish
that this machine's CUDA stack works. Use a compatible Linux/WSL2 GPU environment
if the installed backend requires it.

The following PowerShell commands start in the repository root and copy only
synthetic assets to a timestamped directory outside the checkout:

```powershell
$soupExperiment = Join-Path $env:LOCALAPPDATA ("harqis-experiments/soup-hfl-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $soupExperiment -ErrorAction Stop | Out-Null
Write-Output $soupExperiment
Copy-Item -Path docs/examples/soup-hfl/*.jsonl,docs/examples/soup-hfl/*.json,docs/examples/soup-hfl/*.yaml -Destination $soupExperiment
Set-Location -LiteralPath $soupExperiment
py -3.11 -m venv .venv
```

Choose and record an exact Soup version after checking its published release
notes and package availability. The researched documentation discusses v0.75.1;
that is not a tested HARQIS dependency pin. Replace the marker before running:

```powershell
$soupVersion = '<reviewed-release-version>'
if ($soupVersion.StartsWith('<')) { throw 'Select an exact Soup release first.' }
& ./.venv/Scripts/python.exe -m pip install "soup-cli[train,serve]==$soupVersion"
if ($LASTEXITCODE -ne 0) { throw 'Soup installation failed.' }
& ./.venv/Scripts/soup.exe --help
& ./.venv/Scripts/soup.exe doctor
if ($LASTEXITCODE -ne 0) { throw 'Resolve environment issues before training.' }
& ./.venv/Scripts/python.exe -m pip freeze | Set-Content -Encoding utf8 environment.txt
```

In Linux/WSL2 use `python3.11 -m venv .venv`, `.venv/bin/python`, and
`.venv/bin/soup` in place of the Windows executables. Keep the experiment on the
filesystem of the training environment. Do not install into HARQIS's `.venv`.

`soup doctor` checks the environment, not the quality of a dataset or fitness of
a model. The small model ID in the YAML is a smoke-test candidate, not a
recommended production model. Verify its availability and license, and record
its resolved base/tokenizer revision before a real experiment.

## 3. Train the synthetic smoke example

Inspect [soup.smoke.yaml](../examples/soup-hfl/soup.smoke.yaml). Its keys follow
the upstream [configuration reference](https://trysoup.dev/docs/configuration).
Paths are relative to the experiment working directory. The configuration uses
all three rows for a single training epoch with no validation split; it must
never be used to report accuracy or a promotion verdict.

```powershell
& ./.venv/Scripts/soup.exe train --help
& ./.venv/Scripts/soup.exe train --config ./soup.smoke.yaml
if ($LASTEXITCODE -ne 0) { throw 'Training failed; inspect the error before continuing.' }
```

Expected result: Soup writes model/adapter artifacts under `./output`. Actual
runtime, VRAM use, and output quality are unmeasured. Do not assume a tiny smoke
dataset teaches reliable HFL behavior. If the version rejects a key, compare
local help and the version's schema; do not silently drop validation controls
from a real experiment to make a run succeed.

For a real run, prepare reviewed training/development/test partitions first.
Use the installed release's supported explicit validation-dataset mechanism
instead of randomly splitting related events. Configure training only with
training/development data; keep the final test set outside that configuration.
Record seed, package versions, hardware, dataset hashes, prompt hash, base
revision, tokenizer revision, and final adapter digest alongside each run.

## 4. Serve and issue a read-only request

From the experiment directory, start Soup in one terminal:

```powershell
& ./.venv/Scripts/soup.exe serve --help
& ./.venv/Scripts/soup.exe serve --model ./output --host 127.0.0.1 --port 8000
```

Keep it bound to loopback for this experiment. Use a separate serving environment
if moving to vLLM, as upstream documents dependency conflicts with training.
HARQIS would use inference routes only; it does not need Soup's tool-execution
routes. See [serving documentation](https://trysoup.dev/docs/serving).

In a second PowerShell terminal, change to the experiment directory printed or
created in step 2, then run:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health'
$soupModels = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/v1/models'
$soupModels.data | Select-Object id
```

Select the exact candidate ID from that response. Do not assume it matches the
Hugging Face base ID or the directory name:

```powershell
$soupCandidateId = '<model-id-from-the-response>'
if ($soupCandidateId.StartsWith('<')) { throw 'Select the served candidate model ID first.' }
$soupRequest = Get-Content -LiteralPath ./request.synthetic.json -Raw | ConvertFrom-Json
$soupRequest.model = $soupCandidateId
$soupResponse = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/chat/completions' -ContentType 'application/json' -Body ($soupRequest | ConvertTo-Json -Depth 10) -TimeoutSec 60
if ($soupResponse.choices[0].finish_reason -eq 'length') { throw 'Truncated output: reject the candidate response.' }
$soupResponse.choices[0].message.content
```

Inspect the result against the source text and six-field contract. Successful
HTTP transport is not proof of valid JSON, correct types, or factuality. The
request has no corpus-write endpoint and cannot save an HFL entry. Stop the
foreground server with Ctrl+C when finished.

## 5. Evaluate a real candidate

There is no HARQIS evaluator command in this PR. The implementation should
produce one row per source window and model arm, with these columns:

```text
example_id, split, model_digest, prompt_hash, valid_schema,
human_meaningful, predicted_skip, unsupported_fact_count,
usable_without_substantive_edit, latency_ms, input_tokens,
output_tokens, fallback_reason, estimated_cost
```

Keep source text and outputs in private linked artifacts. Review the current
provider, prompted base, and tuned model blind against the same evidence.
Report sample sizes and failures, including failures hidden by fallback.

Use the [thesis gates](../thesis/SOUP-HFL-MODEL-TRAINING.md#7-evaluation-and-adoption-criteria)
and fill this report without substituting invented measurements:

| Measure | Existing provider | Prompted base | Tuned model |
| --- | --- | --- | --- |
| Reviewed windows | Not measured | Not measured | Not measured |
| Valid output before fallback | Not measured | Not measured | Not measured |
| False skips / meaningful windows | Not measured | Not measured | Not measured |
| Critical unsupported facts | Not measured | Not measured | Not measured |
| Usable without substantive edits | Not measured | Not measured | Not measured |
| p50 / p95 latency | Not measured | Not measured | Not measured |
| Total cost including operations | Not measured | Not measured | Not measured |

Training loss or a successful Soup run alone cannot approve deployment.

## 6. Future HARQIS use and rollback

After the provider/evaluator implementation lands, the intended operator flow is:

1. Preserve baseline routing and record its quality and cost.
2. Select an immutable candidate and run write-free shadow comparisons.
3. Review the comparison report and register a promotion decision.
4. Enable a bounded local canary with deterministic fallback and fixed deadlines.
5. Roll back to baseline on regression; keep the original write identity so
   switching models does not duplicate an entry.

These are future behaviors, not commands or environment variables available
today. The first code PR should provide their exact configuration and operations
interface. This documentation PR does not install Soup, export private data,
train a model, change a schedule, or deploy an endpoint.
