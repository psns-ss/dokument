"""
Tests for logic/appeal.py

This module computes the appropriate appeal (formal address) based on sex.
"""

import pytest
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from logic.appeal import compute_appeal


class TestComputeAppeal:
    """Tests for the compute_appeal function."""

    def test_compute_appeal_male(self):
        """Test appeal computation for male sex."""
        result = compute_appeal("Мужской")
        assert result == "ый"

    def test_compute_appeal_female(self):
        """Test appeal computation for female sex."""
        result = compute_appeal("Женский")
        assert result == "ая"

    def test_compute_appeal_unknown_sex(self):
        """Test appeal computation for unknown sex defaults to male."""
        result = compute_appeal("Не указан")
        assert result == "ый"
