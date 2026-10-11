# app/session_manager.py
# -----------------------
# Session state management for Flask routes.
# Encapsulates all session access to keep routes thin and testable.

from pathlib import Path
from typing import Any, List


def get_file(session: dict, var_name: str) -> List[str]:
    """Standalone: get uploaded file paths for a variable (for use in plugins).

    Plugins receive the session dict, not a SessionManager instance.
    Import this function directly: from session_manager import get_file

    Returns a copy — a plugin mutating the result must not corrupt the
    session's stored list.
    """
    return list(session.get('uploaded_files', {}).get(var_name, []))


class SessionManager:
    """Wrapper around Flask session for type-safe state management."""

    def __init__(self, session: dict[str, Any]):
        """Initialize with Flask session dict."""
        self.session = session

    def _unlink_uploaded_files(self) -> None:
        """Best-effort delete of all uploaded files from disk.

        Called before clearing the session's uploaded_files references so the
        files don't linger on disk after a nuke. Never raises — a failed unlink
        (already gone, locked, permission) is logged-and-skipped.
        """
        for paths in self.session.get('uploaded_files', {}).values():
            for path in paths:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass  # Best-effort cleanup

    def clear_for_init(self) -> None:
        """Clear all per-run session data when user restarts (GET /init).

        Nuke-everything approach: preserve only pack identity and session
        folder ID, clear the rest. Called on GET /init only (user clicks
        the "Return to the form" button on ready.html).

        Preserved keys:
          - active_pack: user stays in the same pack
          - session_id: file paths on disk remain valid for this session

        Cleared:
          - uploaded_files: new upload cycle starts fresh
          - form data: user starts with empty form
        """
        # Delete old uploaded files from disk before clearing references.
        self._unlink_uploaded_files()

        keep = {'active_pack', 'session_id'}
        for key in set(self.session.keys()) - keep:
            self.session.pop(key)

    def save_form_data(self, form_data: dict[str, str]) -> None:
        """Save user-provided form values to session.

        Skips the system keys (the same set get_form_data excludes) so a forged
        form field can't overwrite session_id / uploaded_files / active_pack /
        ui_hash — the spots that read the session directly, bypassing get_form_data.
        """
        system_keys = {'uploaded_files', 'active_pack', 'session_id', 'ui_hash'}
        for key, value in form_data.items():
            if key not in system_keys:
                self.session[key] = value

    def get_form_data(self) -> dict[str, Any]:
        """Get user-provided form values (scalars + inflected dicts).

        Excludes system keys managed by SessionManager.
        """
        system_keys = {
            'uploaded_files',      # file paths
            'active_pack',         # pack identity
            'session_id',          # session folder UUID
            'ui_hash',             # convergence guard
        }
        return {
            k: v for k, v in self.session.items()
            if k not in system_keys
        }

    def clear_for_pack_switch(self) -> None:
        """Clear ALL session data when switching to a different pack.

        Nuke-everything approach: preserve only active_pack, clear the rest.
        Pack switch = new world. No data from old pack is relevant.

        NOT preserved:
          - session_id: old pack's files belong to old pack
          - uploaded_files: pack-specific, cleared (files unlinked from disk)
        """
        # Delete uploaded files from disk before clearing references.
        self._unlink_uploaded_files()

        keep = {'active_pack'}
        for key in set(self.session.keys()) - keep:
            self.session.pop(key)
