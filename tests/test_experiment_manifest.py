from pathlib import Path
import pytest
from domain.experiments import ExperimentManifest
from infrastructure.execution.manifest_store import ManifestIntegrityError,ManifestStore
H='a'*64
def manifest(**kw):
 d=dict(dataset_hash=H,dataset_license='CC-BY',split='train/test',code_commit='abc',argv=('python','run.py'),environment_lock='requirements.lock',hardware='cpu',seed=1,config={'lr':.1},metric_definition='accuracy',started_at='a',ended_at='b',exit_code=1,raw_artifact_hashes=(H,));d.update(kw);return ExperimentManifest(**d)
def test_complete_manifest_is_immutable_and_failed_run_is_retained(tmp_path:Path):
 p=ManifestStore(tmp_path).write(manifest());assert ManifestStore(tmp_path).load(p).exit_code==1
def test_missing_provenance_is_not_ready_for_analysis():
 with pytest.raises(ValueError):manifest(environment_lock='')
def test_manifest_tampering_is_detected(tmp_path:Path):
 s=ManifestStore(tmp_path);p=s.write(manifest());p.write_text('{}',encoding='utf-8')
 with pytest.raises(ManifestIntegrityError):s.load(p)
