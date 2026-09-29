# Synthetic Soup HFL examples

These assets support the [usage guide](../../info/SOUP-HFL-PILOT-GUIDE.md) and
[implementation thesis](../../thesis/SOUP-HFL-MODEL-TRAINING.md).

| File | Purpose |
| --- | --- |
| [train.synthetic.jsonl](train.synthetic.jsonl) | Three fictional ChatML training pairs; format demonstration only |
| [request.synthetic.json](request.synthetic.json) | Separate fictional inference request; replace its model ID with the served ID |
| [soup.smoke.yaml](soup.smoke.yaml) | One-epoch isolated smoke configuration; no validation or quality claim |

All repository names, commits, and outcomes in these files are fictional. They
contain no exports from the user's corpus. Copy the files outside the checkout
before running the guide, so model artifacts and later private datasets stay
out of Git. The short system prompt illustrates the contract; a real experiment
must freeze and reuse the repository's full Git distillation prompt.

The configuration follows documented Soup keys but has not been executed against
a training backend. JSON/JSONL syntax and relative file links are checked in this
documentation change. Hardware compatibility and model quality remain untested.
