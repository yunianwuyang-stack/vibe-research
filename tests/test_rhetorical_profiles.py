from domain.narrative.profiles import PROFILES,profile
def test_three_profiles_define_section_moves_not_stock_prose():
 assert set(PROFILES)=={'ml_mechanism','causal_empirical','negative_result'}
 for p in PROFILES.values():assert set(p.moves)=={'Introduction','Methods','Results','Discussion'} and all(p.moves.values())
def test_negative_profile_preserves_null_result_value():assert 'null estimate' in profile('negative_result').moves['Results']
