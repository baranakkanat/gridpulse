Written 2026-10-17T13:35:59Z, BEFORE running the network survey.

Survey scope: 1-LV-{rural1,rural2,rural3,semiurb4,semiurb5,urban6}--{0,1,2}-sw, simbench 1.6.3,
benchmark taps made effective, storage idle (0 MW), PV q = 0 (as published), development half
only: UTC days 0..181 (2016-01-01 .. 2016-06-30). Two flows per step: no action, PV cap 0.
No policy is run; no evaluation-half (Jul-Dec) data are computed or inspected.

Eligibility of a network for the dual-uncertainty study (primary set = scenario --2 of each
topology, as in Phase 3; --0/--1 variants are descriptive only):
 E1 no non-converged flow in the development half at no action;
 E2 >= 50 PV-driven violation steps in the development half (violation at no action and none
    at PV cap 0), so that a curtailment decision problem exists;
 E3 violations that persist at PV cap 0 (load-driven, not addressable by PV curtailment) are
    reported separately and excluded from the decision problem's primary violation count.
Networks failing E1 or E2 are reported and excluded, not tuned or modified to pass.
