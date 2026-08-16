"""Tests for the shared quality vocabulary (03 §5.5, §8.2)."""

from contracts import quality


class TestLocatorTier:
    """A lower tier number is a better locator — hence `meets`."""

    def test_an_anchored_locator_meets_a_coarse_minimum(self):
        """Tier 1 satisfies a route asking for tier 2 or better."""
        assert quality.LocatorTier.ANCHORED.meets(quality.LocatorTier.COARSE)

    def test_a_coarse_locator_does_not_meet_an_anchored_minimum(self):
        """Tier 2 does not satisfy a route asking for tier 1."""
        assert not quality.LocatorTier.COARSE.meets(
            quality.LocatorTier.ANCHORED
        )

    def test_a_tier_meets_itself(self):
        """The comparison is inclusive."""
        for tier in quality.LocatorTier:
            assert tier.meets(tier)

    def test_diagnostic_never_meets_an_mvp_route(self):
        """Tier 3 alone never satisfies an MVP route (03 §5.5)."""
        assert not quality.LocatorTier.DIAGNOSTIC.meets(
            quality.LocatorTier.COARSE
        )
        assert not quality.LocatorTier.DIAGNOSTIC.meets(
            quality.LocatorTier.ANCHORED
        )


def test_verdicts_are_the_three_the_design_names():
    """valid, partial, failed — and nothing else (03 §7.4)."""
    assert {verdict.value for verdict in quality.QualityVerdict} == {
        "valid",
        "partial",
        "failed",
    }
