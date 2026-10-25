"""Mission 12 Stage A read-out: the summary and the figures. Zero solves, zero power flows.

This module reads the artefacts that `run_stage_a.py` wrote -- the 36 evaluations,
`results/verdicts.json`, `results/control_d.json` and the six `results/control_e_*.json` --
and writes one summary JSON plus six SVG figures. It computes **no new result**: every number
here is a copy, a difference, a share or a count over the written artefacts.

**The evaluation code is frozen.** `ratings_core.py` (`8527be1d...`) and `run_stage_a.py`
(`4fd263fc...`) are pinned in all 36 evaluations and in `verdicts.json`, so the read-out is a
new module rather than an edit: it imports `ratings_core` for the write-once helper and the
hashes, and reads only artefacts. `summarise` fails loudly if any evaluation records a
different pair.

**Amendment A4 is load-bearing** (protocol, Amendments, 2026-10-25; AKK-84). `verdicts.json`
reports `controls.D.pass = null`, because `cmd_verdicts` reads `pass` at the top level of
`results/control_d.json` while the record stores it at `rating_only_change.pass`; and it
reports no fragility flag for H3a. Both gaps are read-out gaps, so they are repaired here, in
`a4_corrections`, with the amendment cited. Nothing is re-run and no artefact is rewritten.

**Amendment A5 is load-bearing too** (protocol, Amendments, 2026-10-25; AKK-87), and is also
read-out only: `fragility_a5` adds protocol s. 9's fragile-margin rule for H5(c) and H4 and a
paired-SE reading of H3b and H3c, `verification` adds an energy-weighted recovery as a
secondary descriptive statistic, and `disclosure` states eight limits the post-experiment
review named. `verdicts.json` is kept as written and **no verdict changes**.

The figures are drawn by Mission 11's `svgplot.py`, imported from
`analysis/export_envelope_shift/` through `sys.path` and never copied. Its ODbL notice names
Mission 11's attribution file, so `build_figures` points it at Mission 12's for the length of
one call and restores it afterwards (amendment A5): a process that imports this module must
not find Mission 11's module global rewritten.

**No SimBench parameter value** (a rating, an impedance, a `std_type` name) leaves this
module: `assert_no_simbench_parameters` scans every written byte, with the forbidden values
taken from the artefacts themselves.

Commands:

* `summarise` -- write `results/stage_a_summary.json` (write-once), then `figures/fig_*.svg`.
* `verify` -- read-only: check the written summary against `PINNED_SUMMARY_SHA256` and every
  input its provenance names against the recorded digest, and refuse an unaccounted-for
  `eval_*` artefact. Writes nothing and recomputes nothing.
* `figure --name <file name>` -- redraw one figure, refusing unless the recomputed summary
  equals the stored one outside this module's own hash.

`--dry-run` computes and prints without writing, so each write-once artefact is written once.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MISSION11 = HERE.parent / "export_envelope_shift"
for _path in (HERE, MISSION11):  # imported, never copied or edited
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import ratings_core as rc  # noqa: E402
import svgplot  # noqa: E402

#: ODbL 1.0 s. 4.3 wants a notice associated with every Produced Work. `svgplot` holds its
#: notice as a module global that `Figure.to_svg` reads at draw time, so Mission 12's figures
#: need it assigned while they are drawn: the sentence is Mission 11's, with Mission 12's own
#: attribution file. Amendment A5: the assignment is made inside `build_figures` and undone in
#: its `finally`, so importing this module does not rewrite Mission 11's notice for the rest of
#: the process. Both missions' tests read the live global, not a literal.
ATTRIBUTION_NOTICE = (
    "Contains information from SimBench (simbench.de), made available under the Open "
    "Database License (ODbL 1.0). "
    "See analysis/asset_rating_information/DATA_ATTRIBUTION.md."
)

#: Overridable so that the tests can point the read-out at a synthetic directory. The
#: functions below resolve them as module globals at call time, never as default arguments.
RESULTS = HERE / "results"
RUNS = HERE / "runs"
FIGURES = HERE / "figures"

SUMMARY_NAME = "stage_a_summary.json"

#: The frozen summary's own sha256, as written and reported. `verify` checks the file on disk
#: against this pin and then every input the summary's provenance lists against its recorded
#: digest, so a value-level corruption -- valid JSON with a changed number -- is caught rather
#: than silently read.
PINNED_SUMMARY_SHA256 = "1f6faed5e726d61b71a465a9504bb559cf5c84ecdcc5ec93f4afd16c680e45e6"

#: The frozen evaluation pair, as pinned in every evaluation and in `verdicts.json`.
FROZEN_CODE_SHA256 = {
    "ratings_core.py": "8527be1d58fcafb8ba789956f4021fe95c6fc6f04c5e461e10dcae6b33b41df8",
    "run_stage_a.py": "4fd263fc43256a783792201b7373f2fe3b05102221d2fc38dab1bc52bdcf222d",
}
PROTOCOL_RELATIVE = "analysis/asset_rating_information/stage_a_protocol.md"
SVGPLOT_RELATIVE = "analysis/export_envelope_shift/svgplot.py"
READ_OUT_NAME = "analyse_stage_a.py"

EVAL_RE = re.compile(r"^eval_(?P<network>[A-Za-z0-9]+)_(?P<model>[A-Za-z0-9]+)\.json$")
CONTROL_E_RE = re.compile(r"^control_e_(?P<network>[A-Za-z0-9]+)\.json$")

#: Protocol s. 5's models, in the order they are reported. `U2w3` is U2 at w = 0.3.
MODEL_ORDER = ("U0", "U2", "U2w3", "U3", "U4", "UT", "U2P")
U2 = "U2"
U2_W3 = "U2w3"
U2_PRIME = "U2P"
TRAFO_MODEL = "UT"
CABLE_LIMITED = "cable-limited"

#: Protocol s. 7: R = (export(policy) - export(B2)) / (export(B4) - export(B2)) on E.
ORACLE_POLICY = "B4"
BASE_POLICY = "B2"
#: H3c's random reference (protocol s. 6), the second arm of A5's paired standard error.
RANDOM_POLICY = "B5"
#: The reference policies of protocol s. 7, which carry no recovery.
DIRECT_KEY = "na"
BUDGET_ALL = "all"
#: Protocol s. 7's H5(c) budget, and the budget U2' is read out at.
K_FOUR = "4"
#: The recovery levels B6's smallest sufficient budget is reported for.
B6_TARGETS = (0.5, 0.9)
#: Protocol s. 7's H3a rejection threshold, and s. 9's fragile-margin multiple.
H3A_REJECT_THRESHOLD = 0.25
FRAGILE_SE_MULTIPLE = 2.0
#: U2' per-draw check: a denominator below this share of the oracle is treated as collapsed.
U2P_SMALL_GAP_SHARE = 0.01

A4_CITATION = "amendment A4 (2026-10-25; AKK-84), protocol Amendments"
A5_CITATION = "amendment A5 (2026-10-25; AKK-87), protocol Amendments"
RATIO_OF_MEANS_LABEL = "descriptive; not the protocol's per-draw R"

#: Amendment A5's secondary recovery: a ratio of means, not the mean of per-draw ratios.
ENERGY_WEIGHTED_LABEL = (
    "secondary descriptive statistic (A5); the s. 7 verdict statistic is the mean of per-draw "
    "ratios"
)
#: Under U2' the per-draw denominator can collapse, so the ratio of means carries u2_prime's
#: own caveat as well (amendment A5).
ENERGY_WEIGHTED_U2P_NOTE = "descriptive; the denominator can be <= 0 per draw"
#: `verdicts.json` adds the two policies' marginal standard errors instead of pairing by draw,
#: which overstates the uncertainty of a difference; A5 keeps the flag and labels it.
VERDICTS_SE_LABEL = "conservative: summed marginal SEs"
A5_NO_VERDICT_CHANGES = "no verdict changes"
#: H4's criterion is a share of truth draws, so its standard error is binomial.
H4_MODELS = (U2, "U4")
#: Protocol s. 10's H4 enumeration: sizes 1..`H4_ENUMERATED_KMAX` over the m = 10 top
#: candidates, i.e. 847 subsets. The count is recomputed here rather than copied.
H4_TOP_M = 10
H4_ENUMERATED_KMAX = 6

#: Text that may never leave this module: a `std_type` name or a rating in kA. The numeric
#: rating values are not listed here -- they are read from the artefacts by `forbidden_values`.
FORBIDDEN_TOKENS = ("std_type", "max_i_ka", "NAYY", "NA2X")


# --- A. loading the artefacts ---------------------------------------------------------------


def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _input_key(path: Path) -> str:
    """An artefact's provenance key: its directory name and its file name."""
    return f"{path.parent.name}/{path.name}"


def summary_path() -> Path:
    return RESULTS / SUMMARY_NAME


def _input_path(key: str) -> Path:
    """The file a provenance key names, resolved under the live `RESULTS` / `RUNS` globals so
    that a synthetic tree is checked rather than the study's own directories."""
    folder, _, name = key.partition("/")
    roots = {RESULTS.name: RESULTS, RUNS.name: RUNS}
    if not name or folder not in roots:
        raise ValueError(f"{key!r} is not a provenance key of the form <directory>/<file name>")
    return roots[folder] / name


def _f(value) -> float | None:
    """A plain float, or None for a null the frozen code wrote."""
    if value is None:
        return None
    number = float(value)
    return None if number != number else number


def _nan(value) -> float:
    """A float for a figure: a missing value becomes NaN, which `svgplot` skips."""
    return float("nan") if value is None else float(value)


def _model_rank(model: str) -> tuple[int, str]:
    return (MODEL_ORDER.index(model) if model in MODEL_ORDER else len(MODEL_ORDER), model)


@dataclass
class Study:
    """Every artefact the read-out reads, with its sha256 and the per-draw U2' arrays."""

    evals: dict[tuple[str, str], dict]
    verdicts: dict
    control_d: dict
    control_e: dict[str, dict]
    u2p_draws: dict[str, dict[str, np.ndarray]]
    u2_draws: dict[str, dict[str, np.ndarray]]
    inputs: dict[str, str]
    summary: dict = field(default_factory=dict)

    @property
    def classes(self) -> dict[str, str]:
        """Each network's H1 class, read from `verdicts.json` rather than hard-coded."""
        return {name: block["class"] for name, block in self.verdicts["H1"]["networks"].items()}

    @property
    def networks(self) -> tuple[str, ...]:
        return tuple(self.verdicts["H1"]["networks"])

    @property
    def cable_limited(self) -> tuple[str, ...]:
        classes = self.classes
        return tuple(name for name in self.networks if classes[name] == CABLE_LIMITED)

    def models(self, network: str) -> tuple[str, ...]:
        found = [model for (net, model) in self.evals if net == network]
        return tuple(sorted(found, key=_model_rank))

    def record(self, network: str, model: str) -> dict:
        try:
            return self.evals[(network, model)]
        except KeyError:
            raise KeyError(f"no evaluation for {network}/{model}") from None

    def companion_model(self, network: str) -> str:
        """Protocol s. 5's second model for a network: U-T if the transformer is the binding
        asset, U2 at w = 0.3 if the cables are."""
        return U2_W3 if self.classes[network] == CABLE_LIMITED else TRAFO_MODEL


