# Agent hooks and the provider proxy

How to use apii with Claude Code and LLM SDKs without sending raw customer
data to a cloud model. The `apii hook` stdin/stdout contract and the
provider proxy are agent-agnostic — for any other agent, fork the wiring
to fit its hook format.

## Security model

Use the layers that fit your risk:

1. **Local anonymizer** — apii detects and replaces PII on your machine or
   inside private infrastructure only.
2. **Agent hooks** — redact tool output before it enters the model
   context, and restore real values when the agent writes back to disk.
3. **Network enforcement** — route model traffic through the local provider
   proxy and block direct egress to providers except from that process.

Hooks are a convenience and audit layer. The hard enforcement boundary is
the proxy plus OS / container / firewall / MDM policy that prevents direct
provider access.

## Claude Code — one command

```bash
pip install "apii[cli,ner]"
apii install-claude-hook        # add --global for every project
```

This creates a local secret + vault under `~/.apii` and wires two hooks:

- **redact-on-read** (`PostToolUse` / `Read`) — Claude only ever sees
  tokens like `PERSON_…`, `IBAN_…`; raw PII never reaches the model.
- **restore-on-write** (`PreToolUse` / `Write`,`Edit`,`MultiEdit`,
  `NotebookEdit`) — files the agent writes come back out with the real
  values spliced in.

Then, in another terminal pane:

```bash
apii watch        # tails the session transcript, shows tokens decoded — locally
```

The chat shows tokens; the watch pane shows the real values on **your**
screen only — they never re-enter the model's context. Run `/hooks` in
Claude Code (or restart) once to activate.

## Manual hook wiring

The `hook` subcommand reads an agent hook-event JSON on stdin and emits the
hook-response JSON for the selected client. It never prints raw detections.

```bash
export APII_SECRET='replace-with-a-long-local-secret'
apii hook --client claude --tenant org-a --vault /private/apii/org-a.vault
```

An example settings file lives in [`docs/integrations/`](integrations/).
Use an absolute path to the `apii` entry point (or `python -m apii hook …`)
and keep `APII_SECRET` in a local secret manager, not a committed file.

### HTTP-hook daemon

Spawning a process per hook event pays a fork plus an engine load each
time. The `daemon` subcommand runs apii once as a long-lived local process
serving `POST /hook` with the same behaviour as the stdin/stdout `hook`:

```bash
apii daemon --client claude --tenant org-a \
  --vault /private/apii/org-a.vault \
  --host 127.0.0.1 --port 8718 --idle-timeout 3600
```

Claude Code's `http` hook type can POST event JSON straight to
`http://127.0.0.1:8718/hook`. For agents that only support command hooks,
`apii hook-client --url http://127.0.0.1:8718/hook` relays stdin to the
daemon. The daemon self-exits after the idle timeout.

## Provider proxy (OpenAI- and Anthropic-compatible)

`apii.server` is a FastAPI app that anonymizes every outbound JSON string
locally, refuses to forward residual raw PII, forwards only the anonymized
payload upstream, then de-anonymizes every returned JSON string before
responding to the local client.

```bash
pip install "apii[proxy]"
export APII_SECRET='replace-with-a-long-local-secret'
export OPENAI_API_KEY='sk-...'        # forwarded with the client's own request

uvicorn "apii.server:build_app" --factory --host 127.0.0.1 --port 8720
```

Routes:

- `POST /v1/messages` (Anthropic Messages API)
- `POST /v1/chat/completions` (OpenAI Chat)
- `POST /v1/responses` (OpenAI Responses)

Point your client at it: set `ANTHROPIC_BASE_URL=http://127.0.0.1:8720` for
Claude Code, or the OpenAI `base_url` for OpenAI SDKs. Override the upstream
targets with `APII_ANTHROPIC_BASE` / `APII_OPENAI_BASE` (e.g. for a private
gateway). Also exposes `POST /v1/detect`, `/v1/anonymize`, `/v1/deanonymize`
for direct use.

Streaming (`stream=true`) is supported: the upstream Server-Sent Event
stream is de-anonymized on the fly, with a per-stream carry buffer that
reassembles any placeholder token split across event boundaries. Only
text-bearing fields are rewritten (Anthropic `text_delta` /
`thinking_delta` / `input_json_delta`, OpenAI `delta.content` and tool-call
arguments); `signature_delta` and other non-text fields pass through
untouched.

```text
Claude Code / SDK
        |  base URL → local proxy
        v
apii provider proxy  ──anonymized request only──>  external LLM provider
        ^                                                   |
        |  restored answer            placeholder response  |
        +───────────────── de-anonymized locally <──────────+
```

## Operational rules

- Treat hook configs as a convenience and audit layer, not the hard
  security perimeter.
- Never store the vault in the repo. Use `/private/apii`, an encrypted
  volume, or another managed local path.
- Do not put `APII_SECRET` in committed files.
- Disable or tightly allowlist network access for agent-spawned commands.
- In high-risk environments, require zero residual detections before egress
  and fail closed on detector errors.
