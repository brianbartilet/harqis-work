# Security and public releases

[Overview](../../README.md) · [Setup](SETUP.md) · [Host deployment](HERMES-HOST.md)

Publishing source and exposing running services are separate decisions. This
project handles personal records and can perform actions through connected
accounts. Configure only the access and integrations you need.

## Keep private data out of releases

Store credentials in ignored `.env` files and machine-specific settings in
`machines.local.toml` or `fork-fleet.local.toml`. Activity records, agent state,
captured media, logs, and databases belong in local runtime directories.

Git ignore rules do **not** protect Docker builds. The root `.dockerignore`
excludes host configuration, `.harqis-data`, agent settings/state, temporary
checkouts, output directories, databases, and virtual-environment backups.
Review new runtime locations against both ignore files. Inspect an image's
contents before distributing it; rebuilding does not erase an older image.
If a previously shared image contains credentials, revoke or rotate them.

## Network access

Published Docker ports now default to `127.0.0.1`. Container-to-container
connections still use Docker service names. This change does not add
authentication: Redis, Elasticsearch, and the supplied anonymous MQTT broker
must remain inside a trusted boundary.

**Migration for existing installations:** before the next Compose recreation,
identify services used by remote workers or devices. Set only their bind
addresses to the host's private/VPN interface, and restrict clients with firewall
or VPN ACLs. Leaving the defaults will intentionally stop remote connections.
Do not use a public interface or `0.0.0.0` as a convenience workaround.

| Setting | Service / existing port setting |
|---|---|
| `RABBITMQ_BIND_ADDRESS` | Broker / `RABBITMQ_PORT` |
| `RABBITMQ_MANAGEMENT_BIND_ADDRESS` | Broker management / `RABBITMQ_MANAGEMENT_PORT` |
| `REDIS_BIND_ADDRESS` | Task results / `REDIS_PORT` |
| `MQTT_BIND_ADDRESS` | OwnTracks MQTT / `MQTT_PORT` |
| `OWNTRACKS_BIND_ADDRESS` | Location recorder / `OWNTRACKS_PORT` |
| `N8N_BIND_ADDRESS` | Automation editor / `HOST_PORT_N8N` |
| `ELASTICSEARCH_BIND_ADDRESS` | Search and logs / `ELASTICSEARCH_PORT` |
| `KIBANA_BIND_ADDRESS` | Search administration / `KIBANA_PORT` |
| `FLOWER_BIND_ADDRESS` | Task monitoring / `FLOWER_PORT` |
| `NGROK_INSPECT_BIND_ADDRESS` | Tunnel inspection / `NGROK_INSPECT_PORT` |

Set these in the host's ignored environment/machine configuration when using
`scripts/deploy.py`. Direct `docker compose` invocations must receive the same
environment explicitly; Compose does not automatically read `.env/apps.env`.
Use a stable private address available when Docker starts.

Before broadening access, configure authentication and encrypted transport as
appropriate: dedicated RabbitMQ credentials, Redis ACLs, Elasticsearch security,
and MQTT credentials/ACLs. The supplied OwnTracks recorder uses blank MQTT
credentials, so update its client configuration together with the broker.
Keep administrative interfaces local unless there is a concrete need.

These defaults cover **Docker port publication only**. The Python frontend,
corpus API, and command runner have their own listeners and authentication.
Protect their origins with firewall rules. Public tunnels still reach services
inside the Docker network; loopback bindings do not disable those tunnels.
Use HTTPS, secure cookies, and authenticated/restricted ingress for public access.

## Dependencies and remaining blockers

`requirements.txt` and `frontend/requirements.txt` include
[`constraints-security.txt`](../../constraints-security.txt), which sets minimum
versions for reviewed vulnerable transitive packages without installing unused
packages. Direct requirements also raise the cryptography, filelock, pytest,
and pypdf floors. Constraints are security minimums, not a reproducible lock.

The November 2026 review found that the pinned `harqis-core` commit requires
`Pillow<13` and `paramiko<4`. The patched versions reported by the advisory
database require Pillow 13 and Paramiko 5. Installing those versions while
ignoring core's metadata would produce an inconsistent environment.

**These two upstream blockers remain open.** Update and validate harqis-core's
dependency ranges, publish a reviewed core commit, then update this repository's
Git pin and the frontend Pillow range. Re-resolve and re-audit the entire graph.
Until then, treat untrusted image processing and SSH-related use as requiring
additional review. Do not describe this release as vulnerability-free.

Compared with the original Windows environment (148 records across 18 packages),
fresh Windows and Linux resolutions each report 44 records in Pillow and Paramiko.
These are different environment resolutions, not an exploit count or a guarantee
for other hosts. Some advisory records repeat IDs. Consult current audit results
rather than treating these figures as permanent.

## Automated checks

The [security workflow](../../.github/workflows/security.yml) runs on main pushes,
pull requests, weekly schedules, and manual dispatch:

- Gitleaks scans fetched Git history. Narrow file-and-content exceptions in
  `.gitleaks.toml` cover reviewed fixtures, prose, and vendored JavaScript matches.
- npm audit checks the package graph and fails on moderate or higher findings.
- Python requirements are freshly resolved and audited using separate tooling.
  The JSON report is retained as an artifact. **Python advisory failures are
  currently non-blocking**, with an explicit warning, because of the core
  blockers above. Resolution and missing-report failures still fail the job.
  Remove this advisory exception once the upstream blockers are resolved.

Dependabot proposes weekly dependency and action updates. Third-party GitHub
actions are pinned to reviewed commit IDs. Repository administrators should also
enable secret scanning and push protection where available.

## Publication checklist

1. Inspect the exact tracked snapshot and every branch/tag intended for release.
   Scan history too when retaining it; a fresh source export does not publish old commits.
2. Review documents and examples for private records, client information, internal
   topology, and third-party redistribution rights. Secret scanners cannot certify these.
3. Inspect Docker build contexts and images separately from Git contents.
4. Resolve dependencies, audit them, run relevant regression tests, and record
   remaining advisories. Audit container images and vendored browser assets separately.
5. Review network bindings and public tunnels before deployment.
6. If a real credential is found, revoke/rotate it first and then remove it from
   the release/history. Deleting its current file alone does not remove history.

The repository review used [Gitleaks](https://github.com/gitleaks/gitleaks),
[pip-audit](https://pypi.org/project/pip-audit/), npm audit, and Python static
analysis. It did not establish full privacy clearance or constitute a penetration test.