def export_array_key(policy: str, budget: str) -> str:
    """The per-draw export array one (policy, budget) cell is written under in the npz."""
    return f"{policy}__{budget}__export"


def a5_paired_array_keys(verdicts: dict, network: str) -> list[str]:
    """The per-draw arrays amendment A5's paired standard errors need for one network.

    The compared policies and the compared budget are **not** chosen here: they are read from
    `verdicts.json`, which recorded H3b's argmax at its selected k and H3c's best targeted
    policy, so the paired standard error describes the very comparison the verdict was taken
    on. H3c's budget is protocol s. 7's k = 4.
    """
    block = verdicts["H3"]["per_network"][network]
    keys = [
        export_array_key(ORACLE_POLICY, DIRECT_KEY),
        export_array_key(BASE_POLICY, DIRECT_KEY),
    ]
    h3b = block["H3b"]
    budget = str(h3b["budget_with_smallest_gap"])
    cell = h3b["per_budget"][budget]
    keys += [export_array_key(cell["single"], budget), export_array_key(cell["structural"], budget)]
    h3c = block["H3c"]
    keys += [
        export_array_key(h3c["best_targeted"], K_FOUR),
        export_array_key(RANDOM_POLICY, K_FOUR),
    ]
    return sorted(set(keys))


def assert_complete(
    evals: dict[tuple[str, str], dict], verdicts: dict, control_e: dict[str, dict]
) -> None:
    """The evaluations found must be exactly the ones `verdicts.json` scored.

    Without this check a tree with one `eval_*.json` removed still produces a summary -- a
    smaller one, with `frozen_code_check.all_match = true`, because every record that *is*
    present pins the frozen pair. The read-out would then describe a subset of the experiment
    while reporting it as the whole. `combinations_scored` is the authority, and
    `combinations_missing` must be empty, since a missing combination is not a result.
    """
    found = {f"{network}/{model}" for network, model in evals}
    scored = set(verdicts["combinations_scored"])
    problems: list[str] = []
    if missing := sorted(scored - found):
        problems.append(f"no evaluation for the scored combination(s) {', '.join(missing)}")
    if extra := sorted(found - scored):
        problems.append(f"{', '.join(extra)} is not in verdicts.json combinations_scored")
    if recorded := list(verdicts["combinations_missing"]):
        problems.append(
            f"verdicts.json records combinations_missing {', '.join(map(str, recorded))}"
        )
    if uncovered := sorted(set(verdicts["H1"]["networks"]) - set(control_e)):
        problems.append(f"no control_e_*.json for the network(s) {', '.join(uncovered)}")
    if problems:
        raise ValueError(
            f"the artefact set does not match verdicts.json: {'; '.join(problems)}. The "
            "read-out refuses to summarise part of the experiment as though it were the whole."
        )


def load_study() -> Study:
    """Read every artefact the read-out needs, failing loudly on a partial set."""
    eval_paths = sorted(RESULTS.glob("eval_*.json"))
    if not eval_paths:
        raise FileNotFoundError(f"{RESULTS} holds no eval_*.json; the read-out needs the set")
    evals: dict[tuple[str, str], dict] = {}
    inputs: dict[str, str] = {}
    for path in eval_paths:
        match = EVAL_RE.match(path.name)
        if match is None:
            raise ValueError(f"{path.name} is not named eval_<network>_<model>.json")
        record = _load_json(path)
        named = (match["network"], match["model"])
        stored = (record["network"], record["model"])
        if named != stored:
            raise ValueError(
                f"{path.name} names {named[0]}/{named[1]} but the record says "
                f"{stored[0]}/{stored[1]}"
            )
        evals[stored] = record
        inputs[_input_key(path)] = rc.sha256_of(path)

    verdicts_path = RESULTS / "verdicts.json"
    control_d_path = RESULTS / "control_d.json"
    for path in (verdicts_path, control_d_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; the read-out needs the complete set")
        inputs[_input_key(path)] = rc.sha256_of(path)
    verdicts = _load_json(verdicts_path)
    control_d = _load_json(control_d_path)

    control_e: dict[str, dict] = {}
    for path in sorted(RESULTS.glob("control_e_*.json")):
        if CONTROL_E_RE.match(path.name) is None:
            raise ValueError(f"{path.name} is not named control_e_<network>.json")
        payload = _load_json(path)
        control_e[payload["network"]] = payload
        inputs[_input_key(path)] = rc.sha256_of(path)

    assert_complete(evals, verdicts, control_e)

    # The npz arrays are read for the U2' per-draw counts alone (protocol s. 5's
    # misspecification check): every other number here comes from the JSON records.
    u2p_draws: dict[str, dict[str, np.ndarray]] = {}
    for network, model in sorted(evals):
        if model != U2_PRIME:
            continue
        path = RUNS / f"eval_{network}_{model}.npz"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; U2' needs its per-draw arrays")
        with np.load(path) as bundle:
            u2p_draws[network] = {
                policy: np.asarray(bundle[f"{policy}__{DIRECT_KEY}__export"], dtype=float)
                for policy in (ORACLE_POLICY, BASE_POLICY)
            }
        inputs[_input_key(path)] = rc.sha256_of(path)

    # Amendment A5: the paired standard errors of H3b and H3c are differences of per-draw
    # recoveries, so the U2 arrays of the compared cells are read as well. Only the keys
    # `verdicts.json` names are loaded, and no number outside them is touched.
    classes = {name: block["class"] for name, block in verdicts["H1"]["networks"].items()}
    u2_draws: dict[str, dict[str, np.ndarray]] = {}
    for network, class_name in sorted(classes.items()):
        if class_name != CABLE_LIMITED:
            continue
        path = RUNS / f"eval_{network}_{U2}.npz"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing; amendment A5's paired standard errors need its per-draw arrays"
            )
        with np.load(path) as bundle:
            u2_draws[network] = {
                key: np.asarray(bundle[key], dtype=float)
                for key in a5_paired_array_keys(verdicts, network)
            }
        inputs[_input_key(path)] = rc.sha256_of(path)

    return Study(
        evals=evals,
        verdicts=verdicts,
        control_d=control_d,
        control_e=control_e,
        u2p_draws=u2p_draws,
        u2_draws=u2_draws,
        inputs=dict(sorted(inputs.items())),
    )


# --- B. record conventions ------------------------------------------------------------------


def _is_budgeted(entry) -> bool:
    """True for a policy scored at budgets, false for a reference policy or an absent one."""
    return (
        isinstance(entry, dict)
        and bool(entry)
        and all(key == BUDGET_ALL or key.isdigit() for key in entry)
    )


def budget_order(entry: dict) -> list[str]:
    """A budgeted policy's budgets: the numeric ones ascending, then "all"."""
    numeric = sorted((key for key in entry if key != BUDGET_ALL), key=int)
    return [*numeric, *([BUDGET_ALL] if BUDGET_ALL in entry else [])]


def export_mean(record: dict, policy: str, budget: str = DIRECT_KEY) -> float | None:
    return _f(record["policies"][policy][budget]["export_MWh"]["mean"])


def oracle_and_base(record: dict) -> tuple[float | None, float | None]:
    return export_mean(record, ORACLE_POLICY), export_mean(record, BASE_POLICY)


def ob_budget_limit(record: dict) -> int | None:
    """Protocol amendment A3: OB is searched to k <= `searched_kmax` and carries that set
    above it, so the later budgets repeat the last searched one and are omitted here."""
    block = record.get("ob") or {}
    if not block.get("available"):
        return None
    limit = block.get("searched_kmax", block.get("kmax"))
    return None if limit is None else int(limit)


def kept_budgets(record: dict, policy: str, entry: dict) -> list[str]:
    """The budgets reported for one policy, after OB's k <= searched_kmax restriction."""
    budgets = budget_order(entry)
    if policy != "OB":
        return budgets
    limit = ob_budget_limit(record)
    if limit is None:
        return []
    return [key for key in budgets if key != BUDGET_ALL and int(key) <= limit]


def recovery_point(entry: dict, gap: float | None, base: float | None) -> dict:
    """One (policy, budget) cell of protocol s. 7's recovery read-out.

    `recovery_energy_weighted` is amendment A5's secondary statistic: the record's **mean**
    exports put into the same formula, (mean(policy) - mean(B2)) / (mean(B4) - mean(B2)), which
    weights a draw by the energy at stake in it. `R_mean` stays the s. 7 verdict statistic, the
    mean of the per-draw ratios.
    """
    recovery = entry["recovery"]
    mean = _f(entry["export_MWh"]["mean"])
    return {
        "R_mean": _f(recovery["mean"]),
        "R_se": _f(recovery["se"]),
        "n": recovery["n"],
        "nan_excluded": recovery["nan_excluded"],
        "export_MWh_mean": mean,
        "recovery_energy_weighted": (
            None if mean is None or base is None or gap in (None, 0.0) else (mean - base) / gap
        ),
        "realised_units": _f(entry["realised_units"]["mean"]),
        "realised_segments": _f(entry["realised_segments"]["mean"]),
    }


def smallest_budget_reaching(
    curve: dict[str, dict], target: float, key: str = "R_mean"
) -> str | None:
    """The first budget, in `budget_order`, whose `key` reaches `target`; None if none do."""
    for budget in budget_order(curve):
        value = curve[budget][key]
        if value is not None and value >= target:
            return budget
    return None


# --- C. provenance --------------------------------------------------------------------------


def frozen_code_check(study: Study) -> dict:
    """Every evaluation's `code_sha256` must equal the frozen pair. Fail loudly otherwise."""
    live = {name: rc.sha256_of(HERE / name) for name in FROZEN_CODE_SHA256}
    edited = {name: digest for name, digest in live.items() if digest != FROZEN_CODE_SHA256[name]}
    if edited:
        changed = "; ".join(
            f"{name} is {digest} not {FROZEN_CODE_SHA256[name]}"
            for name, digest in sorted(edited.items())
        )
        raise ValueError(
            f"the frozen evaluation code has changed on disk: {changed}. The read-out may "
            "not describe artefacts it cannot attribute."
        )
    wrong: list[str] = []
    for (network, model), record in sorted(study.evals.items()):
        if record["code_sha256"] != FROZEN_CODE_SHA256:
            wrong.append(f"results/eval_{network}_{model}.json: {record['code_sha256']}")
    if study.verdicts["code_sha256"] != FROZEN_CODE_SHA256:
        wrong.append(f"results/verdicts.json: {study.verdicts['code_sha256']}")
    if wrong:
        raise ValueError(
            f"{len(wrong)} artefact(s) do not record the frozen evaluation code "
            f"{FROZEN_CODE_SHA256}: " + "; ".join(wrong) + ". The read-out refuses to "
            "summarise results it cannot attribute to the frozen pair."
        )
    return {
        "expected": dict(FROZEN_CODE_SHA256),
        "evaluations_checked": len(study.evals),
        "verdicts_checked": True,
        "all_match": True,
    }


