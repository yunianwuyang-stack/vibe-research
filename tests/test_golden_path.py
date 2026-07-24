from application.golden_path import GOLDEN_PATH,GoldenPath,LEGACY_TEMPLATE_ADAPTER,capability_graph
def test_contract_to_claim_path_never_self_verifies():
 p=GoldenPath();s=p.run('Question contract');assert s['approval']=='approval:needs_execution' and p.events[0]['action']=='start_requested'
 assert all(x.input_schema and x.output_schema and x.capabilities and x.gates for x in GOLDEN_PATH)
 assert GOLDEN_PATH[-1].stale_dependencies==('approval',)
 graph=capability_graph();assert len(graph['nodes'])==10 and len(graph['edges'])==9
 assert [node['name'] for node in graph['nodes']]==['contract','question','hypothesis','evidence','experiment_run','result','claim','adversarial_review','approval','audit']
def test_legacy_templates_are_read_only_adapter_and_contract_required():
 assert len(LEGACY_TEMPLATE_ADAPTER)==34 and set(LEGACY_TEMPLATE_ADAPTER.values())=={'read-only'}
 try:GoldenPath().run('')
 except ValueError:pass
 else:raise AssertionError('empty contract accepted')
