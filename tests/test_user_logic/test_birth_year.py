"""
Tests for logic/birth_year.py

This module computes the birth year based on the user's age.
"""

import pytest
from datetime import datetime

# Import the module under test
from logic.birth_year import compute_birth_year


class TestComputeBirthYear:
    """Tests for the compute_birth_year function."""

    def test_compute_birth_year_valid(self):
        """Test birth year calculation with valid age."""
        current_year = datetime.now().year
        age = 30
        expected_year = str(current_year - age)

        result = compute_birth_year(age)
        assert result == expected_year

    def test_compute_birth_year_invalid(self):
        """Test that invalid input returns error message."""
        result = compute_birth_year("not_a_number")
        assert result == "Invalid age"

    def test_compute_birth_year_kwargs_ignored(self):
        """Test that **kwargs are accepted but ignored."""
        current_year = datetime.now().year
        age = 40
        expected_year = str(current_year - 40)

        result = compute_birth_year(age, user_name="John", extra_data="test")
        assert result == expected_year