def provenance_block(study: Study) -> dict:
    code = {
        "ratings_core.py": rc.sha256_of(HERE / "ratings_core.py"),
        "run_stage_a.py": rc.sha256_of(HERE / "run_stage_a.py"),
    }
    read_out = {
        READ_OUT_NAME: rc.sha256_of(HERE / READ_OUT_NAME),
        "svgplot.py": rc.sha256_of(MISSION11 / "svgplot.py"),
    }
    controls = {"results/control_d.json": study.control_d["code_sha256"]} | {
        f"results/control_e_{network}.json": payload["code_sha256"]
        for network, payload in sorted(study.control_e.items())
    }
    return {
        "status": rc.STATUS,
        "frozen_code_sha256": code,
        "read_out_code_sha256": read_out,
        "read_out_code_paths": {
            READ_OUT_NAME: f"analysis/asset_rating_information/{READ_OUT_NAME}",
            "svgplot.py": SVGPLOT_RELATIVE,
        },
        "frozen_code_check": frozen_code_check(study),
        "controls_code_sha256": controls,
        "controls_code_sha256_note": (
            "the controls and the decision tables ran on the pre-A3 code, which every "
            "evaluation also records at `tables_code_sha256`; the A1-A3 re-runs touched the "
            "scored evaluation alone, so the control artefacts were not re-run"
        ),
        "protocol": {
            "path": PROTOCOL_RELATIVE,
            "sha256": rc.sha256_of(rc.PROTOCOL),
            "as_executed_sha256": rc.executed_text_sha(rc.PROTOCOL),
            "as_executed_expected": rc.PROTOCOL_SHA256_EXECUTED,
        },
        "inputs_sha256": dict(study.inputs),
        "inputs_counted": {
            "evaluations": len(study.evals),
            "per_draw_npz": len(study.u2p_draws),
            "u2_per_draw_npz": len(study.u2_draws),
            "control_e": len(study.control_e),
        },
    }


# --- D. decision relevance (protocol s. 7's H1) ---------------------------------------------


def decision_relevance_block(study: Study) -> dict:
    out: dict[str, dict] = {}
    classes = study.classes
    for network in study.networks:
        per_model: dict[str, dict] = {}
        for model in study.models(network):
            record = study.record(network, model)
            oracle, base = oracle_and_base(record)
            loss = None if oracle is None or base is None else oracle - base
            b0 = record["policies"]["B0"][DIRECT_KEY]
            b3 = record["b3_vs_b2"]
            per_model[model] = {
                "oracle_export_MWh": oracle,
                "B2_export_MWh": base,
                "B2_loss_MWh": loss,
                "B2_loss_pct_of_oracle": (
                    None if loss is None or not oracle else 100.0 * loss / oracle
                ),
                "B0_unsafe_draw_share": _f(b0["unsafe"]["share_draws_ge1"]),
                "B0_severity_p95_pct": _f(b0["severity_pct"]["p95"]),
                "B3_minus_B2_MWh": _f(b3["export_gap_MWh"]["mean"]),
                "B3_unsafe_draw_share": _f(b3["B3_unsafe"]["share_draws_ge1"]),
            }
        out[network] = {
            "class": classes[network],
            "companion_model": study.companion_model(network),
            "per_model": per_model,
        }
    return out


# --- E. verification (protocol s. 7's H3, H4, H5) -------------------------------------------


def h4_block(record: dict) -> dict:
    """H4's smallest sufficient set and its named candidates, as the record states them."""
    h4 = record.get("h4") or {}
    if not h4.get("available"):
        return {"available": False}
    smallest = h4.get("smallest")
    return {
        "available": True,
        "kmax": h4.get("kmax"),
        "criterion": h4.get("criterion"),
        "smallest": (
            None
            if smallest is None
            else {
                "size": smallest["size"],
                "columns": list(smallest["columns"]),
                "draw_share": _f(smallest["draw_share"]),
                "source": smallest["source"],
            }
        ),
        "named_candidates": [
            {
                "source": candidate["source"],
                "size": candidate["size"],
                "columns": list(candidate["columns"]),
                "draw_share": _f(candidate["draw_share"]),
                "qualifies": candidate["qualifies"],
            }
            for candidate in h4.get("named_candidates", [])
        ],
        "supported": h4.get("supported"),
        "rejected": h4.get("rejected"),
    }


def verification_block(study: Study) -> dict:
    out: dict[str, dict] = {}
    for network in study.cable_limited:
        per_model: dict[str, dict] = {}
        for model in study.models(network):
            record = study.record(network, model)
            oracle, base = oracle_and_base(record)
            gap = None if oracle is None or base is None else oracle - base
            curves: dict[str, dict] = {}
            omitted: dict[str, str] = {}
            for policy, entry in sorted(record["policies"].items()):
                if not _is_budgeted(entry):
                    continue
                budgets = kept_budgets(record, policy, entry)
                if not budgets:
                    # Never a silent drop: the only policy this can reach is OB, which is
                    # omitted outright where the record reports no searched budget for it.
                    omitted[policy] = (
                        "the record scores this policy at budgets but reports no searched "
                        f"budget for it: ob = {record.get('ob')}"
                    )
                    continue
                curves[policy] = {key: recovery_point(entry[key], gap, base) for key in budgets}
            b6 = curves.get("B6", {})
            label = ENERGY_WEIGHTED_LABEL
            if model == U2_PRIME:
                label = f"{label}; {ENERGY_WEIGHTED_U2P_NOTE}"
            per_model[model] = {
                "R": curves,
                "omitted_policies": omitted,
                "OB_searched_kmax": ob_budget_limit(record),
                "B6_smallest_budget_reaching": {
                    f"R_ge_{target}": smallest_budget_reaching(b6, target) for target in B6_TARGETS
                },
                "B6_smallest_budget_reaching_energy_weighted": {
                    f"energy_weighted_ge_{target}": smallest_budget_reaching(
                        b6, target, "recovery_energy_weighted"
                    )
                    for target in B6_TARGETS
                },
                "recovery_energy_weighted_label": label,
                "h4": h4_block(record),
            }
        out[network] = per_model
    return out


# --- F. U2', the misspecification check (protocol s. 5) -------------------------------------


def u2_prime_block(study: Study) -> dict:
    out: dict[str, dict] = {}
    for network in study.cable_limited:
        record = study.record(network, U2_PRIME)
        oracle, base = oracle_and_base(record)
        b2 = record["policies"][BASE_POLICY][DIRECT_KEY]
        at_k4: dict[str, dict] = {}
        ratio_of_means: dict[str, float | None] = {}
        for policy, entry in sorted(record["policies"].items()):
            if _is_budgeted(entry):
                # OB carries its k = 3 set above k = 3 (amendment A3), so k = 4 is not its
                # own result and is left out here as it is in `verification`.
                if K_FOUR not in kept_budgets(record, policy, entry):
                    continue
                budget = K_FOUR
            else:
                budget = DIRECT_KEY
            cell = entry.get(budget)
            if cell is None:
                continue
            mean = _f(cell["export_MWh"]["mean"])
            at_k4[policy] = {
                "budget": budget,
                "export_MWh_mean": mean,
                "unsafe_draw_share": _f(cell["unsafe"]["share_draws_ge1"]),
            }
            gap = None if oracle is None or base is None else oracle - base
            ratio_of_means[policy] = (
                None if mean is None or gap in (None, 0.0) else (mean - base) / gap
            )

        draws = study.u2p_draws[network]
        difference = draws[ORACLE_POLICY] - draws[BASE_POLICY]
        small = (difference > 0) & (difference < U2P_SMALL_GAP_SHARE * draws[ORACLE_POLICY])
        out[network] = {
            "model": U2_PRIME,
            "B2_unsafe": dict(b2["unsafe"]),
            "B2_severity_pct": dict(b2["severity_pct"]),
            "B3_unsafe": dict(record["b3_vs_b2"]["B3_unsafe"]),
            "at_k4": at_k4,
            "per_draw_denominator": {
                "n_draws": int(difference.size),
                "oracle_minus_B2_le_0": int(np.count_nonzero(difference <= 0)),
                "oracle_minus_B2_under_1pct_of_oracle": int(np.count_nonzero(small)),
                "small_gap_share_of_oracle": U2P_SMALL_GAP_SHARE,
                "source": f"runs/eval_{network}_{U2_PRIME}.npz, "
                f"{ORACLE_POLICY}__{DIRECT_KEY}__export and "
                f"{BASE_POLICY}__{DIRECT_KEY}__export",
            },
            "ratio_of_means_recovery": ratio_of_means,
            "ratio_of_means_label": RATIO_OF_MEANS_LABEL,
            "note": (
                "protocol s. 5's U2' draws the truth at w = 0.3 while every deployable policy "
                "believes w = 0.2, so B2 is no longer the conservative floor. The per-draw "
                "recovery R = (policy - B2) / (oracle - B2) is unstable here for two reasons "
                "the counts above make explicit: on some draws the denominator is zero or "
                "negative, and on others it is a small positive fraction of the oracle, which "
                "makes the per-draw ratio large in either sign. The frozen code's per-draw "
                "mean R is reported in `verdicts.json` and is not interpreted here; the "
                "ratio-of-means recovery above is the descriptive substitute."
            ),
        }
    return out


# --- G. complementarity (protocol s. 5's value of information) ------------------------------


def complementarity_block(study: Study) -> dict:
    out: dict[str, dict] = {}
    for network in study.cable_limited:
        record = study.record(network, U2)
        single = [_f(unit["VoI_E"]["expected_MWh"]) or 0.0 for unit in record["voi"]]
        oracle, base = oracle_and_base(record)
        joint = None if oracle is None or base is None else oracle - base
        total = float(sum(single))
        out[network] = {
            "model": U2,
            "n_pool_units": len(single),
            "sum_single_unit_VoI_E_MWh": total,
            "joint_value_MWh": joint,
            "ratio_sum_over_joint": None if not joint else total / joint,
            "definition": (
                "the sum is over the pool units' single-unit VoI_E.expected_MWh; the joint "
                "value is verifying the whole pool, i.e. export(B4) - export(B2) on E"
            ),
        }
    return out


# --- H. the verdicts, copied verbatim -------------------------------------------------------


def verdicts_block(study: Study) -> dict:
    verdicts = study.verdicts
    out: dict[str, object] = {
        "H1.verdict": verdicts["H1"]["verdict"],
        "H2.verdict": verdicts["H2"]["verdict"],
        "H3.H3a.verdict": verdicts["H3"]["H3a"]["verdict"],
        "H3.H3b.verdict": verdicts["H3"]["H3b"]["verdict"],
        "H3.H3c.verdict": verdicts["H3"]["H3c"]["verdict"],
        "H3.H5.verdict": verdicts["H3"]["H5"]["verdict"],
        "H5.verdict": verdicts["H5"]["verdict"],
    }
    for network, block in verdicts["H4"]["per_network"].items():
        out[f"H4.per_network.{network}.verdict"] = block["verdict"]
    out["control_pass"] = dict(verdicts["control_pass"])
    out["stop_conditions"] = dict(verdicts["stop_conditions"])
    out["combinations_missing"] = list(verdicts["combinations_missing"])
    return out


# --- I. amendment A4's two read-out corrections ---------------------------------------------


