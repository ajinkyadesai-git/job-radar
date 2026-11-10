"""Train and evaluate the fit model: would you apply to this posting?

A logistic regression over the words in the title and description, the role family,
seniority, workplace type and company, plus salary and the company's sponsorship record.
Simple on purpose: with a few hundred labels a linear model is hard to beat, trains in
seconds, and its weights explain each prediction.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_score, recall_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from jobradar.fit.features import CATEGORICAL, NUMERIC, TEXT_BODY, TEXT_TITLE, prepare

# Rule to beat: "would apply" = any of your five role families (not Other).
BASELINE_FAMILIES = {
    "Business systems / ERP",
    "Integration / solutions",
    "Data / BI / AI",
    "Software",
    "Technical program / product",
}


class ResumeMatch(BaseEstimator, TransformerMixin):
    """One number per posting: how closely its description matches your resume (0 to 1).

    Words are weighted by how rare they are across postings (TF-IDF), so "NetSuite" or "dbt"
    in both counts for more than "team". The resume is read on your laptop only; it is kept
    inside the saved model file, which lives in git-ignored data/.
    """

    def __init__(self, resume_text: str = ""):
        self.resume_text = resume_text

    def fit(self, X, y=None):
        if not self.resume_text.strip():
            return self  # no resume: the feature is a constant 0
        docs = list(pd.Series(X).fillna("")) + [self.resume_text]
        self.vec_ = TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, sublinear_tf=True, stop_words="english"
        ).fit(docs)
        self.resume_vec_ = self.vec_.transform([self.resume_text])
        return self

    def transform(self, X):
        if not self.resume_text.strip():
            return np.zeros((len(X), 1))
        sims = cosine_similarity(self.vec_.transform(pd.Series(X).fillna("")), self.resume_vec_)
        return np.asarray(sims).reshape(-1, 1)

    def get_feature_names_out(self, input_features=None):
        return np.array(["resume_match"])


def resume_scores(pipe: Pipeline, df: pd.DataFrame) -> np.ndarray:
    """The resume-match score (0 to 1) the fitted pipeline gives each posting."""
    ct = pipe.named_steps["features"]
    match = ct.named_transformers_["resume"].named_steps["resumematch"]
    return match.transform(prepare(df)[TEXT_BODY]).ravel()


def predict_proba(pipe: Pipeline, df: pd.DataFrame) -> np.ndarray:
    """Chance (0 to 1) that you would apply, for postings straight from the gold table."""
    return pipe.predict_proba(prepare(df))[:, 1]


def build_pipeline(resume_text: str = "") -> Pipeline:
    features = ColumnTransformer(
        [
            (
                "resume",
                make_pipeline(ResumeMatch(resume_text), StandardScaler()),
                TEXT_BODY,
            ),
            ("title", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True), TEXT_TITLE),
            (
                "body",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=5000,
                    sublinear_tf=True,
                    stop_words="english",
                ),
                TEXT_BODY,
            ),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            (
                "num",
                make_pipeline(
                    SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                    StandardScaler(),
                ),
                NUMERIC,
            ),
        ]
    )
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
    return Pipeline([("features", features), ("clf", clf)])


@dataclass
class Scores:
    n: int
    positives: int
    precision: float
    recall: float
    pr_auc: float | None
    precision_at_10: float | None


def score(y_true: np.ndarray, y_pred: np.ndarray, proba: np.ndarray | None) -> Scores:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    p10 = None
    pr_auc = None
    if proba is not None:
        if len(set(y_true)) > 1:
            pr_auc = round(float(average_precision_score(y_true, proba)), 3)
        top = np.argsort(-proba)[:10]
        p10 = round(float(y_true[top].mean()), 3) if len(top) else None
    return Scores(
        n=len(y_true),
        positives=int(y_true.sum()),
        precision=round(float(precision_score(y_true, y_pred, zero_division=0)), 3),
        recall=round(float(recall_score(y_true, y_pred, zero_division=0)), 3),
        pr_auc=pr_auc,
        precision_at_10=p10,
    )


def baseline_predict(df: pd.DataFrame) -> np.ndarray:
    return df["role_family"].isin(BASELINE_FAMILIES).astype(int).to_numpy()


@dataclass
class Report:
    train_days: list[str]
    test_days: list[str]
    n_train: int
    n_test: int
    model: Scores
    baseline: Scores
    threshold: float
    top_apply_terms: list[str]
    top_skip_terms: list[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


def top_terms(pipe: Pipeline, k: int = 15) -> tuple[list[str], list[str]]:
    """The features that push hardest toward apply and toward skip."""
    names = pipe.named_steps["features"].get_feature_names_out()
    coef = pipe.named_steps["clf"].coef_[0]
    order = np.argsort(coef)
    return [names[i] for i in order[::-1][:k]], [names[i] for i in order[:k]]


def train_and_evaluate(
    data: pd.DataFrame, train_keys, test_keys, threshold: float = 0.5, resume_text: str = ""
):
    """data: one row per labeled posting with features and y. Returns (fitted pipeline, report)."""
    data = prepare(data)
    train = data[data["posting_key"].isin(set(train_keys))]
    test = data[data["posting_key"].isin(set(test_keys))]
    if train["y"].nunique() < 2:
        raise ValueError("training labels need both 'Would apply' and 'Would skip'")
    pipe = build_pipeline(resume_text).fit(train, train["y"])
    proba = pipe.predict_proba(test)[:, 1]
    pred = (proba >= threshold).astype(int)
    apply_terms, skip_terms = top_terms(pipe)
    report = Report(
        train_days=sorted({str(d) for d in train["label_date"]}),
        test_days=sorted({str(d) for d in test["label_date"]}),
        n_train=len(train),
        n_test=len(test),
        model=score(test["y"], pred, proba),
        baseline=score(test["y"], baseline_predict(test), None),
        threshold=threshold,
        top_apply_terms=apply_terms,
        top_skip_terms=skip_terms,
    )
    # Final model learns from every label, so tomorrow's scores use everything you know.
    final = build_pipeline(resume_text).fit(data, data["y"])
    return final, report


def save(pipe: Pipeline, report: Report, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, out / "fit_model.joblib")
    (out / "fit_report.json").write_text(report.to_json())
    return out
