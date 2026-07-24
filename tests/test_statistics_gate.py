from domain.assurance.statistics_gate import StatisticsGate
def test_single_seed_stable_ml_claim_is_blocked():
 r=StatisticsGate().ml(seeds=1,ci=True,effect_size=True,baseline=True,ablation=True,leakage_checked=True,metric_direction='higher',stable_claim=True);assert not r.passed and 'single seed' in r.issues[0]
def test_complete_ml_profile_passes():
 assert StatisticsGate().ml(seeds=3,ci=True,effect_size=True,baseline=True,ablation=True,leakage_checked=True,metric_direction='higher',stable_claim=True).passed
def test_causal_claim_without_identification_is_blocked():
 r=StatisticsGate().causal(estimand='ATE',treatment='T',outcome='Y',confounders=('X',),identification='',standard_errors=True,robustness=True,causal_claim=True);assert not r.passed