def _h3a_maximum(study: Study) -> tuple[str, list[str], float, float]:
    """H3a's maximum R_1 over the policies and the qualifying networks, with its SE.

    The maximum is located in `verdicts.json`'s per-network H3a blocks, which hold one entry
    per single-asset ranking (protocol s. 7: B6, B7, B8). Ties are reported together.
    """
    best_network, best_policies, best_mean, best_se = None, [], None, None
    for network, block in study.verdicts["H3"]["per_network"].items():
        h3a = block["H3a"]
        for policy in sorted(key for key in h3a if key != "max_R1"):
            mean = _f(h3a[policy]["mean"])
            if mean is None:
                continue
            if best_mean is None or mean > best_mean:
                best_network, best_policies = network, [policy]
                best_mean, best_se = mean, _f(h3a[policy]["se"])
            elif network == best_network and mean == best_mean:
                best_policies.append(policy)
    if best_mean is None:
        raise ValueError("verdicts.json holds no H3a entry with a mean R_1")
    return best_network, best_policies, best_mean, best_se


def a4_corrections_block(study: Study) -> dict:
    rating_only = study.control_d["rating_only_change"]
    network, policies, max_r1, se = _h3a_maximum(study)
    margin = abs(max_r1 - H3A_REJECT_THRESHOLD)
    two_se = None if se is None else FRAGILE_SE_MULTIPLE * se
    model = study.verdicts["H3"]["model"]
    record = study.record(network, model)
    at_k1 = record["policies"][policies[0]]["1"]["recovery"]
    return {
        "amendment": A4_CITATION,
        "control_D": {
            "source": "results/control_d.json",
            "read_at": "rating_only_change.pass",
            "pass": rating_only["pass"],
            "comparisons": [
                {
                    "quantity": comparison["quantity"],
                    "n": comparison["n"],
                    "max_abs_diff": _f(comparison["max_abs_diff"]),
                    "max_rel_diff": _f(comparison["max_rel_diff"]),
                    "tolerance_rel": _f(comparison["tolerance_rel"]),
                    "within_tolerance": comparison["within_tolerance"],
                }
                for comparison in rating_only["comparisons"]
            ],
            "verdicts_json_controls_D_pass": study.verdicts["controls"]["D"]["pass"],
            "why_null": (
                "`cmd_verdicts` reads `pass` at the top level of results/control_d.json, a key "
                "that does not exist there: the record stores it at rating_only_change.pass, "
                "where it is true"
            ),
            "effect_on_verdicts": (
                "none. Protocol s. 12's stop rule fires on a *failed* Control D, and D passes "
                "in substance, so the rule is correctly not triggered; H2 is analytic"
            ),
            "cites": A4_CITATION,
        },
        "H3a_fragility": {
            "network": network,
            "policies_at_the_maximum": policies,
            "max_R1": max_r1,
            "threshold": H3A_REJECT_THRESHOLD,
            "margin": margin,
            "se": se,
            "two_se": two_se,
            "fragile": None if se is None else bool(rc.fragile(margin, se)),
            "verdict_in_verdicts_json": study.verdicts["H3"]["H3a"]["verdict"],
            "flagged_fragile_in_verdicts_json": "fragile" in study.verdicts["H3"]["H3a"],
            "matches_verdicts_max_R1": (
                max_r1 == _f(study.verdicts["H3"]["H3a"]["max_R1_over_policies_and_networks"])
            ),
            "eval_record_cross_check": {
                "record": f"results/eval_{network}_{model}.json",
                "policy": policies[0],
                "budget": "1",
                "R_mean": _f(at_k1["mean"]),
                "R_se": _f(at_k1["se"]),
            },
            "rule": (
                "protocol s. 9: a verdict whose margin over its threshold is below 2 x the "
                "Monte-Carlo standard error is flagged fragile"
            ),
            "cites": A4_CITATION,
        },
    }


# --- I2. amendment A5's fragility read-out (protocol s. 9) ----------------------------------

FRAGILE_RULE = (
    "protocol s. 9: a verdict whose margin over its threshold is below 2 x the Monte-Carlo "
    "standard error is flagged fragile"
)


def _two_se(se: float | None) -> float | None:
    return None if se is None or se != se else FRAGILE_SE_MULTIPLE * se


def _fragile_flag(margin: float | None, se: float | None) -> bool | None:
    if margin is None or se is None or margin != margin or se != se:
        return None
    return bool(rc.fragile(margin, se))


def _binomial_se(share: float, n: int) -> float | None:
    """The standard error of a share of `n` independent truth draws."""
    if n <= 0:
        return None
    return math.sqrt(share * (1.0 - share) / n)


def h5c_fragility(study: Study) -> dict:
    """H5(c)'s per-network margin over its 0.50 recovery threshold, against 2 x SE."""
    per_network: dict[str, dict] = {}
    fragile: list[str] = []
    for network in study.cable_limited:
        block = study.verdicts["H3"]["per_network"][network]["H5c"]
        recovery, se = _f(block["R"]), _f(block["se"])
        threshold = _f(block["threshold"])
        margin = None if recovery is None or threshold is None else recovery - threshold
        flag = _fragile_flag(margin, se)
        if flag:
            fragile.append(network)
        per_network[network] = {
            "policy": block["policy"],
            "budget": block["budget"],
            "realised_units": _f(block["realised_units"]),
            "R": recovery,
            "se": se,
            "threshold": threshold,
            "margin": margin,
            "two_se": _two_se(se),
            "fragile": flag,
            "holds": block["holds"],
            "fragile_in_verdicts_json": block.get("fragile"),
        }
    return {
        "source": "results/verdicts.json, H3.per_network.<network>.H5c",
        "margin_definition": "R - the 0.50 recovery threshold",
        "per_network": per_network,
        "fragile_networks": fragile,
    }


def h4_fragility(study: Study) -> dict:
    """H4's per-network draw-share margin over 0.95, against 2 x the binomial SE."""
    per_network: dict[str, dict] = {}
    fragile: list[str] = []
    for network in study.cable_limited:
        block = study.verdicts["H4"]["per_network"].get(network) or {}
        per_model: dict[str, dict] = {}
        for model in H4_MODELS:
            h4 = block.get(model) or {}
            smallest = h4.get("smallest")
            if not h4.get("available") or smallest is None:
                # Never a silent drop: a rejected H4 has no sufficient set, so it has no
                # draw-share margin to be fragile about.
                per_model[model] = {
                    "smallest_exists": False,
                    "why": (
                        "the record reports no sufficient set of size <= "
                        f"{h4.get('kmax')}, so there is no draw share to take a margin on"
                    ),
                    "rejected": h4.get("rejected"),
                }
                continue
            share = _f(smallest["draw_share"])
            threshold = _f(h4["criterion"]["draw_share"])
            n_draws = int(study.record(network, model)["sizes"]["n_truth"])
            se = None if share is None else _binomial_se(share, n_draws)
            margin = None if share is None or threshold is None else share - threshold
            flag = _fragile_flag(margin, se)
            if flag:
                fragile.append(f"{network}/{model}")
            per_model[model] = {
                "smallest_exists": True,
                "size": smallest["size"],
                "source": smallest["source"],
                "draw_share": share,
                "threshold": threshold,
                "n_draws": n_draws,
                "se": se,
                "margin": margin,
                "two_se": _two_se(se),
                "fragile": flag,
            }
        per_network[network] = per_model
    return {
        "source": (
            "results/verdicts.json, H4.per_network.<network>.<model>.smallest.draw_share and "
            ".criterion.draw_share; n from results/eval_<network>_<model>.json, sizes.n_truth"
        ),
        "margin_definition": "the smallest sufficient set's draw share - the 0.95 criterion",
        "se_definition": "sqrt(p (1 - p) / n), the binomial SE of a share of n truth draws",
        "models": list(H4_MODELS),
        "per_network": per_network,
        "fragile_network_models": fragile,
    }


def per_draw_recovery(draws: dict[str, np.ndarray], policy: str, budget: str) -> np.ndarray:
    """Protocol s. 7's recovery per truth draw, NaN where the draw's denominator is 0."""
    oracle = draws[export_array_key(ORACLE_POLICY, DIRECT_KEY)]
    base = draws[export_array_key(BASE_POLICY, DIRECT_KEY)]
    export = draws[export_array_key(policy, budget)]
    denominator = oracle - base
    out = np.full(denominator.shape, np.nan, dtype=float)
    usable = denominator != 0.0
    out[usable] = (export[usable] - base[usable]) / denominator[usable]
    return out


def _paired_difference(
    draws: dict[str, np.ndarray], high: tuple[str, str], low: tuple[str, str]
) -> dict:
    """The per-draw difference of two cells' recoveries, with its mean and paired SE."""
    difference = per_draw_recovery(draws, *high) - per_draw_recovery(draws, *low)
    excluded = int(np.count_nonzero(~np.isfinite(difference)))
    paired = rc.paired_summary(difference)
    return {
        "compared": {
            "higher_arm": {"policy": high[0], "budget": high[1]},
            "lower_arm": {"policy": low[0], "budget": low[1]},
        },
        "paired_mean": _f(paired.mean),
        "paired_se": _f(paired.se),
        "n_draws_used": paired.n,
        "n_draws_excluded_zero_denominator": excluded,
    }


def _margin_over_threshold(
    verdict: str, gap: float | None, thresholds: dict
) -> tuple[float | None, float | None, str]:
    """A verdict's margin over the threshold it was decided on (protocol s. 9)."""
    if gap is None:
        return None, None, "no gap is recorded, so no margin is defined"
    if verdict.startswith("REJECTED"):
        return thresholds["reject"] - gap, thresholds["reject"], "rejection threshold - gap"
    if verdict.startswith("SUPPORTED"):
        return gap - thresholds["support"], thresholds["support"], "gap - support threshold"
    return None, None, "an inconclusive verdict has no threshold to take a margin over"


def _paired_fragility(
    study: Study, name: str, arms: dict[str, tuple[tuple[str, str], tuple[str, str]]]
) -> dict:
    """One of H3b and H3c, re-read with a paired standard error instead of a summed one."""
    effect_sizes = study.verdicts["effect_sizes"]
    thresholds = {
        "reject": _f(effect_sizes[f"{name}_reject"]),
        "support": _f(effect_sizes[f"{name}_support"]),
    }
    block = study.verdicts["H3"][name]
    verdict = block["verdict"]
    per_network: dict[str, dict] = {}
    fragile: list[str] = []
    for network in study.cable_limited:
        gap = _f(block["gap_per_network"][network])
        margin, threshold, definition = _margin_over_threshold(verdict, gap, thresholds)
        paired = _paired_difference(study.u2_draws[network], *arms[network])
        flag = _fragile_flag(margin, paired["paired_se"])
        if flag:
            fragile.append(network)
        per_network[network] = {
            **paired,
            "gap_in_verdicts_json": gap,
            "gap_matches_paired_mean": (
                None
                if gap is None or paired["paired_mean"] is None
                else bool(abs(gap - paired["paired_mean"]) <= 1e-12)
            ),
            "threshold": threshold,
            "margin": margin,
            "margin_definition": definition,
            "two_paired_se": _two_se(paired["paired_se"]),
            "fragile_paired": flag,
            "fragile_in_verdicts_json": study.verdicts["H3"]["per_network"][network][name][
                "fragile"
            ],
        }
    return {
        "verdict_in_verdicts_json": verdict,
        "thresholds": thresholds,
        "source": (
            f"runs/eval_<network>_{U2}.npz, the <policy>__<k>__export arrays of the cells "
            "results/verdicts.json records as the compared arms"
        ),
        "per_network": per_network,
        "fragile_networks_paired": fragile,
        "fragile_networks_in_verdicts_json": list(block.get("fragile_networks", [])),
        "verdicts_json_se_label": VERDICTS_SE_LABEL,
    }


