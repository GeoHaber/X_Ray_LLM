"""
tests/test_analysis_git_hotspots.py — Unit tests for Analysis/git_hotspots.py
"""
from pathlib import Path
from unittest.mock import patch, MagicMock

from Analysis.git_hotspots import HotspotAnalyzer, HotspotFile, HotspotReport


class TestHotspotFile:
    def test_badge_flame_high_priority(self):
        h = HotspotFile(path="a.py", churn=30, complexity=8, loc=200, priority=30)
        assert h.badge == "🔥"

    def test_badge_warning_mid_priority(self):
        h = HotspotFile(path="a.py", churn=10, complexity=4, loc=100, priority=12)
        assert h.badge == "⚠️"

    def test_badge_doc_low_priority(self):
        h = HotspotFile(path="a.py", churn=2, complexity=1, loc=20, priority=3)
        assert h.badge == "📄"


class TestHotspotReport:
    def _make_report(self):
        r = HotspotReport()
        r.hotspots = [
            HotspotFile("a.py", churn=20, complexity=10, loc=300, priority=40),
            HotspotFile("b.py", churn=5,  complexity=2,  loc=50,  priority=6),
            HotspotFile("c.py", churn=15, complexity=8,  loc=200, priority=25),
        ]
        return r

    def test_top_hotspots_sorted_descending(self):
        r = self._make_report()
        top = r.top_hotspots
        for i in range(len(top) - 1):
            assert top[i].priority >= top[i + 1].priority

    def test_flame_files_only_high_priority(self):
        r = self._make_report()
        for f in r.flame_files:
            assert f.badge == "🔥"

    def test_as_dict_required_keys(self):
        r = self._make_report()
        d = r.as_dict()
        for key in ("git_available", "analysis_days", "total_files", "top_hotspots"):
            assert key in d

    def test_as_dict_top_hotspots_list(self):
        r = self._make_report()
        d = r.as_dict()
        assert isinstance(d["top_hotspots"], list)


class TestHotspotAnalyzer:
    def test_no_git_repo_returns_unavailable(self, tmp_path):
        """Folder that is not a git repo should return git_available=False."""
        analyzer = HotspotAnalyzer(root=tmp_path)
        report = analyzer.analyze(days=90)
        assert report.git_available is False
        assert report.error != ""

    def test_analyze_with_mocked_git(self, tmp_path):
        """Mock git subprocess to return deterministic output."""
        fake_log = (
            "\n"
            "Analysis/smells.py\n"
            "UI/tabs/graph_tab.py\n"
            "\n"
            "Analysis/smells.py\n"
            "\n"
        )

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            if "rev-parse" in cmd:
                m.returncode = 0
            else:
                m.returncode = 0
                m.stdout = fake_log
            return m

        with patch("Analysis.git_hotspots.subprocess.run", side_effect=fake_run):
            analyzer = HotspotAnalyzer(root=tmp_path)
            report = analyzer.analyze(days=90)

        assert report.git_available is True
        assert len(report.hotspots) >= 2
        paths = [h.path for h in report.hotspots]
        assert "Analysis/smells.py" in paths

    def test_churn_counts_correct_with_mock(self, tmp_path):
        fake_log = (
            "\nAnalysis/smells.py\n"
            "\nAnalysis/smells.py\n"
            "\nAnalysis/smells.py\n"
        )

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = fake_log
            return m

        with patch("Analysis.git_hotspots.subprocess.run", side_effect=fake_run):
            analyzer = HotspotAnalyzer(root=tmp_path)
            report = analyzer.analyze(days=90)

        smell = next((h for h in report.hotspots if h.path == "Analysis/smells.py"), None)
        assert smell is not None
        assert smell.churn == 3

    def test_priority_boosted_by_complexity(self, tmp_path):
        fake_log = "\nsome_file.py\n"

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = fake_log
            return m

        with patch("Analysis.git_hotspots.subprocess.run", side_effect=fake_run):
            analyzer = HotspotAnalyzer(root=tmp_path)
            r_no_cx = analyzer.analyze(days=90, complexity_map={})
            r_high_cx = analyzer.analyze(days=90, complexity_map={"some_file.py": 20.0})

        base = next((h for h in r_no_cx.hotspots if h.path == "some_file.py"), None)
        boosted = next((h for h in r_high_cx.hotspots if h.path == "some_file.py"), None)
        assert base is not None and boosted is not None
        assert boosted.priority > base.priority
