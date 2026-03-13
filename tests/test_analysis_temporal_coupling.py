"""
tests/test_analysis_temporal_coupling.py — Unit tests for temporal_coupling.py
"""

from unittest.mock import patch, MagicMock

from Analysis.temporal_coupling import (
    TemporalCouplingAnalyzer,
    CoupledPair,
    TemporalCouplingReport,
)


class TestCoupledPair:
    def _pair(self, pct):
        return CoupledPair(
            "a.py",
            "b.py",
            cochange_count=5,
            total_commits_a=10,
            total_commits_b=8,
            coupling_pct=pct,
        )

    def test_strong_coupling(self):
        assert self._pair(0.80).strength == "strong"

    def test_moderate_coupling(self):
        assert self._pair(0.55).strength == "moderate"

    def test_weak_coupling(self):
        assert self._pair(0.30).strength == "weak"

    def test_badge_matches_strength(self):
        assert self._pair(0.80).badge == "🔴"
        assert self._pair(0.55).badge == "🟡"
        assert self._pair(0.30).badge == "🟢"


class TestReport:
    def _make(self):
        r = TemporalCouplingReport()
        r.pairs = [
            CoupledPair("a.py", "b.py", 10, 12, 10, 0.83),
            CoupledPair("c.py", "d.py", 3, 8, 5, 0.37),
        ]
        return r

    def test_top_pairs_sorted(self):
        r = self._make()
        top = r.top_pairs
        assert top[0].coupling_pct >= top[1].coupling_pct

    def test_strong_pairs_filter(self):
        r = self._make()
        for p in r.strong_pairs:
            assert p.coupling_pct >= 0.75

    def test_as_dict_keys(self):
        r = self._make()
        d = r.as_dict()
        for key in ("total_pairs", "strong_pairs", "top_pairs", "commits_analyzed"):
            assert key in d


class TestAnalyzer:
    def test_no_git_returns_unavailable(self, tmp_path):
        a = TemporalCouplingAnalyzer(root=tmp_path)
        r = a.analyze()
        assert r.git_available is False

    def test_mocked_two_files_cochange(self, tmp_path):
        """Two files changed in every commit → coupling = 1.0"""
        fake_log = (
            "COMMIT_BOUNDARY\nAnalysis/smells.py\nAnalysis/lint.py\n"
            "COMMIT_BOUNDARY\nAnalysis/smells.py\nAnalysis/lint.py\n"
            "COMMIT_BOUNDARY\nAnalysis/smells.py\nAnalysis/lint.py\n"
        )

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = fake_log
            return m

        with patch("Analysis.temporal_coupling.subprocess.run", side_effect=fake_run):
            r = TemporalCouplingAnalyzer(root=tmp_path).analyze(
                min_commits=2, min_coupling=0.1
            )

        assert r.git_available is True
        assert len(r.pairs) >= 1
        pair = r.pairs[0]
        assert pair.coupling_pct == pytest.approx(1.0)

    def test_min_commits_filter(self, tmp_path):
        """Pair with only 1 co-change should be filtered when min_commits=2."""
        fake_log = "COMMIT_BOUNDARY\na.py\nb.py\n"

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = fake_log
            return m

        with patch("Analysis.temporal_coupling.subprocess.run", side_effect=fake_run):
            r = TemporalCouplingAnalyzer(root=tmp_path).analyze(
                min_commits=2, min_coupling=0.0
            )

        assert len(r.pairs) == 0

    def test_single_file_commits_excluded(self, tmp_path):
        """Commits with only one file should not generate pairs."""
        fake_log = "COMMIT_BOUNDARY\na.py\nCOMMIT_BOUNDARY\na.py\n"

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = fake_log
            return m

        with patch("Analysis.temporal_coupling.subprocess.run", side_effect=fake_run):
            r = TemporalCouplingAnalyzer(root=tmp_path).analyze(
                min_commits=1, min_coupling=0.0
            )

        assert len(r.pairs) == 0


import pytest  # noqa: E402
