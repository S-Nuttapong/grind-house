"""Fit eval metrics on the fake scorer. No model download."""

from jobhunt.fit.base import BragDoc
from jobhunt.fit.eval import FitLabel, eval_fit, fit_gates, icc, quadratic_kappa, retest_sd
from jobhunt.fit.fake import FakeFitScorer


def test_kappa_is_one_when_raters_agree() -> None:
    assert quadratic_kappa([1, 2, 3], [1, 2, 3]) == 1
    assert icc([[1, 1], [2, 2], [3, 3]]) == 1
    assert retest_sd([[10, 10], [20, 20]]) == 0


def test_fake_scorer_repeats_exactly() -> None:
    docs = [BragDoc(id="doc-1", text="built billing services")]
    labels = [
        FitLabel(
            description="Build billing services for the team.\n\nOwn the API.",
            rating=4,
            docs=("doc-1",),
        ),
        FitLabel(description="Unrelated cooking blog post about bread.", rating=1, docs=()),
    ]
    report = eval_fit(FakeFitScorer(), docs, labels, reps=2)
    assert report.retest_sd == 0
    assert report.icc == 1
    assert report.order_delta is not None
    assert "retest sd above 5" not in fit_gates(report, baseline_spearman=None)
