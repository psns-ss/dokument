# logic/sticker.py
"""
Sticker showcase plugin: file-count limit + SVG insertion.

Two hooks, discovered independently per category:
  - init_sticker()    (type=file)    -> a <multiple> file input whose batch size
                        is capped by the `file:<N>` descr option. The cap is the
                        showcased "limit how many files to upload" feature. No
                        content filtering here — rogue files are allowed in.
  - compute_sticker() (type=computed) -> factory: content-sniffs the uploads for
                        real SVGs, drops the rest, converts up to
                        STICKER_CAPACITY to PNG, and returns {'sticker': <deferred
                        assembler>} that splices them side-by-side into the
                        {{p sticker}} slot.

Note: the init hook's cap is descr-driven only once the parser's `file` options
consumer parses `file:<N>` into options['file']; until then the input is uncapped.
"""
import io
import logging
from pathlib import Path

from docx import Document
from session_manager import get_file

logger = logging.getLogger(__name__)

STICKER_VAR = 'sticker'
STICKER_CAPACITY = 2  # the template lays two stickers out side-by-side

# JS injected by init_sticker(): cap the selected batch at __LIMIT__ files.
# A plain template (not an f-string) so the JS braces stay literal.
_LIMIT_JS = """
<script>
(function () {
    var el = document.getElementById('sticker');
    if (!el) return;
    el.addEventListener('change', function () {
        if (el.files.length > __LIMIT__) {
            alert('Можно загрузить не более __LIMIT__ файлов');
            el.value = '';
        }
    });
})();
</script>
"""


def _is_svg(path):
    """Content-sniff (not the extension): does the file look like an SVG?

    Reads the first 4 KB and looks for a <svg element or an <?xml prolog. A false
    positive is harmless — cairosvg's conversion is the real gate and drops
    anything that isn't a valid SVG.
    """
    try:
        with open(path, 'rb') as f:
            head = f.read(4096)
    except OSError:
        return False
    return b'<svg' in head or head.lstrip().startswith(b'<?xml')


def init_sticker(session, matched_list, variable_desc=None):
    """File upload UI for the `sticker` var (type=file).

    matched_list is always [] for a file-only var (enriched in POST /init).
    The upload cap comes from the `file:<N>` descr option (options['file']); when
    it's absent the input is rendered uncapped (no JS). No content filtering —
    the user may upload non-SVGs; compute_sticker() sorts those out.
    """
    if get_file(session, STICKER_VAR):
        return ''  # files already uploaded -> silence (hash convergence)

    limit = None
    if variable_desc:
        options = (variable_desc.get(STICKER_VAR) or {}).get('options') or {}
        value = options.get('file')
        if value is not None:
            try:
                n = int(value)
                limit = n if n > 0 else None
            except (TypeError, ValueError):
                limit = None

    if limit is not None:
        label = f'Наклейки (SVG, до {limit} шт.):'
        js = _LIMIT_JS.replace('__LIMIT__', str(limit))
    else:
        label = 'Наклейки (SVG):'
        js = ''

    return f'''
    <div class="form-group">
        <label for="sticker">{label}</label><br>
        <input type="file" name="sticker" multiple id="sticker">
        {js}
    </div>
    '''


def compute_sticker(**kwargs):
    """Factory: return {'sticker': <deferred assembler>} for the uploads.

    Session arrives via **kwargs from compute_variables(). Reads the uploaded
    files, content-sniffs for real SVGs (drops the rest), converts up to
    STICKER_CAPACITY to PNG at compute time (captured in the closure), and defers
    the donor assembly to render time. No renderable SVGs -> {} so the
    {{p sticker}} slot renders empty.
    """
    session = kwargs.get('session')
    paths = get_file(session, STICKER_VAR) if session else []
    if not paths:
        return {}

    svgs = []
    for path in paths:
        if _is_svg(path):
            svgs.append(path)
        else:
            logger.info('sticker: skipping non-SVG upload %s', Path(path).name)
    svgs = svgs[:STICKER_CAPACITY]
    if not svgs:
        return {}

    try:
        import cairosvg
    except ImportError:
        logger.error('sticker: cairosvg not installed — cannot convert SVGs')
        return {}

    pngs = []
    for path in svgs:
        try:
            pngs.append(cairosvg.svg2png(url=str(path)))  # natural size
        except Exception as e:
            logger.error('sticker: SVG->PNG failed for %s: %s', Path(path).name, e)
    if not pngs:
        return {}

    def _assemble(tpl, **ctx):
        donor = Document()
        paragraph = donor.add_paragraph()
        for png in pngs:
            paragraph.add_run().add_picture(io.BytesIO(png))  # natural size
        buf = io.BytesIO()
        donor.save(buf)
        buf.seek(0)
        return tpl.new_subdoc(buf)

    return {STICKER_VAR: _assemble}
