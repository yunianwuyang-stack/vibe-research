"""Claim-version graph and fail-closed scientific manuscript projection."""
from __future__ import annotations
import copy
import re
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

class ProjectionError(ValueError): pass
@dataclass(frozen=True)
class ClaimEdge:
    relation: str; target_id: str
    def __post_init__(self):
        if self.relation not in {"support", "contradict", "qualify"}: raise ValueError("claim edge relation must be support, contradict, or qualify")
        if not self.target_id.strip(): raise ValueError("claim edge target is required")
@dataclass(frozen=True)
class ClaimVersion:
    claim_id: str; version: int; statement: str; strength: str; scope: str; uncertainty: str; counterexamples: tuple[str,...]; edges: tuple[ClaimEdge,...]; source_hash: str; stale_reason: str|None=None
    def __post_init__(self):
        if not all((self.claim_id.strip(),self.statement.strip(),self.strength.strip(),self.scope.strip(),self.uncertainty.strip())): raise ValueError("claim statement, strength, scope, and uncertainty are required")
        if self.version < 1: raise ValueError("claim version must be positive")
        if not self.counterexamples: raise ValueError("at least one counterexample is required")
        if not any(edge.relation == "support" for edge in self.edges): raise ValueError("at least one support edge is required")
        if not re.fullmatch(r"[a-f0-9]{64}",self.source_hash): raise ValueError("source_hash must be SHA-256")
    @property
    def factual_coverage_complete(self): return not self.stale_reason and bool(self.edges and self.counterexamples)
    def mark_stale(self,reason):
        if not reason.strip(): raise ValueError("stale reason is required")
        return replace(self,stale_reason=reason.strip())
@dataclass(frozen=True)
class ScientificFact:
    fact_id: str; information_type: str; text: str; claim_ids: tuple[str,...]
@dataclass(frozen=True)
class WriterDTO:
    claims: tuple[ClaimVersion,...]; facts: tuple[ScientificFact,...]; profile: str; language: str
    @classmethod
    def build(cls,*,claims,facts,profile,language):
        if language not in {"en","zh"}: raise ProjectionError("language must be en or zh")
        if profile not in _PROFILES: raise ProjectionError("unknown rhetorical profile")
        if not claims or any(c.stale_reason for c in claims): raise ProjectionError("stale or absent claims cannot enter WriterDTO")
        ids={c.claim_id for c in claims}
        if any(not f.claim_ids or not set(f.claim_ids)<=ids for f in facts): raise ProjectionError("every scientific fact must reference a current claim")
        return cls(tuple(claims),tuple(facts),profile,language)
@dataclass(frozen=True)
class LintIssue: code: str; line: int
@dataclass(frozen=True)
class RevisionPatch: section: str; old_text: str; new_text: str
_COMMON={"Abstract":frozenset({"question","claim","result","uncertainty","limitation"}),"Introduction":frozenset({"question","theory","gap","claim"}),"Methods":frozenset({"method","design","assumption","reproducibility"}),"Results":frozenset({"result","uncertainty","counterexample","robustness","claim"}),"Discussion":frozenset({"claim","interpretation","limitation","boundary","counterexample"})}
_PROFILES={"causal_empirical":_COMMON,"ml_mechanism":_COMMON,"negative_result":_COMMON,"qualitative":{**_COMMON,"Results":_COMMON["Results"]|{"theme","quotation"}},"theory":{**_COMMON,"Methods":_COMMON["Methods"]|{"proof"},"Results":_COMMON["Results"]|{"theorem"}}}
_CONTROL=re.compile(r"\b(?:agent|pipeline|module|workflow|api|queue|developer log)\b|(?:智能体|代理|流水线|管线|模块|工作流|接口调用|队列|开发日志)",re.I)
_CAUSAL=re.compile(r"\b(?:caused|causes|causal effect)\b|(?:导致|造成|因果效应)",re.I)
_NOVELTY=re.compile(r"\b(?:first ever|world(?:'s)? first|unprecedented)\b|(?:全球首个|世界首次|前所未有)",re.I)
class ManuscriptProjector:
    @staticmethod
    def profile_names(): return tuple(_PROFILES)
    def project(self,dto,sections):
        facts={f.fact_id:f for f in dto.facts}; rendered={}; allowed=_PROFILES[dto.profile]
        for section,ids in sections.items():
            if section not in allowed: raise ProjectionError(f"unknown section: {section}")
            selected=[]
            for fid in ids:
                if fid not in facts: raise ProjectionError(f"unknown scientific fact: {fid}")
                fact=facts[fid]
                if fact.information_type not in allowed[section]: raise ProjectionError(f"{fact.information_type} is not allowed in {section}")
                selected.append(fact)
            rendered[section]="\n".join(f"{f.text} [claim:{','.join(f.claim_ids)}]" for f in selected)
        issues=tuple(i for text in rendered.values() for i in self.lint(text,language=dto.language))
        if issues: raise ProjectionError(f"projected manuscript failed lint: {issues[0].code}")
        return rendered
    def lint(self,text,*,language,causal_claim_ids=frozenset(),novelty_claim_ids=frozenset()):
        issues=[]
        for n,line in enumerate(text.splitlines(),1):
            ids=frozenset(re.findall(r"\[claim:([^\]]+)\]",line,re.I))
            if _CONTROL.search(line): issues.append(LintIssue("control_plane_leak",n))
            if _CAUSAL.search(line) and not ids.intersection(causal_claim_ids): issues.append(LintIssue("unsupported_causal_upgrade",n))
            if _NOVELTY.search(line) and not ids.intersection(novelty_claim_ids): issues.append(LintIssue("unsupported_novelty_upgrade",n))
        return tuple(issues)
    def apply_revision(self,sections,patch,*,compile_document:Callable):
        if patch.section not in sections or sections[patch.section] != patch.old_text: raise ProjectionError("revision preimage does not match current section")
        candidate=copy.deepcopy(dict(sections)); candidate[patch.section]=patch.new_text
        if not compile_document(candidate): raise ProjectionError("compile failed; original manuscript preserved")
        return candidate
