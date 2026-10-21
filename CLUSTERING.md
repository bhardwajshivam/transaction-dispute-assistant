# Cluster-distance anomaly signal

`clustering.py` implements bounded Lloyd k-means with deterministic farthest-first
initialisation. It adds a secondary unusualness signal to the existing activity
rules. No LLM, new package, hosted service or database reset is needed.

## Method and authority

The read-only adapter independently checks customer/account/card ownership and
loads a consistent transaction snapshot. Only posted purchases on the selected
card in the same currency, bought and posted before the selected payment's date,
are eligible. Same-day, future, pending and other-currency payments are excluded.
The window is 90 days, with at least 50 eligible purchases and at most 300 retained.

Historical purchase dates define an approximately 70/30 train/calibration split.
Dates are kept together: training purchases **and their posting dates** precede
the first calibration purchase date. A minimum of 30 training and 10 calibration
records is required. This avoids using late-posted training facts that would not
have been known at calibration time. Missing, malformed or duplicate required
history produces abstention. Limits and convergence failures are explicit.

Features are log(1 + amount in minor units), online/card-present channel,
recurring status and one-hot merchant category/MCC. Amount mean/scale and category
vocabulary fit on training rows only. Amount scale has a 0.25 floor; categorical
features have weight 0.5. An explicit unseen-category dimension handles a new MCC.
Unknown MCC remains a recorded category for older fixtures lacking that field.
IDs, descriptions, statements, route labels and authorisation truth are excluded
from feature vectors. There is no FX conversion and no hour/velocity feature yet.

The algorithm requests three clusters, or fewer if distinct points are limited.
Farthest-first initialisation and stable ties make runs reproducible; it is not
random k-means++. Lloyd updates stop at convergence or 40 iterations. Failure to
converge returns UNAVAILABLE rather than a score. The model may reach a local
optimum; no claim of globally optimal clustering is made. A small standard-library
implementation makes the actual algorithm reviewable without another runtime
dependency. The reference [scikit-learn clustering guide](https://scikit-learn.org/dev/modules/clustering.html)
describes k-means and its Euclidean/cluster-shape assumptions.

The target's Euclidean distance to its nearest centre is divided by a threshold:

`anomaly_score = target_distance / max(95th percentile of calibration distances, 1.5)`

The percentile uses the nearest-rank definition. **Values strictly above 1 flag
unusualness.** This is an unbounded distance ratio, not a probability, likelihood
of fraud, confidence level or percentage. The quantile and distance floor are
prototype choices; they have not been calibrated to banking outcomes. Small
calibration sets make the empirical quantile especially coarse.

The selected transaction never fits the scaler, vocabulary, centres or threshold.
Historical calibration data does not fit centres/scaling. Each new assessment
refits from its own permitted history rather than sharing other customers' data.
No case-generation or action tool is available to this module.

## Routing and UI

Versioned configuration: `policies/clustering_v1.json`. Default **shadow mode**
records and displays the score but makes **no change to routing**. Existing
deterministic amount and repeated-order rules remain active independently.

A separate `review_decision` table supports explicit `recommend_review` mode.
If deliberately enabled in trusted configuration, an assessed score above the
threshold adds sticky `CLUSTER_ACTIVITY_REVIEW`. It can only recommend specialist
review: handoff and case creation still require their existing explicit customer
confirmations, permission checks and audit controls. The earlier fix that skips
merchant recognition when specialist review is required applies to this reason
too. Customer text cannot set the configuration mode.

The chat shows **Spending-pattern clustering**, its status, distance score,
threshold flag and training/calibration counts. Observation-mode text makes clear
that clustering does not change the dispute route. Insufficient history produces
a reason code and no score. A low score never declares a payment safe.

The encrypted concern, case and handoff snapshots retain the assessment, model
version/configuration, feature scaler, centres, threshold, calibration distances,
training/calibration fact records, dominant squared-distance contributions and
reproducible model ID. These make a result reviewable. Staff see the snapshot in
their existing authenticated workspace. Customer exports expose only assessment
status/version/mode/score/reason; raw historical training data is excluded.
The clustering snapshot is not sent to Ollama. Old snapshots are preserved;
new evidence-gathering runs add the new assessment.

## Try it

```sh
source .venv/bin/activate
CONCERNS_DATABASE="$PWD/data/activity.sqlite" python -m streamlit run app.py
```

Choose the unrecognised-payment option, CARD-001, and describe **TX-691847**.
After confirming search and selecting it, open **Spending-pattern clustering**.
The existing richer database, relabelled to INR without changing amounts, gives
this legitimate large purchase a distance score of approximately **1.745**.
TX-869736 scores approximately **0.239** despite a repeated-order signal from
the deterministic rules. This difference illustrates why both techniques have
limits and why duplicate processing is not inferred from distance alone.

## Evaluation

```sh
python scripts/evaluate_clustering.py --split development
python scripts/evaluate_clustering.py --split evaluation
python -m unittest tests.test_clustering -v
python -m unittest discover -s tests -q
```

The evaluator reads only the transaction/history fields for fitting/scoring,
then summarises outcomes against sidecar authorisation truth. It does not tune
thresholds or declare agreement with deterministic route labels as clustering
accuracy. Reports live in `data/activity_corpus/results/*_clustering_report.json`.

On each 78-case split, **66 cases were assessed and 12 abstained**. None of those
66 exceeded the clustering threshold, including six legitimate outliers relative
to the simpler median rule and six ordinary-looking unauthorised payments.
The constructed boundary amounts remain near some ordinary spending clusters.
This establishes neither useful fraud detection nor adequate recall. Separate
positive-control probes multiply the largest historical amount by 100, outside
the main 78-case denominator. They check extreme-distance sensitivity rather
than representing realistic prevalence. Repeated recipes and deliberate
authorisation counterfactuals are not independent statistical observations.

Tests cover known centroid solutions, constant history, deterministic ordering,
target exclusion, calibration isolation, delayed-posting leakage, date/ownership/
currency boundaries, invalid/insufficient data, nonconvergence, observation-mode
control, reproducible corpus reports and the Streamlit score display. No test
asserts that an anomaly is fraud. The full suite passes **133 tests**, including
15 focused clustering tests.

Keep observation mode until representative independently reviewed cases show
useful additional signals at an acceptable false-review rate. Category weights,
cluster count, log scaling, history length and threshold all influence distance.
Contaminated history, drift, long-tailed legitimate purchases and missing features
can hide suspicious activity or create false alarms. A fraud probability would
require labelled outcomes and separate calibration; this implementation does
not provide one.
