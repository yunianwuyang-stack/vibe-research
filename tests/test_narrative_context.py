import pytest
from domain.narrative import NarrativeContext
def test_writer_context_allowlists_only_approved_scientific_records():
 c=NarrativeContext.from_record({'question':['Q'],'claim':['C'],'evidence':['E']});assert c.claim==('C',) and not c.reproducibility_facts
def test_log_path_agent_or_debug_trace_injection_is_rejected():
 for key in ('workflow','debug','module','log','path','agent','trace'):
  with pytest.raises(ValueError):NarrativeContext.from_record({key:['bad']})
def test_methods_can_receive_minimal_approved_reproducibility_facts():
 assert NarrativeContext.from_record({'reproducibility_facts':['seed=1']},methods_approved=True).reproducibility_facts==('seed=1',)
