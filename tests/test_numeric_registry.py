import math,pytest
from domain.assurance import VerifiedNumericRegistry
H='a'*64
def args():return dict(condition='control',artifact_hash=H,run_id='run',metric='accuracy')
def test_validated_values_and_derivations_are_recomputable():
 r=VerifiedNumericRegistry({H});assert r.mean([1,2,3],**args()).value==2;assert r.difference(3,1,**args()).value==2
def test_unexecuted_bad_condition_nan_and_inf_are_rejected():
 r=VerifiedNumericRegistry(set())
 with pytest.raises(ValueError):r.register('raw',1,**args())
 r=VerifiedNumericRegistry({H})
 for x in (math.nan,math.inf):
  with pytest.raises(ValueError):r.register('raw',x,**args())
 with pytest.raises(ValueError):r.register('raw',1,**dict(args(),condition=''))