def _h3b_arms(study: Study) -> dict[str, tuple[tuple[str, str], tuple[str, str]]]:
    """H3b's compared cells per network, as `verdicts.json` recorded its argmax at the k it
    selected: the structural arm (B8P or B9) against the single-asset arm (B6, B7 or B8)."""
    arms = {}
    for network in study.cable_limited:
        h3b = study.verdicts["H3"]["per_network"][network]["H3b"]
        budget = str(h3b["budget_with_smallest_gap"])
        cell = h3b["per_budget"][budget]
        arms[network] = ((cell["structural"], budget), (cell["single"], budget))
    return arms


def _h3c_arms(study: Study) -> dict[str, tuple[tuple[str, str], tuple[str, str]]]:
    """H3c's compared cells per network: the best targeted policy against B5, at k = 4."""
    return {
        network: (
            (study.verdicts["H3"]["per_network"][network]["H3c"]["best_targeted"], K_FOUR),
            (RANDOM_POLICY, K_FOUR),
        )
        for network in study.cable_limited
    }


def fragility_a5_block(study: Study) -> dict:
    """Amendment A5's four fragility read-outs. No verdict changes; A5 is post-verdict."""
    return {
        "amendment": A5_CITATION,
        "rule": FRAGILE_RULE,
        "no_verdict_changes": A5_NO_VERDICT_CHANGES,
        "post_verdict": (
            "A5 is post-verdict: it was written after results/verdicts.json, which the frozen "
            "code produced from all 36 evaluations. Every flag below is a reading of those "
            "artefacts, so no verdict changes and nothing is re-scored"
        ),
        "H5c": h5c_fragility(study),
        "H4": h4_fragility(study),
        "H3b": _paired_fragility(study, "H3b", _h3b_arms(study)),
        "H3c": _paired_fragility(study, "H3c", _h3c_arms(study)),
        "cites": A5_CITATION,
    }


# --- J. B9's granularity (protocol s. 7's budget matching) ----------------------------------


def b9_granularity_block(study: Study) -> dict:
    out: dict[str, dict] = {}
    for network in study.cable_limited:
        record = study.record(network, U2)
        entry = record["policies"]["B9"]
        budgets = budget_order(entry) if _is_budgeted(entry) else []
        units = {key: _f(entry[key]["realised_units"]["mean"]) for key in budgets}
        first_unit = next(
            (
                key
                for key in budgets
                if key != BUDGET_ALL and units[key] is not None and units[key] > 0
            ),
            None,
        )
        over = next(
            (
                key
                for key in budgets
                if key != BUDGET_ALL and units[key] is not None and units[key] > int(key)
            ),
            None,
        )
        out[network] = {
            "model": U2,
            "realised_units_per_budget": units,
            "smallest_budget_with_a_realised_unit": first_unit,
            "smallest_budget_where_units_exceed_the_budget": over,
            "note": (
                "protocol s. 7's budget-matching rule at work, not a termination. Each policy "
                "enters at its largest realised count <= k, and B9 verifies a whole "
                "co-blocking route in one round, so at every budget below that route's size "
                "the matched state is the empty set: 0 realised units and R = 0. The rule is "
                "why `smallest_budget_where_units_exceed_the_budget` is null -- a matched "
                "state never sits above its budget. Amendment A1 fixed the earlier "
                "termination defect, and the record's own `b9.note` says that 'terminated' "
                "means a round verified nothing new."
            ),
        }
    return out


# --- K. Controls D and E --------------------------------------------------------------------


def controls_d_e_block(study: Study) -> dict:
    rating_only = study.control_d["rating_only_change"]
    changes = rating_only["loading_percent_changes_as_expected"]
    physical = {
        comparison["quantity"]: _f(comparison["max_abs_diff"])
        for comparison in rating_only["comparisons"]
    }
    per_network: dict[str, dict] = {}
    for network, payload in sorted(study.control_e.items()):
        invisible = payload["invisible_overload"]
        delta = payload["distributions"]["vm_abs_delta_all_buses"]
        per_network[network] = {
            "share_invisible": _f(invisible["share_invisible"]),
            "share_of_true_over_that_is_invisible": _f(
                invisible["share_of_true_over_that_is_invisible"]
            ),
            "vm_abs_delta_all_buses": {
                "p95": _f(delta["p95"]),
                "max": _f(delta["max"]),
                "unit": delta["unit"],
                "n": delta["n"],
            },
            "alignment_pass": payload["alignment"]["pass"],
        }
    return {
        "D": {
            "network": study.control_d["network"],
            "max_abs_diff": physical,
            "loading_percent_changes_as_expected": {
                "quantity": changes["quantity"],
                "n": changes["n"],
                "max_abs_diff": _f(changes["max_abs_diff"]),
                "max_rel_diff": _f(changes["max_rel_diff"]),
                "within_tolerance": changes["within_tolerance"],
            },
            "reading": (
                "a rating-only change leaves the electrical state bit-identical: the two "
                "physical quantities differ by exactly 0, and only the loading in % of the "
                "record moves"
            ),
        },
        "E": per_network,
    }


# --- K2. amendment A5's disclosures ---------------------------------------------------------

NO_PARAMETER_DISCLOSURE = (
    "aggregates only: no SimBench parameter value (a rating in kA, an impedance or a cable "
    "type name) is reported, and every written byte is scanned for one"
)


def _voi_worst_case_disclosure(study: Study) -> dict:
    """(a) s. 5's `worst_MWh` is a 100-sample minimum, so it is > 0 in some records."""
    per_model: dict[str, dict] = {}
    for (_, model), record in sorted(study.evals.items()):
        counts = per_model.setdefault(
            model,
            {
                "evaluations": 0,
                "unit_records": 0,
                "unit_records_with_a_positive_worst_case": 0,
                "unit_period_records": 0,
                "unit_period_records_with_a_positive_worst_case": 0,
            },
        )
        counts["evaluations"] += 1
        for unit in record["voi"]:
            worst_p = _f(unit["VoI_P"]["worst_MWh"]) or 0.0
            worst_e = _f(unit["VoI_E"]["worst_MWh"]) or 0.0
            counts["unit_records"] += 1
            counts["unit_period_records"] += 2
            if worst_p > 0.0 or worst_e > 0.0:
                counts["unit_records_with_a_positive_worst_case"] += 1
            counts["unit_period_records_with_a_positive_worst_case"] += int(worst_p > 0.0) + int(
                worst_e > 0.0
            )
    totals = {
        key: sum(counts[key] for counts in per_model.values())
        for key in (
            "evaluations",
            "unit_records",
            "unit_records_with_a_positive_worst_case",
            "unit_period_records",
            "unit_period_records_with_a_positive_worst_case",
        )
    }
    return {
        "per_model": per_model,
        "totals": totals,
        "counted_over": "every voi[] record of all the evaluations read",
        "fields": "voi[].VoI_P.worst_MWh and voi[].VoI_E.worst_MWh",
        "text": (
            "s. 5's `worst_MWh` is the minimum over 100 prior samples, not the infimum over "
            "Theta; s. 1.2's zero worst case concerns the set and holds exactly for U3 and for "
            "zero-VoI units."
        ),
    }


def _control_g_disclosure(study: Study) -> dict:
    """(b) Control G evaluates the first three non-pool columns per combination."""
    per_combination: dict[str, dict] = {}
    for (network, model), record in sorted(study.evals.items()):
        block = record.get("control_g") or {}
        columns = len(block.get("non_pool_table_columns") or [])
        lines = len(block.get("non_table_lines") or [])
        per_combination[f"{network}/{model}"] = {
            "non_pool_table_columns_evaluated": columns,
            "non_table_lines_evaluated": lines,
            "evaluated": columns + lines,
            "zero_value_candidates": block.get("zero_value_candidates"),
        }
    evaluated = sorted({entry["evaluated"] for entry in per_combination.values()})
    return {
        "per_combination": per_combination,
        "evaluated_counts_observed": evaluated,
        "text": (
            "Control G evaluates the first three non-pool columns per combination "
            "(`CONTROL_G_LINES = 3` in the frozen run_stage_a.py). The rest are covered by the "
            "pool certificate, not by a computed VoI."
        ),
    }


def _h4_count_disclosure(study: Study) -> dict:
    """(c) H4's scored counts include the empty set and the named candidates."""
    enumerated = sum(math.comb(H4_TOP_M, size) for size in range(1, H4_ENUMERATED_KMAX + 1))
    per_combination: dict[str, dict] = {}
    for network, block in sorted(study.verdicts["H4"]["per_network"].items()):
        for model in H4_MODELS:
            h4 = block.get(model) or {}
            if not h4.get("available"):
                continue
            per_combination[f"{network}/{model}"] = {
                "subsets_scored": h4.get("subsets_scored"),
                "named_candidate_sources": [
                    candidate["source"] for candidate in h4.get("named_candidates", [])
                ],
            }
    scored = [
        entry["subsets_scored"]
        for entry in per_combination.values()
        if entry["subsets_scored"] is not None
    ]
    return {
        "enumerated_subsets_in_s_10": enumerated,
        "enumeration": (f"sizes 1 to {H4_ENUMERATED_KMAX} over the m = {H4_TOP_M} top candidates"),
        "largest_subsets_scored": max(scored) if scored else None,
        "per_combination": per_combination,
        "text": (
            "H4's scored counts include the empty set and the named B8P / B9-static / B9 "
            f"candidates (up to {max(scored) if scored else 'n/a'}), beyond s. 10's "
            f"{enumerated} enumerated subsets."
        ),
    }


def _control_d_cap_disclosure(study: Study) -> dict:
    """(d) Control D ran at cap level index 0, which is c = 1.0, uncapped."""
    return {
        "cap_level_index": study.control_d.get("cap_level_index"),
        "cap_level": _f(study.control_d.get("cap_level")),
        "source": "results/control_d.json, fields cap_level_index and cap_level",
        "text": (
            "Control D was run at cap level index 0 (c = 1.0, uncapped), which is the first "
            "entry of CAP_LEVELS and not the zero-export level."
        ),
    }


def _h3b_min_over_k_disclosure(study: Study) -> dict:
    """(g) H3b's per-budget gaps never exceed 0.0, so it is rejected at every budget."""
    reject = _f(study.verdicts["effect_sizes"]["H3b_reject"])
    per_network: dict[str, dict] = {}
    largest = None
    for network in study.cable_limited:
        per_budget = study.verdicts["H3"]["per_network"][network]["H3b"]["per_budget"]
        gaps = {budget: _f(cell["gap"]) for budget, cell in sorted(per_budget.items(), key=_by_int)}
        values = [value for value in gaps.values() if value is not None]
        top = max(values) if values else None
        if top is not None:
            largest = top if largest is None else max(largest, top)
        per_network[network] = {
            "gap_per_budget": gaps,
            "largest_gap": top,
            "rejected_at_every_budget": (
                None if not values else all(value <= reject for value in values)
            ),
        }
    return {
        "selected_budget": "the k with the smallest gap (protocol s. 7's conservative choice)",
        "rejection_threshold": reject,
        "largest_gap_over_networks_and_budgets": largest,
        "never_exceeds_zero": None if largest is None else bool(largest <= 0.0),
        "per_network": per_network,
        "source": "results/verdicts.json, H3.per_network.<network>.H3b.per_budget",
        "text": (
            "H3b uses the budget with the smallest gap, but the selection changes nothing "
            "here: the per-budget gaps never exceed 0.0, so H3b is REJECTED at every budget "
            "individually."
        ),
    }


