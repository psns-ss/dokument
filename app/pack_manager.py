# app/pack_manager.py
"""
Pack discovery and validation for multi-template-pack support.

Discovers all template packs under templates/, extracts descriptions,
and validates pack integrity.
"""
from pathlib import Path
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


def discover_packs(templates_dir: Path) -> list[dict]:
    """
    Discover all template packs under templates/.

    Finds all descr.docx files:
    - Root level: templates/descr.docx (identifier = 'root')
    - Subdirs: templates/<name>/descr.docx (identifier = subdir name)

    Behavior for inaccessible packs:
    - descr.docx missing: skip silently, log info
    - descr.docx unreadable (permission): show as disabled with error
    - Folder unreadable: skip silently (can't discover)

    Returns:
        List of dicts with keys:
        - 'identifier': str ('root' or subdir name)
        - 'base_dir': Path (directory containing descr.docx)
        - 'descr_path': Path (full path to descr.docx)
        - 'description': str or None (extracted description, or None if disabled)
        - 'desc_hash': int or None (case-insensitive hash for duplicate detection)
        - 'is_duplicate': bool (True if description matches another pack)
        - 'error': str or None (error message if disabled)
        - 'is_disabled': bool (True if pack should appear greyed out in UI)
        - 'template_count': int (number of template*.docx files in pack)
    """
    from logic.parser import extract_pack_description, NO_DESCRIPTION

    if not templates_dir.is_dir():
        return []  # no templates dir → no packs (avoids iterdir() raising)

    packs = []
    desc_hashes = defaultdict(list)

    # Root level descr.docx
    root_descr = templates_dir / 'descr.docx'
    try:
        if not root_descr.exists():
            logger.info("Root descr.docx not found — no root pack available")
        else:
            desc = extract_pack_description(root_descr)
            desc_hash = hash(desc.lower()) if desc != NO_DESCRIPTION else None
            template_count = len(list(templates_dir.glob('template*.docx')))

            packs.append({
                'identifier': 'root',
                'base_dir': templates_dir,
                'descr_path': root_descr,
                'description': desc,
                'desc_hash': desc_hash,
                'is_duplicate': False,
                'error': None,
                'is_disabled': False,
                'template_count': template_count,
            })
            desc_hashes[desc_hash].append('root')
    except PermissionError:
        packs.append({
            'identifier': 'root',
            'base_dir': templates_dir,
            'descr_path': root_descr,
            'description': None,
            'desc_hash': None,
            'is_duplicate': False,
            'error': 'Permission denied',
            'is_disabled': True,
            'template_count': 0,
        })
    except Exception as e:
        packs.append({
            'identifier': 'root',
            'base_dir': templates_dir,
            'descr_path': root_descr,
            'description': None,
            'desc_hash': None,
            'is_duplicate': False,
            'error': str(e),
            'is_disabled': True,
            'template_count': 0,
        })

    # Subdirectory descr.docx files
    for subdir in sorted(templates_dir.iterdir()):
        if not subdir.is_dir():
            continue

        # Skip known non-pack directories. 'root' is reserved for the top-level
        # pack (templates/ itself) — a templates/root/ subdir would otherwise
        # collide with the root pack's identifier.
        if subdir.name in ('logic', '__pycache__', 'root'):
            continue

        descr_path = subdir / 'descr.docx'

        # Check if descr.docx exists
        try:
            if not descr_path.exists():
                logger.info(f"Skipping pack '{subdir.name}': no descr.docx")
                continue  # Silent skip
        except PermissionError:
            # Can't even stat the file - folder or file unreadable
            packs.append({
                'identifier': subdir.name,
                'base_dir': subdir,
                'descr_path': descr_path,
                'description': None,
                'desc_hash': None,
                'is_duplicate': False,
                'error': 'Permission denied',
                'is_disabled': True,
                'template_count': 0,
            })
            continue

        # File exists, try to read it
        try:
            desc = extract_pack_description(descr_path)
            desc_hash = hash(desc.lower()) if desc != NO_DESCRIPTION else None
            template_count = len(list(subdir.glob('template*.docx')))

            packs.append({
                'identifier': subdir.name,
                'base_dir': subdir,
                'descr_path': descr_path,
                'description': desc,
                'desc_hash': desc_hash,
                'is_duplicate': False,
                'error': None,
                'is_disabled': False,
                'template_count': template_count,
            })
            desc_hashes[desc_hash].append(subdir.name)
        except PermissionError:
            # File exists but unreadable - show as disabled
            packs.append({
                'identifier': subdir.name,
                'base_dir': subdir,
                'descr_path': descr_path,
                'description': None,
                'desc_hash': None,
                'is_duplicate': False,
                'error': 'Permission denied',
                'is_disabled': True,
                'template_count': 0,
            })
        except Exception as e:
            packs.append({
                'identifier': subdir.name,
                'base_dir': subdir,
                'descr_path': descr_path,
                'description': None,
                'desc_hash': None,
                'is_duplicate': False,
                'error': str(e),
                'is_disabled': True,
                'template_count': 0,
            })

    # Mark duplicates
    for pack in packs:
        if pack['desc_hash'] is not None:
            pack['is_duplicate'] = len(desc_hashes[pack['desc_hash']]) > 1

    # Order is set by construction: root first, then subdirs in sorted() order
    # (the iterdir loop above) — no final sort needed.
    return packs


def validate_pack(templates_dir: Path, identifier: str) -> tuple[bool, str | None]:
    """
    Check that a pack's descr.docx exists.

    Existence only — the "is it a valid docx" open now happens in the route's
    single read_variable_descriptions() call. (This used to also open the docx
    via extract_pack_description and discard the result — a redundant per-
    request parse; the /select descriptions come from discover_packs instead.)
    A corrupt docx degrades in read_variable_descriptions (degrade-and-log)
    rather than failing here.

    Returns:
        (True, None) if descr.docx exists
        (False, error_message) if the pack is missing
    """
    if identifier == 'root':
        descr_path = templates_dir / 'descr.docx'
    else:
        descr_path = templates_dir / identifier / 'descr.docx'

    if not descr_path.exists():
        return False, f"Pack not found: {descr_path}"
    return True, None


def resolve_pack_paths(templates_dir: Path, identifier: str) -> tuple[Path, Path]:
    """
    Resolve (descr_path, lang_rules_path) for a pack identifier.

    Pure path resolution — thread-safe, no cfg mutation (used by select.py
    and debug.py). Language rules fall back to the root file when the pack
    has none of its own.
    """
    if identifier == 'root':
        descr = templates_dir / 'descr.docx'
        lang = templates_dir / 'language_rules.yaml'
    else:
        descr = templates_dir / identifier / 'descr.docx'
        lang = templates_dir / identifier / 'language_rules.yaml'
        if not lang.exists():
            lang = templates_dir / 'language_rules.yaml'  # fallback to root
    return descr, lang


def resolve_pack_dirs(templates_dir: Path, identifier: str) -> tuple[Path, Path]:
    """
    Resolve (pack_dir, logic_dir) for a pack identifier.

    Pure path resolution — thread-safe, no cfg mutation. pack_dir is where the
    pack's templates live; logic_dir is the pack's logic/ if present, else the
    root logic/ (mirrors the old `cfg.logic_dir or root` fallback).
    """
    pack_dir = templates_dir if identifier == 'root' else templates_dir / identifier
    pack_logic = pack_dir / 'logic'
    logic_dir = pack_logic if pack_logic.exists() else templates_dir / 'logic'
    return pack_dir, logic_dir
