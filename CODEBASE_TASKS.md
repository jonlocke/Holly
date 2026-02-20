# Proposed Maintenance Tasks

## 1) Typo fix task
**Task:** Rename `templates/index.html-cyberpunk` to a conventional template name such as `templates/index-cyberpunk.html` (or `templates/index_cyberpunk.html`) and update any references.

**Why:** The current `index.html-cyberpunk` naming looks like an accidental suffix typo rather than a true extension, making it easy to miss by editors/tooling and inconsistent with Flask template conventions.

**Acceptance criteria:**
- File renamed to a valid `.html` template name.
- Any rendering/lookup references updated.
- App still serves the intended template.

## 2) Bug fix task
**Task:** Prevent the theme toggle from accidentally submitting the chat form.

**Why:** In `templates/index.html`, the theme toggle button is inside `<form>` and has no explicit `type`, so browsers treat it as `submit` by default. Clicking it can trigger form submission unexpectedly.

**Acceptance criteria:**
- Add `type="button"` to `#theme-toggle`.
- Verify toggling theme does not send a message or trigger stream calls.

## 3) Comment/documentation discrepancy task
**Task:** Align CSS comments/sections with the actual DOM structure in `templates/index.html`.

**Why:** `static/style.css` includes a full `/* Header Strip */` section (`.header`, `.header-title`) that is not present in `templates/index.html`, so comments imply a component that does not exist.

**Acceptance criteria:**
- Either add the referenced header markup in HTML, or remove/relocate header-specific CSS and update comments.
- Comments describe only components currently rendered.

## 4) Test improvement task
**Task:** Add automated tests for `/stream` SSE behavior in `main.py`.

**Why:** There are currently no tests, and stream formatting/error semantics are easy to regress.

**Suggested coverage:**
- Success path emits `token` events and a final `done` event.
- Exception path emits an `error` event.
- Response headers include `text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no`.

**Acceptance criteria:**
- New test module using Flask test client + mocked `client.chat`.
- Tests run in CI/local with one command.
