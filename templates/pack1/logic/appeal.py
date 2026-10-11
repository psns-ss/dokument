#logic/appeal.py
import yaml
from pathlib import Path

def compute_appeal(sex, language='ru', **kwargs):
    """
    Compute the appropriate appeal based on sex

    Args:
        sex: The selected sex ("Мужской" or "Женский")
        language: Language code (default: 'ru')
        **kwargs: Additional unused arguments

    Returns:
        The appropriate appeal string
    """
    # Pack-local language rules first, root as fallback — mirrors cfg.lang_rules
    # without pulling framework code into a demo plugin. __file__-relative on
    # purpose: a CWD-relative "templates/language_rules.yaml" silently reads the
    # ROOT pack from every pack, so a pack's own rules file is never honoured.
    rules_path = Path(__file__).resolve().parent.parent / "language_rules.yaml"
    if not rules_path.is_file():
        rules_path = Path("templates/language_rules.yaml")

    # Load language rules
    with open(rules_path, 'r', encoding='utf-8') as f:
        rules = yaml.safe_load(f)

    # Determine gender from sex
    gender_map = {
        rules['sex_options'][0]: 'male',  # "Мужской"
        rules['sex_options'][1]: 'female'  # "Женский"
    }

    gender = gender_map.get(sex, 'male')  # Default to male if unknown

    try:
        return rules['appeals'][language]['formal'][gender]
    except (KeyError, TypeError):
        # Fallback to default if anything goes wrong
        return rules['appeals']['ru']['formal']['male']