def _by_int(item: tuple[str, object]) -> tuple[int, str]:
    key = item[0]
    return (int(key), key) if key.isdigit() else (1 << 30, key)


def disclosure_block(study: Study) -> dict:
    """Protocol A5's disclosures (a)-(h), each with the counts it rests on."""
    return {
        "amendment": A5_CITATION,
        "no_simbench_parameter_value": NO_PARAMETER_DISCLOSURE,
        "a_VoI_worst_case": _voi_worst_case_disclosure(study),
        "b_control_G_coverage": _control_g_disclosure(study),
        "c_H4_scored_counts": _h4_count_disclosure(study),
        "d_control_D_cap_level": _control_d_cap_disclosure(study),
        "e_P_E_split": (
            "the P/E split validates temporal transfer only: one rho per draw applies to both "
            "periods, so a policy ranked on P is tested on unseen steps of the same truth, not "
            "on an unseen truth."
        ),
        "f_multiple_comparisons": (
            "no multiple-comparison adjustment is made or claimed, although several hypotheses "
            "and several networks are read from the same draw set."
        ),
        "g_H3b_min_over_k": _h3b_min_over_k_disclosure(study),
        "h_amendment_timing": (
            "A1-A3 were made before results/verdicts.json existed and caused re-runs; A4 and "
            "A5 are post-verdict and disclosure only, so they change no scored number and no "
            "verdict."
        ),
    }


# --- L. the whole summary -------------------------------------------------------------------


def build_summary() -> Study:
    study = load_study()
    study.summary = {
        "command": "summarise",
        "status": rc.STATUS,
        "provenance": provenance_block(study),
        "decision_relevance": decision_relevance_block(study),
        "verification": verification_block(study),
        "u2_prime": u2_prime_block(study),
        "complementarity": complementarity_block(study),
        "verdicts": verdicts_block(study),
        "a4_corrections": a4_corrections_block(study),
        "fragility_a5": fragility_a5_block(study),
        "b9_granularity": b9_granularity_block(study),
        "controls_D_E": controls_d_e_block(study),
        "disclosure": disclosure_block(study),
    }
    return study


# --- M. the SimBench parameter guard --------------------------------------------------------


def forbidden_values(study: Study) -> list[float]:
    """The rating values the artefacts carry, which the read-out may never reproduce."""
    values: list[float] = []
    for value in (study.control_d.get("max_i_ka") or {}).values():
        values.append(float(value))
    for payload in study.control_e.values():
        cable = payload.get("modified_cable") or {}
        for key, value in cable.items():
            if key.startswith("max_i_ka"):
                values.append(float(value))
    return sorted(set(values))


def assert_no_simbench_parameters(text: str, values: list[float], where: str) -> None:
    """Refuse any output that carries a `std_type` name or a rating in kA.

    A numeric value is matched only when it is not part of a longer number, so an unrelated
    quantity that happens to start with the same digits is not a false positive. Both the
    short and the full repr of a value are looked for, since the two differ past six
    significant digits.
    """
    for token in FORBIDDEN_TOKENS:
        if token in text:
            raise ValueError(f"{where} carries the forbidden token {token!r}")
    for value in values:
        spellings = {f"{value:g}", repr(value)}
        pattern = "|".join(rf"(?<![\d.]){re.escape(one)}(?!\d)" for one in sorted(spellings))
        if re.search(pattern, text):
            raise ValueError(f"{where} carries the forbidden rating value {value:g}")


# --- N. the figures -------------------------------------------------------------------------


def _categorical(names: list[str]) -> tuple[list[float], list[tuple[float, str]]]:
    positions = [float(index) for index in range(len(names))]
    return positions, list(zip(positions, names, strict=True))


def figure_a(study: Study) -> tuple[str, svgplot.Figure]:
    relevance = study.summary["decision_relevance"]
    names = list(relevance)
    positions, ticks = _categorical(names)
    loss_u2, loss_companion, labels, unsafe = [], [], [], []
    for name in names:
        block = relevance[name]
        companion = block["companion_model"]
        loss_u2.append(_nan(block["per_model"][U2]["B2_loss_pct_of_oracle"]))
        loss_companion.append(_nan(block["per_model"][companion]["B2_loss_pct_of_oracle"]))
        labels.append(companion)
        unsafe.append(_nan(block["per_model"][U2]["B0_unsafe_draw_share"]))
    loss_panel = svgplot.Panel(
        series=[
            svgplot.Series(
                x=positions,
                y=loss_u2,
                label="U2 (w = 0.2)",
                marker="circle",
                colour=svgplot.PALETTE[0],
            ),
            svgplot.Series(
                x=positions,
                y=loss_companion,
                label="U-T or U2 at w = 0.3",
                marker="diamond",
                filled=False,
                colour=svgplot.PALETTE[1],
                point_labels=labels,
            ),
        ],
        title="B2's export loss, in % of the oracle",
        xlabel="network (left to right: transformer-limited, then cable-limited)",
        ylabel="oracle - B2, in % of the oracle",
        xticks=ticks,
        xlim=(-0.5, len(names) - 0.5),
    )
    unsafe_panel = svgplot.Panel(
        series=[
            svgplot.Series(
                x=positions,
                y=unsafe,
                label="B0, U2",
                marker="square",
                colour=svgplot.PALETTE[2],
            )
        ],
        title="B0's unsafe draws under U2",
        xlabel="network",
        ylabel="share of truth draws with >= 1 unsafe E-step",
        xticks=ticks,
        xlim=(-0.5, len(names) - 0.5),
        ylim=(-0.05, 1.08),
    )
    desc = (
        "Protocol s. 7's H1 read-out: how much export the robust interval policy B2 gives up, "
        "and how often the record-trusting policy B0 is unsafe, per network. n = 200 truth "
        "draws per cell; no uncertainty is drawn, because B2's and the oracle's exports are "
        "deterministic given the draw set and the loss is their difference. The second series "
        "is each network's companion model: U-T for the transformer-limited networks and U2 at "
        "w = 0.3 for the cable-limited ones, labelled per point. Source: "
        "results/eval_<network>_<model>.json, fields policies.B4.na.export_MWh.mean, "
        "policies.B2.na.export_MWh.mean and policies.B0.na.unsafe.share_draws_ge1."
    )
    return "fig_a_decision_relevance.svg", svgplot.Figure(
        title="A - Decision relevance of the rating uncertainty",
        desc=desc,
        panels=[loss_panel, unsafe_panel],
        ncols=2,
        panel_width=470.0,
        panel_height=340.0,
        legend_width=180.0,
    )


#: fig_b's curves, in drawing order, with protocol s. 6's own description of each rule
#: (amendment A5: the labels of the first read-out named the wrong rules). B7 and B8 coincide
#: with B6 on every cell here and are not drawn twice.
FIG_B_POLICIES = (
    ("B5", "B5 (random)", "circle"),
    ("B6", "B6 (loading rank; B7 and B8 identical)", "square"),
    ("B8P", "B8P (VoI greedy, pair look-ahead)", "triangle"),
    ("B9", "B9 (route rule)", "diamond"),
    ("OB", "OB (ex-post best, k <= 3)", "cross"),
)
#: The share-of-loss panels share one y range, so the two rows can be read against each other.
#: The range is widened rather than clipped if a value ever sits above it.
FIG_B_YLIM_TOP = 1.1


def _recovery_ylim(panels_values: list[float]) -> tuple[float, float]:
    finite = [value for value in panels_values if value == value]
    top = max(finite) if finite else 1.0
    return (-0.05, max(FIG_B_YLIM_TOP, top + 0.05))


def _fig_b_series(curve_set: dict[str, dict], value_key: str) -> list[svgplot.Series]:
    """One panel's series: a connected curve over the numeric budgets, and the full pool as an
    isolated marker. Amendment A5: no budget between the last k and the full pool was scored,
    so a segment to the "all" point would draw an interpolation that was never computed."""
    series: list[svgplot.Series] = []
    for index, (policy, label, marker) in enumerate(FIG_B_POLICIES):
        curve = curve_set.get(policy)
        if not curve:
            continue
        colour = svgplot.PALETTE[index % len(svgplot.PALETTE)]
        budgets = budget_order(curve)
        numeric = [key for key in budgets if key != BUDGET_ALL]
        series.append(
            svgplot.Series(
                x=[_nan(curve[key]["realised_units"]) for key in numeric],
                y=[_nan(curve[key][value_key]) for key in numeric],
                label=label,
                kind="line+marker",
                marker=marker,
                colour=colour,
            )
        )
        if BUDGET_ALL in budgets:
            cell = curve[BUDGET_ALL]
            series.append(
                svgplot.Series(
                    x=[_nan(cell["realised_units"])],
                    y=[_nan(cell[value_key])],
                    label="",  # the policy is already in the legend; this is the same policy
                    kind="marker",
                    marker=marker,
                    colour=colour,
                )
            )
    return series


def _fig_b_panel(
    network: str, curve_set: dict[str, dict], value_key: str, title: str, ylabel: str
) -> svgplot.Panel:
    series = _fig_b_series(curve_set, value_key)
    values = [value for one in series for value in one.y]
    return svgplot.Panel(
        series=series,
        title=f"{network} (U2): {title}",
        xlabel="realised verifications (pool units)",
        ylabel=ylabel,
        ylim=_recovery_ylim(values),
        hlines=[(0.5, "H5(c)'s 0.5"), (1.0, "the oracle")],
    )


def figure_b(study: Study) -> tuple[str, svgplot.Figure]:
    verification = study.summary["verification"]
    rows = (
        ("R_mean", "per-draw recovery", "R, the recovered share of B2's loss"),
        (
            "recovery_energy_weighted",
            "energy-weighted recovery",
            "energy-weighted recovered share",
        ),
    )
    panels = [
        _fig_b_panel(network, per_model[U2]["R"], value_key, title, ylabel)
        for value_key, title, ylabel in rows
        for network, per_model in verification.items()
    ]
    desc = (
        "Protocol s. 7's recovery on the cable-limited networks under U2, against the policy's "
        "realised verification count rather than its requested budget (s. 6: a policy that "
        "adds pairs or paths may overshoot), n = 200 truth draws. Top row: s. 7's per-draw "
        "recovery (the verdict statistic). Bottom row: the energy-weighted recovery (A5, "
        "descriptive). The marker at the full pool is not connected; no budget between the "
        "last k and the full pool was scored. B7 and B8 coincide with B6 on every cell here "
        "and are not drawn twice. OB is the ex-post best set and is searched to k <= 3 only "
        "(amendment A3), so its curve stops there. No uncertainty is drawn; the standard "
        "errors are in results/stage_a_summary.json, verification.<network>.U2.R. Source: "
        "results/eval_<network>_U2.json, fields policies.<policy>.<k>.recovery.mean, "
        "policies.<policy>.<k>.export_MWh.mean and policies.<policy>.<k>.realised_units.mean."
    )
    return "fig_b_verification_curves.svg", svgplot.Figure(
        title="B - What verification recovers, against how much of it is done",
        desc=desc,
        panels=panels,
        ncols=max(1, len(verification)),
        panel_width=450.0,
        panel_height=360.0,
        legend_width=205.0,
    )


