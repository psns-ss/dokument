"""
The init form's dynamic-UI block: generation, checksumming, post-hash render.

init_* hooks return Jinja *template* strings (session values as
``{{ session.get(...) }}`` placeholders, not baked in). This module owns the
dynamic-UI block the /init route drives — the part of the init form built from
init_* hooks (not the whole form):

  1. **generate** — fire init_* hooks, join their unrendered fragments.
  2. **checksum** — sha256 of the *unrendered* template (stable: no user input).
  3. **render** — fill the session placeholders post-hash (prerender for display).

The invariant that makes pre-population work lives here: hash the *unrendered*
template, render *strictly after* the hash guard. A fresh pick therefore can't
move the hash (kills the extra init click), and a structure-change re-render
refills picks from the session (no value-loss). The route carries the hash in a
hidden form field (not the session) so it travels with the page.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from flask import current_app

from logic.loader import load_plugins

logger = logging.getLogger(__name__)


@dataclass
class DynamicUIBlock:
    """The assembled dynamic-UI block for one /init render — part of the init
    form, not the whole thing. Holds the unrendered hook template and its
    stable hash, with a lazy post-hash render."""
    template: str      # joined unrendered hook fragments ("" if no init hooks)
    ui_hash: str       # sha256 of `template` — stable across a fresh pick
    rendered: str = "" # post-hash output, filled lazily by render()

    def is_empty(self) -> bool:
        return not self.template.strip()

    @classmethod
    def empty(cls) -> "DynamicUIBlock":
        """A block with no dynamic UI (used when generation is skipped/fails)."""
        return cls(template="", ui_hash=dynamic_ui_hash(""))

    def render(self, session) -> str:
        """Fill the session placeholders post-hash. Lazy — the auto-submit path
        never needs the rendered output."""
        if not self.rendered:
            self.rendered = render_dynamic_ui_block(self.template, session)
        return self.rendered


def generate_dynamic_ui_block(
    matched_entities: Dict[str, List[str]],
    session: Dict[str, Any],
    logic_dir: Path,
    variable_desc: Dict[str, Dict] = None,
) -> str:
    """
    Fire init_* hooks and join their unrendered fragments. Returns the block's
    unrendered template ("" if there's nothing to render).

    After in-place enrichment, matched_entities carries both match results
    (from run_matching()) and empty-list entries for vars_need_init_form
    (from hints). This function iterates all keys and fires init_<var>() hooks —
    it doesn't care which source populated them.

    Args:
        matched_entities: Results from run_matching(), enriched with
            vars_need_init_form entries
        session: Flask session
        logic_dir: Directory to load init plugins from
        variable_desc: Optional dict from descr.docx — passed to init hooks
            for metadata access (e.g., table slot discovery)
    """
    if not matched_entities:
        logger.debug("No matched entities to generate UI for")
        return ""

    init_plugins = load_plugins(logic_dir, 'init')
    html_parts = []

    for var_name, matched_list in matched_entities.items():
        func_name = f"init_{var_name}"
        if var_name in init_plugins and hasattr(init_plugins[var_name], func_name):
            try:
                logger.debug(f"Calling {func_name} for UI generation")
                ui_fragment = getattr(init_plugins[var_name], func_name)(
                    session, matched_list, variable_desc
                )
                if ui_fragment:
                    html_parts.append(ui_fragment)
                    # TEMP DIAGNOSTIC — DELETE when no longer needed: per-fragment
                    # hash to pinpoint which init hook's output changes between
                    # hash-guard renders.
                    logger.debug(
                        "UI-fragment %-14s len=%-5d hash=%s",
                        var_name, len(ui_fragment),
                        hashlib.sha256(ui_fragment.encode()).hexdigest()[:16],
                    )
            except Exception as e:
                logger.error(f"Error in init_{var_name}: {e}")
        else:
            logger.debug(f"No {func_name} hook — no dynamic UI for {var_name}")

    return "\n".join(html_parts)


def dynamic_ui_hash(template: str) -> str:
    """sha256 of the UNRENDERED template (stable — carries no user input)."""
    return hashlib.sha256(template.encode()).hexdigest()


def render_dynamic_ui_block(template: str, session) -> str:
    """Render the joined init-hook template with ``session`` in the context.

    Called strictly AFTER the hash guard, so the hash is on the unrendered
    template (stable — no user input). Empty-safe: no block -> ``""``. Uses the
    app's Jinja env; ``from_string`` templates autoescape OFF by Flask default,
    so the HTML structure passes through and hooks escape user-typed values
    explicitly with ``| e``. Only ``session`` is exposed to the template.
    """
    if not template or not template.strip():
        return ""
    return current_app.jinja_env.from_string(template).render(session=session)


def build_dynamic_ui_block(
    matched_entities: Dict[str, List[str]],
    session: Dict[str, Any],
    logic_dir: Path,
    variable_desc: Dict[str, Dict] = None,
) -> DynamicUIBlock:
    """Generate the dynamic-UI block and checksum it.

    Fires the init_* hooks (``generate_dynamic_ui_block``) and hashes the
    unrendered result. The rendered output is computed lazily on
    ``DynamicUIBlock.render()`` — the auto-submit path never needs it.
    """
    template = generate_dynamic_ui_block(matched_entities, session, logic_dir, variable_desc)
    return DynamicUIBlock(template=template, ui_hash=dynamic_ui_hash(template))
