# dokument

A Flask-based document generator that relies on python-docx and docxtpl to generate documents from
Word templates. Define the variables in a `descr.docx` (a Word table of
name, type, and visibility), put `{{placeholders}}` in a Word template, and the
app builds a form from them. Fill the form and the generated document opens in
OnlyOffice for editing.

Templates can be grouped into packs. A pack has its own variables, templates
and plugins.

## Quick start

    docker compose up

Builds the webserver image on first run, then starts nginx, the Flask app, and
OnlyOffice. Open http://localhost:5555/init. (The first pull is slow — the
OnlyOffice image is large.) The bundled demo generates a letter from an uploaded
CV; generated files are saved under `data/` and served at `/documents/`.

## How it works

1. Define variables in `descr.docx` — a Word table (the demo pack is a worked
   example):

   | Variable | Description | Show | Type | Options |
   |----------|-------------|------|------|---------|
   | `{{user_name}}` | User name | ✓ | text | |
   | `{{signature}}` | Signature block | ✓ | bool | |

2. Put `{{placeholders}}` in a `template_*.docx`. docxtpl renders them: Jinja2
   syntax plus structural tags (`{%p ... %}`, `{%tr ... %}`, `{%tc ... %}`) and
   `{{p var}}` / `{{r var}}` for paragraph- and run-level substitution. Tag
   reference: [docxtpl docs](https://docxtpl.readthedocs.io/en/latest/).
3. Fill the form at `/init`, generate, and edit the result in OnlyOffice.

### Flow

`descr.docx` is parsed into a variable list, and the Type cells become the list of
hooks to fire. The form is built from that list: plain fields come from the table,
custom fields from `init_<var>` hooks. Submitting saves the uploads, runs
`match_<var>` hooks to look for known entities in them, and runs `init_<var>` hooks
to render the findings as a selection step. Generation runs `compute_<var>` for the
variables the user left empty, then renders every `template_*.docx` in the pack;
subdocuments are resolved during rendering. Output files go to `data/` and open in
OnlyOffice.

Module-by-module detail: [app/logic/FLOW.md](app/logic/FLOW.md).

### Plugins

Plugins are Python files in `logic/`. The file name matches the variable name:
`logic/birth_year.py` for `birth_year`. The variable's **Type** cell decides
which function runs, and the function name follows the type:

| Type | Function | Runs |
|------|----------|------|
| `computed` | `compute_birth_year(**kwargs)` | at generate, while the value is empty |
| `match` | `match_university(session, yaml_key)` | on POST /init, before the form is shown |
| `form`, `file` | `init_cv(session, matched_list)` | while the form is built |
| `subdoc` | `university_historical(tpl, **kwargs)` | at render (no prefix) |

A `match` variable also gets `init_<var>`, without the `form` type; that hook
renders the checkboxes for the matched values. A hook not named in the Type cell
is never called: the list of hooks comes from `descr.docx`, not from the contents
of `logic/`.

Plugin changes need `docker compose restart webserver`. `/debug-vars` shows which
hooks were found. Examples: `logic/*.py` and [templates/DEMO.md](templates/DEMO.md);
function signatures: [logic/CLAUDE.md](logic/CLAUDE.md).

## Stack

    nginx (5555) → Flask/gunicorn (5000) → OnlyOffice (80)

nginx proxies and serves the generated files; Flask is the app; OnlyOffice is
the editor. Document Server runs in its own container, unmodified and not
redistributed, under AGPL-3.0. Community Edition is free and has no user limit;
builds before 9.4 limited editing to 20 simultaneous sessions.

## Development

    python -m venv venv && source venv/Scripts/activate   # Linux/macOS: venv/bin
    pip install -r requirements.txt -r requirements-test.txt
    python -m pytest                                       # E2E self-skips without the container
    python -m pytest tests/test_e2e.py --e2e               # E2E, needs the container on :5555

## Updating

    git pull
    docker compose restart webserver

`app/`, `templates/` and `logic/` are bind-mounted and the image holds only the
dependencies — no code is copied in — so an edit needs just a process restart:

    docker compose restart webserver

Rebuild only when a dependency changes:

    docker compose up -d --build webserver

The mounts are required: without them the container has dependencies, but no
application and no packs. Restart `nginx` after editing `nginx/nginx.conf`.

A restart invalidates active sessions: `SECRET_KEY` is generated at container
start, so cookies issued earlier stop working and users mid-form lose their input.

Releases are not tagged; record the deployed commit (`git log -1 --oneline`).
Versions are set in `requirements.txt` and `docker-compose.yml`, including the
OnlyOffice image.

## Security

Assumes a trusted network. As shipped there is no authentication anywhere:

- `JWT_ENABLED=false` in `docker-compose.yml`, and the app does not sign editor
  configs — enabling JWT in Document Server requires adding signing in Flask first.
- `ALLOW_PRIVATE_IP_ADDRESS` and `ALLOW_META_IP_ADDRESS` are true, so the editor can be
  pointed at internal addresses.
- nginx forwards everything it does not recognize to Document Server, which puts that
  service on the same port as the app.
- Generated documents and their editor pages are served from `/documents/` with no
  authentication. The paths embed a session id, so they are hard to guess rather than
  protected.

Before exposing this beyond a trusted network: sign editor configs and enable JWT on
both sides, stop routing the Document Server through the app's port, and put real
authentication in front of `/documents/`.

## Docs

The `CLAUDE.md` files are the reference (written for AI-assisted development, but
readable as human docs):

- `templates/CLAUDE.md` — variable format
- `templates/DEMO.md` — the demo, all four plugin types
- `logic/CLAUDE.md` — plugins
- `app/logic/CLAUDE.md` — core modules
- `app/routes/CLAUDE.md` — routes

## License

MIT — see [LICENSE](LICENSE).

This project is independent. OnlyOffice and Microsoft Word are trademarks of their
respective owners; the names are used for identification only.
