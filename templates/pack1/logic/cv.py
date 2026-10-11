"""
CV file upload init hook.

Generates file upload UI for the 'cv' type=file variable.
Discovered automatically via vars_need_init_form (type=file vars need init).
"""
from session_manager import get_file


def init_cv(session, matched_list, variable_desc=None):
    """Generate UI for CV file upload.

    Discovered automatically for type=file variables via vars_need_init_form.
    Signature matches framework convention: init_<var>(session, matched_list).
    For file vars, matched_list is always [] (enriched with empty list in POST).

    Behavior:
    - GET /init: uploaded_files['cv'] is empty -> return file input HTML
    - POST /init (after upload): cv_paths has values -> return "" (silence)
      -> init_university() produces UI for matched universities on the POST page
    """
    cv_paths = get_file(session, 'cv')

    # File already uploaded — no UI needed, init_university() handles the POST page
    if cv_paths:
        return ""

    # No file yet — return file input HTML snippet
    return '''
    <div class="form-group">
        <label for="cv">Загрузить резюме (.docx):</label><br>
        <input type="file" name="cv" accept=".docx" id="cv">
    </div>
    '''