#: fig_c's policies: the references of protocol s. 7, plus B6 at the H5(c) budget.
FIG_C_DIRECT = ("B0", "B1", "B2", "B3", "B4")


def figure_c(study: Study) -> tuple[str, svgplot.Figure]:
    panels = []
    for network in study.cable_limited:
        record = study.record(network, U2)
        oracle, _ = oracle_and_base(record)
        xs, ys, labels = [], [], []
        for policy, label in [
            *((name, name) for name in FIG_C_DIRECT),
            ("B6", f"B6 at k = {K_FOUR}"),
        ]:
            budget = K_FOUR if policy == "B6" else DIRECT_KEY
            entry = record["policies"][policy].get(budget)
            if entry is None:
                continue
            xs.append(_nan(entry["unsafe"]["unsafe_step_share"]))
            share = None if not oracle else 100.0 * _nan(entry["export_MWh"]["mean"]) / oracle
            ys.append(_nan(share))
            labels.append(label)
        panels.append(
            svgplot.Panel(
                series=[
                    svgplot.Series(
                        x=xs,
                        y=ys,
                        label="policy",
                        marker="circle",
                        colour=svgplot.PALETTE[0],
                        point_labels=labels,
                    )
                ],
                title=f"{network} (U2)",
                xlabel="unsafe E-steps / E-steps (mean over draws)",
                ylabel="export, in % of the oracle",
                hlines=[(100.0, "the oracle")],
            )
        )
    desc = (
        "The safety-utilisation plane on the cable-limited networks under U2, n = 200 truth "
        "draws. y = the policy's mean export as a percentage of the oracle's (B4's); x = the "
        "mean share of E-steps that are unsafe. B0 trusts the record and buys its export with "
        "unsafe steps; B2 is safe and gives export up; B6 at k = 4 is the H5(c) cell, which "
        "buys most of the gap back with four verifications and no unsafe step. No uncertainty "
        "is drawn: these are the means of the two read-outs. Source: "
        "results/eval_<network>_U2.json, fields policies.<policy>.<budget>.export_MWh.mean "
        "and policies.<policy>.<budget>.unsafe.unsafe_step_share."
    )
    return "fig_c_safety_utilisation.svg", svgplot.Figure(
        title="C - Export against unsafe steps, per policy",
        desc=desc,
        panels=panels,
        ncols=3,
        panel_width=450.0,
        panel_height=360.0,
        legend_width=160.0,
    )


