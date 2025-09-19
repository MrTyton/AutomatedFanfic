"""
Test cases for the update mode parameter conversion logic.

This module tests the parameter conversion that was previously handled by
construct_fanficfare_command but is now handled by fanficfare_wrapper.get_update_mode_params.
"""

import unittest
from unittest.mock import Mock

import fanficfare_wrapper


class TestUpdateModeParameterConversion(unittest.TestCase):
    """Test cases for update mode parameter conversion logic."""

    def test_update_method_update(self):
        """Test normal update method."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update", False
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertFalse(update_always)

    def test_update_method_update_always(self):
        """Test update_always method."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_always", False
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertTrue(update_always)

    def test_update_method_force(self):
        """Test force method."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "force", False
        )
        self.assertEqual(update_mode, "force")
        self.assertTrue(force)
        self.assertFalse(update_always)

    def test_fanfic_behavior_force_override(self):
        """Test that force behavior overrides normal update method."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update", True  # Force requested
        )
        self.assertEqual(update_mode, "force")
        self.assertTrue(force)
        self.assertFalse(update_always)

    def test_update_no_force_with_force_behavior(self):
        """Test that update_no_force ignores force requests."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_no_force", True  # Force requested but should be ignored
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)  # Force should be ignored
        self.assertFalse(update_always)

    def test_update_no_force_without_force_behavior(self):
        """Test update_no_force without force request."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_no_force", False
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertFalse(update_always)

    def test_default_update_method_fallback(self):
        """Test that unrecognized update_method defaults to normal update."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "unknown_method", False
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertFalse(update_always)

    def test_force_behavior_precedence_over_update_always(self):
        """Test that force behavior overrides update_always method."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_always", True  # Force requested
        )
        self.assertEqual(update_mode, "force")
        self.assertTrue(force)
        self.assertFalse(update_always)  # Force takes precedence

    def test_update_no_force_precedence_over_force_behavior(self):
        """Test that update_no_force method overrides force behavior."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_no_force", True  # Force requested but ignored
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)  # Force ignored
        self.assertFalse(update_always)

    def test_force_method_with_force_behavior(self):
        """Test force method with force behavior (both should result in force)."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "force", True
        )
        self.assertEqual(update_mode, "force")
        self.assertTrue(force)
        self.assertFalse(update_always)

    def test_update_always_without_force(self):
        """Test update_always method without force behavior."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_always", False
        )
        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertTrue(update_always)


if __name__ == "__main__":
    unittest.main()
