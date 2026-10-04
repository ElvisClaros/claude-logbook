# claude-logbook share server

Serves the sessions published with `claude-logbook -s REF --share`:

| Route | |
| --- | --- |
| `GET /` | Home with the instructions. |
| `GET /share/<id>` | The conversation as a page (the CLI's `template.html`). |
| `GET /share/<id>.txt` | Plain text transcript. |
| `GET /share/<id>.json` | The stored payload. |
| `POST /api/shares` | `{"payload": {...}, "expire": "30d"}` → `201 {id, url, secret, expires}` |
| `PUT /api/shares/<id>` | `Authorization: Bearer <secret>`; replaces the payload. |
| `DELETE /api/shares/<id>` | `Authorization: Bearer <secret>`. |
| `GET /healthz` | `ok`. |

Anyone can create a share; only the holder of the secret returned on
creation can replace or delete it. The server keeps only the secret's SHA-256.

## Security model

- **No HTML is accepted.** The payload is the JSON of `claude-logbook --json -s`;
  it is checked field by field, unknown keys are dropped, memories are refused,
  and the page is built from the template embedded in the binary.
- The data goes inside `<script type="application/json">` with `<`, `>` and `&`
  escaped, and the page is served with a CSP that allows only the template's
  two inline scripts by hash: no inline handlers, no external anything.
- Share ids are 10 base62 characters from `crypto/rand`; pages carry
  `X-Robots-Tag: noindex` and `Referrer-Policy: no-referrer`.
- Images (`--images`) are accepted only as base64 `data:` URLs of PNG, JPEG,
  GIF or WebP whose bytes match the format they claim; SVG never.
- Limits: request body (`MAX_BYTES`), sessions per share (`MAX_SESSIONS`),
  and a token bucket per client IP for creations and for updates/deletes.
- `X-Forwarded-For` is believed only when the connection comes from
  `TRUSTED_PROXY`; otherwise the peer address counts.
- Logs carry method, path, status and size, never bodies or headers.

Content is **not encrypted**: whoever runs the server can read the shares.

## Configuration

| Env | Flag | Default |
| --- | --- | --- |
| `ADDR` | `-addr` | `:8181` |
| `DATA_DIR` | `-data` | `/data` |
| `PUBLIC_URL` | `-public-url` | `https://claude-logbook.all.ar` |
| `MAX_BYTES` | `-max-bytes` | `20971520` (20 MB) |
| `MAX_SESSIONS` | `-max-sessions` | `1` |
| `TRUSTED_PROXY` | `-trusted-proxy` | empty: trust no proxy (IPs or CIDRs, comma separated) |
| `CREATES_PER_HOUR` | `-creates-per-hour` | `10` per IP |
| `WRITES_PER_HOUR` | `-writes-per-hour` | `60` per IP |

Shares expire after `1d`, `7d`, `30d` (default) or `90d`. Expired ones return
404 at once and are deleted by a sweep every hour.

Storage is two files per share in `DATA_DIR` (`<id>.json`, `<id>.meta`), mode
600, written atomically. Back up that directory and you have backed up
everything.

## Build and run

The image is built from the **repository root**, because it embeds
`claude_logbook/template.html`:

```bash
docker build -t claude-logbook-server .
docker run -d --name claude-logbook-server --restart unless-stopped \
  -p 8181:8181 -v claude-logbook-data:/data \
  -e TRUSTED_PROXY=203.0.113.10 \
  claude-logbook-server
```

or with compose:

```yaml
services:
  claude-logbook:
    build: .
    image: claude-logbook-server
    restart: unless-stopped
    ports: ["8181:8181"]   # 127.0.0.1:8181:8181 if NPM runs on this same host
    volumes: ["claude-logbook-data:/data"]
    environment:
      TRUSTED_PROXY: 203.0.113.10   # the address NPM connects from
volumes:
  claude-logbook-data:
```

The image is `FROM scratch`: one static binary, running as `65534:65534`,
with a `HEALTHCHECK` that runs `/server -healthcheck`.

### Nginx Proxy Manager

Add a proxy host `claude-logbook.all.ar` → `<host>:8181`, with an SSL
certificate (Let's Encrypt) and *Force SSL*. Add this under *Advanced* so
uploads up to `MAX_BYTES` get through:

```nginx
client_max_body_size 20m;
```

`TRUSTED_PROXY` must be the address the connections from NPM arrive from.
With NPM on another machine, that is its public IP (`203.0.113.10` above is
only an example), and the firewall should open 8181 to that IP only. If NPM
runs in Docker on the same host, it is its address on the Docker network
(e.g. `172.17.0.0/16`) instead. If it is wrong, every visitor
seems to come from NPM, they all share one rate-limit bucket, and ten shares
an hour from anyone block everyone.

## Development

```bash
cd server
go generate        # copies ../claude_logbook/template.html (git-ignored)
go vet ./... && go test ./...
go run . -data /tmp/shares -public-url http://localhost:8181
CLAUDE_LOGBOOK_SERVER=http://localhost:8181 claude-logbook -s 3 --share
```
