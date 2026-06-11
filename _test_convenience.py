#!/usr/bin/env python3
"""Regression test for the Convenient Lab Result Groupings statistical engine.
Validates the pure-Python statistics against known reference values and checks the
scoring/banding + min-sample rules. Run: python3 _test_convenience.py"""
import math
import cannascope_ct_v17_src as M

_fails = []
def ok(msg): print("ok   ", msg)
def approx(label, got, want, tol):
    if abs(got - want) <= tol:
        ok(f"{label}: {got:.6f} ~= {want:.6f}")
    else:
        _fails.append(f"{label}: {got:.6f} != {want:.6f} (tol {tol})"); print("FAIL ", _fails[-1])
def eq(label, got, want):
    if got == want: ok(f"{label}: {got}")
    else: _fails.append(f"{label}: {got} != {want}"); print("FAIL ", _fails[-1])

# ---- statistics vs known references ----
approx("binomial P(X>=8 | 10,0.5)", M._cg_binom_sf_ge(8, 10, 0.5), 0.0546875, 1e-6)
approx("z-enrichment (8/10 vs .5)", M._cg_z_enrich(8, 10, 0.5), 1.8973666, 1e-4)
approx("chi2 sf(3.841, 1)", M._cg_chi2_sf(3.841, 1), 0.05, 2e-3)
approx("chi2 sf(11.07, 5)", M._cg_chi2_sf(11.07, 5), 0.05, 2e-3)
approx("fisher [[8,2],[2,8]]", M._cg_fisher_2x2(8, 2, 2, 8), 0.02301, 5e-4)
# edge cases must not explode
eq("binom k>n -> 0", M._cg_binom_sf_ge(5, 3, 0.1), 0.0)
eq("binom k<=0 -> 1", M._cg_binom_sf_ge(0, 10, 0.1), 1.0)
eq("z n=0 -> 0", M._cg_z_enrich(0, 0, 0.1), 0.0)
eq("chi2 dof<=0 -> 1", M._cg_chi2_sf(5.0, 0), 1.0)

# ---- band index ----
eq("band 10% -> 0", M._cg_band_index(10.0), 0)
eq("band 96% -> 4 (95-99)", M._cg_band_index(96.0), 4)
eq("band 99.5% -> 5 (99-100)", M._cg_band_index(99.5), 5)
eq("band 105% -> over", M._cg_band_index(105.0), len(M.CG_BANDS))

# ---- score bands + min-sample caps ----
eq("score 95 -> extreme", M._cg_score_band(95), "Extreme boundary clustering")
eq("score 10 -> normal", M._cg_score_band(10), "Normal variation")
# strong score requires >=3 near; with near<3 the score is capped below 50
s_lown = M._cg_convenience_score(near=1, n=2, over=0, ratio=5.0, pval=0.0001, z=6.0,
                                 round_cluster=1.0, low_n=True)
if s_lown <= 24: ok(f"low-N capped to <=24: {s_lown}")
else: _fails.append(f"low-N not capped: {s_lown}"); print("FAIL ", _fails[-1])
s_fewnear = M._cg_convenience_score(near=2, n=50, over=0, ratio=5.0, pval=0.0001, z=6.0,
                                    round_cluster=1.0, low_n=False)
if s_fewnear <= 49: ok(f"<3 near capped to <50: {s_fewnear}")
else: _fails.append(f"few-near not capped: {s_fewnear}"); print("FAIL ", _fails[-1])
# a strong, significant, cliff-effect group should score high
s_strong = M._cg_convenience_score(near=14, n=20, over=0, ratio=6.0, pval=0.0001, z=6.0,
                                   round_cluster=0.8, low_n=False)
if s_strong >= 75: ok(f"strong cliff group scores high: {s_strong}")
else: _fails.append(f"strong group too low: {s_strong}"); print("FAIL ", _fails[-1])

# ISSUE #20/#21 — significance GATES the score+band: a non-significant p never reads as real clustering.
s_p089 = M._cg_convenience_score(near=14, n=391, over=0, ratio=2.0, pval=0.089, z=3.0,
                                 round_cluster=0.0, low_n=False)
if s_p089 < 50: ok(f"p=0.089 capped below 'Review recommended': {s_p089}")
else: _fails.append(f"p=0.089 not capped: {s_p089}"); print("FAIL ", _fails[-1])
eq("p>=0.05 band is 'not significant'", M._cg_score_band(49, 0.089),
   "Not statistically significant (review lead only)")
eq("p>=0.10 score capped to <=24",
   min(99, M._cg_convenience_score(near=10, n=300, over=0, ratio=2.0, pval=0.259, z=2.5,
                                   round_cluster=0.0, low_n=False)) <= 24, True)
eq("significant strong group keeps clustering band", M._cg_score_band(80, 0.001), "Strong clustering")

# --- S8/S10 screens (full remediation pass) ---
eq("sig tier <0.001", M.significance_tier(0.0005), "highly significant (p<0.001)")
eq("sig tier 0.2 not significant", "not statistically significant" in M.significance_tier(0.2), True)
_lo, _hi = M._wilson_ci(5, 100)
eq("wilson(5,100) brackets 5%", _lo <= 5 <= _hi, True)
_ss = M.statistical_screens([97000, 98000, 99000] * 4 + [50000 + i * 137 for i in range(30)])
eq("screens scored (not low-sample)", _ss.get("low_sample", False), False)
eq("round-thousand rate > 0", _ss["round_thousand_rate"] > 0, True)
eq("low-sample guard", M.statistical_screens([1, 2, 3]).get("low_sample"), True)

print("\n" + ("ALL PASSED" if not _fails else f"{len(_fails)} FAILED"))
raise SystemExit(1 if _fails else 0)
