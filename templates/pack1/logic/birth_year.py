#logic/birth_year.py
from datetime import datetime

#def compute_birth_year(user_age):
#    current_year = datetime.now().year
#    try:
#        age = int(user_age)
#        return str(current_year - age + 1)  # Adding 1 because of the "+1" in the original function
#    except (ValueError, TypeError) as e:
#        print(f"Error computing birth year: {e}")
#        return "ERROR: Invalid age"

def compute_birth_year(user_age, **kwargs):
    try:
        current_year = datetime.now().year # or get dynamically
        age = int(user_age)
        return str(current_year - age)
    except (ValueError, TypeError):
        return "Invalid age"
