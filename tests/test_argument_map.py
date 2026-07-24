import pytest
from domain.narrative.argument_map import ArgumentMap,NarrativeDraftGate,ParagraphBrief
def base():return ArgumentMap(('C1',),'mechanism',('alternative',),('boundary',))
def test_unapproved_argument_map_blocks_draft():
 with pytest.raises(PermissionError):NarrativeDraftGate().draft(base(),(ParagraphBrief('C1','result','x'),))
def test_approved_briefs_map_claim_and_rhetorical_role():
 assert NarrativeDraftGate().draft(base().approve(),(ParagraphBrief('C1','result','x'),))[0].claim_id=='C1'
def test_new_claim_or_strength_change_requires_approval():
 with pytest.raises(ValueError):NarrativeDraftGate().draft(base().approve(),(ParagraphBrief('C2','result','x'),))
 with pytest.raises(PermissionError):NarrativeDraftGate().draft(base().approve().revise_strength('strong'),())