def _and_list(parts: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`: a reading list, not a JSON list."""
    if len(parts) < 3:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _two_significant(value: float) -> str:
    """A positive number to two significant figures, written out rather than in exponent form
    (`280`, not `2.8e+02`), with a trailing zero dropped."""
    if value <= 0.0:
        return f"{value:g}"
    places = 1 - math.floor(math.log10(value))  # negative above 100: round to tens, hundreds
    decimals = max(0, places)
    text = f"{round(value, places):.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _complementarity_sentence(block: dict) -> str:
    """Figure D's claim about the size of the gap, **computed from the recorded ratios**.

    The multiples are 1 / `ratio_sum_over_joint`, to two significant figures, so the sentence
    cannot drift from the numbers the figure draws. A network whose joint value is missing or
    zero carries no ratio and is left out of the span.
    """
    usable = [(name, body["ratio_sum_over_joint"]) for name, body in block.items()]
    usable = [(name, ratio) for name, ratio in usable if ratio]
    if not usable:
        return "no network here carries a usable sum / joint ratio, so the gap is not sized"
    multiples = sorted(1.0 / ratio for _, ratio in usable)
    low, high = _two_significant(multiples[0]), _two_significant(multiples[-1])
    span = (
        f"about {low} times less" if low == high else f"between about {low} and {high} times less"
    )
    ratios = _and_list([f"{ratio:.2g}" for _, ratio in usable])
    networks = _and_list([name for name, _ in usable])
    return (
        f"verifying one cable at a time is worth {span} than verifying the pool "
        f"(sum / joint = {ratios} for {networks})"
    )


def figure_d(study: Study) -> tuple[str, svgplot.Figure]:
    """Amendment A5: the two values differ by more than an order of magnitude, so they are
    drawn as two series per network on one logarithmic MWh axis rather than as a scatter of one
    against the other. The ratio is printed per network, and there is no y = x line. The size
    of the gap in the description is computed from the ratios by `_complementarity_sentence`,
    never asserted."""
    block = study.summary["complementarity"]
    names = list(block)
    positions, ticks = _categorical(names)
    sums = [_nan(block[name]["sum_single_unit_VoI_E_MWh"]) for name in names]
    joints = [_nan(block[name]["joint_value_MWh"]) for name in names]
    ratios = [block[name]["ratio_sum_over_joint"] for name in names]
    drawn = [value for value in [*sums, *joints] if value == value]
    logarithmic = bool(drawn) and all(value > 0.0 for value in drawn)
    panel = svgplot.Panel(
        series=[
            svgplot.Series(
                x=positions,
                y=sums,
                label="sum of the single-unit VoI_E",
                marker="circle",
                colour=svgplot.PALETTE[0],
                point_labels=[
                    "" if ratio is None else f"sum / joint = {ratio:.2g}" for ratio in ratios
                ],
            ),
            svgplot.Series(
                x=positions,
                y=joints,
                label="joint value: oracle - B2 on E",
                marker="diamond",
                filled=False,
                colour=svgplot.PALETTE[1],
            ),
        ],
        title="single-unit value and the joint value of the pool, per network",
        xlabel="cable-limited network (U2)",
        ylabel="MWh (logarithmic)" if logarithmic else "MWh (linear)",
        ylog=logarithmic,
        xticks=ticks,
        xlim=(-0.5, len(names) - 0.5),
        note=(
            ""
            if logarithmic
            else "a non-positive value is drawn, so the axis is linear rather than logarithmic"
        ),
    )
    desc = (
        "Protocol s. 5's value of information is complementary, not additive, on these "
        f"networks: {_complementarity_sentence(block)}, because the series segments co-block. "
        "The filled marker "
        "sums the pool units' single-unit VoI_E.expected_MWh over n = 100 prior samples; the "
        "hollow marker is the joint value, export(B4) - export(B2) on E over n = 200 truth "
        "draws. The two have different draw sets by construction, which is why they are shown "
        "as a pair and not as a difference, and the ratio of the two is printed per network. "
        "The y axis is logarithmic in MWh. No uncertainty is drawn. Source: "
        "results/eval_<network>_U2.json, fields voi[].VoI_E.expected_MWh, "
        "policies.B4.na.export_MWh.mean and policies.B2.na.export_MWh.mean."
    )
    return "fig_d_complementarity.svg", svgplot.Figure(
        title="D - Single-unit value against the joint value of the pool",
        desc=desc,
        panels=[panel],
        panel_width=560.0,
        panel_height=380.0,
        legend_width=220.0,
    )


#: fig_e's models: B6's curve against the budget, plus U4's single route unit.
FIG_E_CURVES = ((U2, "U2 (w = 0.2)"), (U2_W3, "U2 at w = 0.3"), ("U3", "U3 (class ambiguity)"))
FIG_E_POINT = ("U4", "U4 (one route unit, at its realised count)")


def figure_e(study: Study) -> tuple[str, svgplot.Figure]:
    panels = []
    for network, per_model in study.summary["verification"].items():
        series = []
        for index, (model, label) in enumerate(FIG_E_CURVES):
            curve = (per_model.get(model) or {}).get("R", {}).get("B6")
            if not curve:
                continue
            budgets = [key for key in budget_order(curve) if key != BUDGET_ALL]
            series.append(
                svgplot.Series(
                    x=[float(key) for key in budgets],
                    y=[_nan(curve[key]["R_mean"]) for key in budgets],
                    label=f"B6, {label}",
                    kind="line+marker",
                    colour=svgplot.PALETTE[index % len(svgplot.PALETTE)],
                )
            )
        model, label = FIG_E_POINT
        curve = (per_model.get(model) or {}).get("R", {}).get("B6")
        if curve:
            cell = curve[budget_order(curve)[0]]
            segments = cell["realised_segments"]
            series.append(
                svgplot.Series(
                    x=[_nan(cell["realised_units"])],
                    y=[_nan(cell["R_mean"])],
                    label=f"B6, {label}",
                    marker="cross",
                    colour=svgplot.PALETTE[len(FIG_E_CURVES) % len(svgplot.PALETTE)],
                    point_labels=["" if segments is None else f"{segments:.0f} segments"],
                )
            )
        panels.append(
            svgplot.Panel(
                series=series,
                title=f"{network}",
                xlabel="budget k (verifications requested; B6 realises exactly k)",
                ylabel="R, the recovered share of B2's loss",
                ylim=(-0.05, 1.1),
                hlines=[(0.5, "H5(c)'s 0.5"), (1.0, "the oracle")],
            )
        )
    desc = (
        "How B6's recovery depends on the uncertainty model, per cable-limited network, n = 200 "
        "truth draws. The three curves are B6 against its budget under U2, under U2 at w = 0.3 "
        "and under U3's discrete class ambiguity; B6 realises exactly k on these cells, so the "
        "budget is also its realised count. U4 is a single point, because the whole pool lies "
        "in one route there: verifying that one route unit resolves the network by construction, "
        "and the point is placed at its realised unit count with its segment count labelled. No "
        "uncertainty is drawn; the standard errors are in results/stage_a_summary.json, "
        "verification.<network>.<model>.R.B6. Source: results/eval_<network>_<model>.json, "
        "fields policies.B6.<k>.recovery.mean and policies.B6.<k>.realised_units.mean."
    )
    return "fig_e_model_sensitivity.svg", svgplot.Figure(
        title="E - B6's recovery across the uncertainty models",
        desc=desc,
        panels=panels,
        ncols=3,
        panel_width=450.0,
        panel_height=360.0,
        legend_width=185.0,
    )


def figure_f(study: Study) -> tuple[str, svgplot.Figure]:
    block = study.summary["controls_D_E"]
    names = list(block["E"])
    positions, ticks = _categorical(names)
    control_d_network = block["D"]["network"]
    d_zero = max(abs(value or 0.0) for value in block["D"]["max_abs_diff"].values())
    share_panel = svgplot.Panel(
        series=[
            svgplot.Series(
                x=positions,
                y=[_nan(block["E"][name]["share_invisible"]) for name in names],
                label="invisible of all step-levels",
                marker="circle",
                colour=svgplot.PALETTE[0],
            ),
            svgplot.Series(
                x=positions,
                y=[
                    _nan(block["E"][name]["share_of_true_over_that_is_invisible"]) for name in names
                ],
                label="invisible of the truly overloaded",
                marker="square",
                filled=False,
                colour=svgplot.PALETTE[1],
            ),
        ],
        title="Control E: overloads the nominal model cannot see",
        xlabel="network",
        ylabel="share of step-levels",
        xticks=ticks,
        xlim=(-0.5, len(names) - 0.5),
        ylim=(-0.05, 1.05),
    )
    vm_panel = svgplot.Panel(
        series=[
            svgplot.Series(
                x=positions,
                y=[_nan(block["E"][name]["vm_abs_delta_all_buses"]["p95"]) for name in names],
                label="Control E, |dvm| p95",
                marker="circle",
                colour=svgplot.PALETTE[2],
            ),
            svgplot.Series(
                x=positions,
                y=[_nan(block["E"][name]["vm_abs_delta_all_buses"]["max"]) for name in names],
                label="Control E, |dvm| max",
                marker="triangle",
                filled=False,
                colour=svgplot.PALETTE[3],
            ),
            svgplot.Series(
                x=[float(names.index(control_d_network))] if control_d_network in names else [],
                y=[d_zero] if control_d_network in names else [],
                label="Control D, max |dvm| and |dI| (exactly 0)",
                marker="cross",
                colour=svgplot.PALETTE[5],
            ),
        ],
        title="Control D's zero against Control E's measured change",
        xlabel="network",
        ylabel="|change| in bus voltage magnitude (p.u.)",
        xticks=ticks,
        xlim=(-0.5, len(names) - 0.5),
    )
    desc = (
        "Protocol s. 8's Controls D and E, which together carry H2. Control D changes one "
        "cable's rating alone and the electrical state does not move: the largest absolute "
        "change in res_bus.vm_pu and in res_line.i_ka is exactly 0, at n = 2 AC solves on one "
        "network, so electrical data carry no information about a rating-only error. Control E "
        "changes an impedance as well as the rating, and the state does move: the voltage "
        "change is drawn as its 95th percentile and its maximum over every bus and step, and "
        "the left panel shows how often the resulting overload is invisible to the nominal "
        "model. No uncertainty is drawn; both controls are deterministic comparisons of "
        "complete cached years. Source: results/control_d.json, field "
        "rating_only_change.comparisons, "
        "and results/control_e_<network>.json, fields invisible_overload and "
        "distributions.vm_abs_delta_all_buses."
    )
    return "fig_f_controls_d_e.svg", svgplot.Figure(
        title="F - A rating-only change is invisible; an impedance change is not",
        desc=desc,
        panels=[share_panel, vm_panel],
        ncols=2,
        panel_width=470.0,
        panel_height=350.0,
        legend_width=215.0,
    )


FIGURE_BUILDERS = (figure_a, figure_b, figure_c, figure_d, figure_e, figure_f)


def build_figures(study: Study) -> list[tuple[str, str]]:
    """Every figure as (filename, svg text). Nothing is written to disk here.

    This is the figure-writing entry point, so it is where `svgplot`'s notice global is pointed
    at Mission 12's attribution file (amendment A5). The previous value is restored in the
    `finally`, so a caller that draws a Mission 11 figure after this call still gets Mission
    11's notice.
    """
    values = forbidden_values(study)
    previous_notice = svgplot.ATTRIBUTION_NOTICE
    svgplot.ATTRIBUTION_NOTICE = ATTRIBUTION_NOTICE
    out = []
    try:
        for build in FIGURE_BUILDERS:
            name, figure = build(study)
            text = figure.to_svg()
            assert_no_simbench_parameters(text, values, name)
            out.append((name, text))
    finally:
        svgplot.ATTRIBUTION_NOTICE = previous_notice
    return out


def build_one_figure(study: Study, name: str) -> str:
    """One named figure's SVG text, under the same notice and parameter guard as the set.

    Only the named figure is rendered and only its text is guarded; the builders ahead of it in
    `FIGURE_BUILDERS` are called for their file name alone, which is how the known names are
    reported when nothing matches.
    """
    values = forbidden_values(study)
    previous_notice = svgplot.ATTRIBUTION_NOTICE
    svgplot.ATTRIBUTION_NOTICE = ATTRIBUTION_NOTICE
    known: list[str] = []
    try:
        for build in FIGURE_BUILDERS:
            built, figure = build(study)
            known.append(built)
            if built != name:
                continue
            text = figure.to_svg()
            assert_no_simbench_parameters(text, values, built)
            return text
    finally:
        svgplot.ATTRIBUTION_NOTICE = previous_notice
    raise ValueError(f"no figure is named {name!r}; this read-out draws {', '.join(known)}")


# --- O. the command line --------------------------------------------------------------------


def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    raise TypeError(f"{type(obj).__name__} is not JSON-serialisable")


def _write_once_svg(path: Path, text: str) -> Path:
    if path.exists():
        raise FileExistsError(f"{path} exists; figures are written once and never rewritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def command_summarise(dry_run: bool) -> int:
    study = build_summary()
    values = forbidden_values(study)
    payload = study.summary
    text = json.dumps(payload, indent=2, sort_keys=True, default=_json_default)
    assert_no_simbench_parameters(text, values, SUMMARY_NAME)
    figures = build_figures(study)
    if dry_run:
        print(text)
        print(f"\n[dry run] {summary_path()} not written", file=sys.stderr)
        for name, svg in figures:
            print(f"[dry run] {name}: {len(svg)} bytes", file=sys.stderr)
        return 0
    path = rc.write_json_once(summary_path(), payload)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    print(f"sha256 {rc.sha256_of(path)}")
    for name, svg in figures:
        written = _write_once_svg(FIGURES / name, svg)
        print(f"wrote {written} ({written.stat().st_size} bytes) sha256 {rc.sha256_of(written)}")
    return 0


def _listed_combinations(listed: dict[str, str]) -> set[tuple[str, str]]:
    """The (network, model) pairs the summary's `results/eval_*.json` keys name."""
    out = set()
    for key in listed:
        name = key.split("/")[-1]
        match = EVAL_RE.match(name)
        if match is not None and key.startswith(f"{RESULTS.name}/"):
            out.add((match["network"], match["model"]))
    return out


def _unexpected_extras(listed: dict[str, str]) -> list[str]:
    """Scored artefacts on disk that the frozen summary does not account for.

    A `results/eval_*.json` must be listed by name: all 36 are read. A `runs/eval_*.npz` is
    held to its combination instead, because the read-out opens only the six arrays amendment
    A5 needs and so lists only those six; an npz is an extra when **no** evaluation of that
    (network, model) is in the summary at all.
    """
    combinations = _listed_combinations(listed)
    extras = []
    for path in sorted(RESULTS.glob("eval_*.json")):
        if _input_key(path) not in listed:
            extras.append(f"{_input_key(path)} is not listed in the summary")
    for path in sorted(RUNS.glob("eval_*.npz")):
        match = EVAL_RE.match(path.name.replace(".npz", ".json"))
        if match is None:
            extras.append(f"{_input_key(path)} is not named eval_<network>_<model>.npz")
        elif (match["network"], match["model"]) not in combinations:
            extras.append(f"{_input_key(path)} has no evaluation in the summary")
    return extras


def command_verify() -> int:
    """Read-only: the frozen summary against its pin, then every input it names. Writes
    nothing, recomputes nothing, and reports one line per check."""
    path = summary_path()
    failures: list[str] = []
    if not path.exists():
        print(f"FAIL {_input_key(path)}: missing")
        print(f"verify: FAILED ({path} is missing)", file=sys.stderr)
        return 1
    digest = rc.sha256_of(path)
    if digest == PINNED_SUMMARY_SHA256:
        print(f"ok   {_input_key(path)} sha256 {digest} (pinned)")
    else:
        failures.append(f"{_input_key(path)}: sha256 {digest}, pinned {PINNED_SUMMARY_SHA256}")
        print(f"FAIL {_input_key(path)}: sha256 {digest} is not the pin")
    try:
        listed = dict(_load_json(path)["provenance"]["inputs_sha256"])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"FAIL {_input_key(path)}: no readable provenance.inputs_sha256 ({error})")
        print("verify: FAILED (1 failure)", file=sys.stderr)
        return 1
    for key, expected in sorted(listed.items()):
        target = _input_path(key)
        if not target.exists():
            failures.append(f"{key}: missing")
            print(f"FAIL {key}: missing")
            continue
        found = rc.sha256_of(target)
        if found == expected:
            print(f"ok   {key} sha256 {found}")
        else:
            failures.append(f"{key}: sha256 {found}, recorded {expected}")
            print(f"FAIL {key}: sha256 {found} is not the recorded {expected}")
    for extra in _unexpected_extras(listed):
        failures.append(f"unexpected extra: {extra}")
        print(f"FAIL unexpected extra: {extra}")
    if failures:
        for failure in failures:
            print(f"verify: FAILED -- {failure}", file=sys.stderr)
        print(f"verify: FAILED ({len(failures)} of {len(listed) + 1} checks)", file=sys.stderr)
        return 1
    print(f"verify: OK ({len(listed) + 1} files)")
    return 0


def canonical_summary(payload: dict) -> str:
    """The summary as canonical JSON, with the read-out's own hashes dropped.

    `provenance.read_out_code_sha256` is this module's sha256, which necessarily differs once
    this module is edited. Everything else must be byte-identical, which is what makes a
    single regenerated figure provably a redraw of the frozen numbers.
    """
    out = dict(payload)
    provenance = dict(out.get("provenance") or {})
    provenance.pop("read_out_code_sha256", None)
    out["provenance"] = provenance
    return json.dumps(out, indent=2, sort_keys=True, default=_json_default)


def assert_summary_unchanged(study: Study) -> None:
    """Refuse to redraw unless the recomputed summary is the stored one."""
    path = summary_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; a figure may only be redrawn from it")
    stored = canonical_summary(_load_json(path))
    if canonical_summary(study.summary) != stored:
        raise ValueError(
            f"the recomputed summary differs from {path} outside "
            "provenance.read_out_code_sha256; a figure may not be redrawn on numbers the "
            "frozen summary does not record. Re-check the artefacts before drawing."
        )


def command_figure(name: str) -> int:
    """Redraw exactly one figure from the frozen summary's numbers. Write-once."""
    if name != Path(name).name:
        raise ValueError(f"--name takes a file name, not a path: {name!r}")
    study = build_summary()
    assert_summary_unchanged(study)
    print(f"recomputed summary matches {summary_path()} (read-out hash excluded)")
    text = build_one_figure(study, name)
    written = _write_once_svg(FIGURES / name, text)
    print(f"wrote {written} ({written.stat().st_size} bytes) sha256 {rc.sha256_of(written)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("summarise", "verify", "figure"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and print without writing, so each write-once artefact is written once",
    )
    parser.add_argument(
        "--name",
        help="the single figure `figure` redraws, as a file name, e.g. fig_d_complementarity.svg",
    )
    args = parser.parse_args(argv)
    rc.check_protocol()
    if args.command == "verify":
        return command_verify()
    if args.command == "figure":
        if not args.name:
            parser.error("figure needs --name <file name>")
        return command_figure(args.name)
    return command_summarise(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
