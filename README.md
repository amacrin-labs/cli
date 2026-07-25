# Amacrin CLI

Deploy and manage [Open Scientific Archive](https://github.com/opensciencearchive/osa-py)
instances on the Amacrin cloud platform — provision a managed archive, build and
register your conventions, and start ingestion runs, without running your own
infrastructure.

## Install

```bash
pip install amacrin
```

## Quickstart

### 1. Sign in

```bash
amacrin login
```

This opens your browser to sign in. On first sign-in Amacrin creates your
account and a **Personal** organisation to hold your archives. Tokens are saved
to `~/.config/amacrin/credentials.json` and refreshed automatically — no need to
paste tokens by hand.

### 2. Describe your archive

```bash
amacrin init
```

`init` scaffolds two files. **`osa.yaml`** is your OSA server's own config — it
runs identically locally, self-hosted, or in the cloud, so it carries no cloud
settings:

```yaml
name: My Lab Archive
auth:
  providers:
    orcid:
      client_id: ${ORCID_CLIENT_ID}
      client_secret: ${ORCID_CLIENT_SECRET}
  admins:
    orcid:
      - "0000-0002-1234-5678"
```

**`amacrin.yaml`** is the deploy manifest — how Amacrin provisions the archive.
It owns the `slug` (the `<slug>.amacr.in` subdomain) and points at the server
config to ship. The OSA server never reads this file:

```yaml
slug: my-lab          # your archive is served at my-lab.amacr.in
config: osa.yaml      # the server config to ship
```

`${VAR}` references in either file are resolved from a local `.env` and the
environment (the environment wins), so secrets stay out of the files:

```bash
# .env
ORCID_CLIENT_ID=APP-XXXXXXXX
ORCID_CLIENT_SECRET=super-secret
```

### 3. Provision it

```bash
amacrin archive create
```

This provisions the archive and deploys the server, streaming live progress and
ending with your archive URL (e.g. `https://my-lab.amacr.in`). The archive ID is
written to `.amacrin/archive-id` so the rest of the commands know which archive
this project is bound to.

### 4. Deploy your conventions

```bash
amacrin deploy
```

Builds your convention OCI images and registers them with the running archive.
Deploy never provisions — it targets the archive already linked to this project.

### 5. Ingest data

```bash
amacrin ingest start --convention <slug>
```

Starts an ingestion run for a convention, identified by its slug — shown by
`amacrin deploy` when the convention is registered.

## Command reference

| Command | What it does |
| --- | --- |
| `amacrin init` | Scaffold `osa.yaml` (server config) + `amacrin.yaml` (deploy manifest). |
| `amacrin login` | Sign in via the browser (creates your account + Personal org on first use). |
| `amacrin logout` | Revoke and remove stored credentials. |
| `amacrin whoami` | Show the signed-in user and organisations. |
| `amacrin org list` | List your organisations. |
| `amacrin org create <name>` | Create a new organisation. |
| `amacrin link --archive <id>` | Bind this project to an existing archive. |
| `amacrin archive create` | Provision and deploy a new archive (live progress). |
| `amacrin archive list` | List archives you can access. |
| `amacrin archive status` | Show the linked archive's deployment status and URL. |
| `amacrin archive destroy` | Tear down the linked archive. |
| `amacrin deploy` | Build convention images and register them with the linked archive. |
| `amacrin ingest start` | Start an ingestion run for a convention. |

## Authentication notes

- **Credentials** live in `~/.config/amacrin/credentials.json` (created with
  `0600` permissions), keyed by control-plane URL. Access tokens are refreshed
  transparently, so you rarely re-run `amacrin login`.
- **CI / non-interactive** — set `AMACRIN_TOKEN` to a token and the CLI uses it
  directly (no browser, no refresh). Provide a fresh token when it expires.
- **Admin escape hatch** — pass `--token <token>` to a command to override the
  stored credential for that invocation.
- **Targeting another control plane** — set `AMACRIN_API` (e.g. a staging
  deployment) to point every command at a different API base. Credentials are
  stored per API base, so multiple environments coexist.
