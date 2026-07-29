export type Artifact={id:string;kind:string;status:string;provenance:string;sha256?:string};
export type EvidenceCard={id:string;identity:string;title:string;authors:string[];publication_year?:number;doi?:string;canonical_url:string;citation_status:string;claim_support_status:string;decision_reason?:string;citation_machine_verdict?:string|null;citation_machine_layer?:string|null;citation_machine_detail?:string|null;citation_machine_checked_at?:string|null;citation_machine_artifact_path?:string|null;provenance:Array<{provider:string;query:string;source_url:string;raw_response_sha256:string;retrieved_at:string}>};
export type HypothesisManifest={path:string;sha256:string;size?:number;status?:string};
export type HypothesisEvent={id:number;event_type:string;actor:string;reason:string;payload:Record<string,unknown>;created_at:string};
export type HypothesisVersion={id:string;project_id:string;hypothesis_id:string;version:number;parent_version_id?:string|null;statement:string;mechanism:string;prediction:string;falsification_criteria:string;boundary_conditions:string;status:'draft'|'frozen'|'falsified'|'superseded';change_reason:string;state_reason?:string|null;created_by:string;frozen_by?:string|null;frozen_at?:string|null;falsified_by?:string|null;falsified_at?:string|null;created_at:string;updated_at:string;is_current:boolean;manifest?:HypothesisManifest|null;events:HypothesisEvent[]};
export type HypothesisReadiness={ready:boolean;current_count:number;frozen_count:number;falsified_count:number;rule:string};
export type Project={id:string;title:string;research_question:string;inclusion_criteria:string;status:string;artifacts:Artifact[];evidence_cards:EvidenceCard[];hypotheses:HypothesisVersion[];hypothesis_readiness:HypothesisReadiness;events:Array<{event_type:string;actor:string;payload?:Record<string,unknown>}>};
export type LiteratureRecord={provider:string;title:string;provenance:string;status:string;url:string;doi?:string;authors?:string[];year?:number;retrieved_at:string;query_snapshot:string;snapshot_sha256:string};
export type WorkflowStep={skill_name:string;display_name:string;status:string;step_order:number;has_checkpoint:boolean;checkpoint_type?:string;output_files:string[];started_at?:string;completed_at?:string;error_message?:string};
export type Workflow={id:string;project_id?:string|null;title:string;template:string;params?:Record<string,unknown>;enable_checkpoints?:boolean;status:string;current_step?:string;created_at?:string;updated_at?:string;steps?:WorkflowStep[]};
export type WorkflowLog={id?:number;step_name?:string;level:string;message:string;created_at:string};
export type WorkflowCheckpoint={id:number;workflow_id:string;step_name:string;checkpoint_type:string;data:Record<string,unknown>;status:'pending'|'resolved';created_at:string;resolved_at?:string};
export type WorkflowArtifact={path:string;size:number;sha256:string;producer_step?:string|null};
export type WorkflowRunCenter={workflow:Workflow;logs:WorkflowLog[];checkpoint:WorkflowCheckpoint|null;artifacts:WorkflowArtifact[]};
export type WorkflowInput={path:string;name:string;size:number;sha256:string;status:string;extracted_text?:string;role?:string};
export type WorkflowTemplate={name:string;pipeline_skill:string;steps:Array<{skill_name:string;display_name:string;has_checkpoint:boolean}>};
export type WorkflowOperationsSummary={total:number;pending:number;running:number;paused:number;failed:number;completed:number;recoverable:number};
export type WorkflowRecoveryTarget={skill_name:string;display_name?:string|null;status:string;reason?:string|null};
export type WorkflowStatePlanes={transport:string;execution:string;assurance:string;root_cause:string;remediation:string};
export type WorkflowOperationsRun={id:string;project_id?:string|null;project_title?:string|null;title:string;template:string;status:string;state?:WorkflowStatePlanes;current_step?:string|null;created_at?:string;updated_at?:string;step_counts:Record<string,number>;progress:{completed:number;total:number;percent:number};latest_log?:WorkflowLog|null;artifact_count:number;recoverable:boolean;recovery_target?:WorkflowRecoveryTarget|null};
export type WorkflowOperationsSnapshot={summary:WorkflowOperationsSummary;runs:WorkflowOperationsRun[];pagination:{limit:number;offset:number;total:number}};
export type WorkflowAttempt={id?:number|string;workflow_id?:string;skill_name?:string;attempt_number?:number;status?:string;started_at?:string;finished_at?:string;completed_at?:string;error_message?:string|null;[key:string]:unknown};
export type WorkflowRecovery={id?:number|string;operation_id?:string;workflow_id?:string;skill_name?:string;status?:string;reason?:string;requested_by?:string;created_at?:string;started_at?:string;finished_at?:string;completed_at?:string;error_message?:string|null;[key:string]:unknown};
export type WorkflowOperationsEvent={id:number;event:string;data:Record<string,unknown>};
export type WorkflowOperationsDetail={workflow:Workflow&{state?:WorkflowStatePlanes};logs:WorkflowLog[];checkpoint:WorkflowCheckpoint|null;artifacts:Array<WorkflowArtifact&{attempt_id?:number|string|null;predecessor_sha256?:string|null;recorded_at?:string|null;exists?:boolean;lineage_verified?:boolean}>;attempts:WorkflowAttempt[];recoveries:WorkflowRecovery[];events:Array<Record<string,unknown>>;recovery_target?:WorkflowRecoveryTarget|null};
export type ExperimentRun={id:string;project_id:string;status:string;analysis_mode?:'exploratory'|'confirmatory';hypothesis_version_id?:string|null;hypothesis_manifest_sha256?:string|null;specification_sha256?:string;dependency_status?:'current'|'stale';stale_reason?:string|null;stale_at?:string|null;specification:{control:number[];treatment:number[];seeds:number;metric:string;analysis_mode?:'exploratory'|'confirmatory';hypothesis_version_id?:string;hypothesis_manifests?:Array<{version_id:string;hypothesis_id:string;version:number;sha256:string;path:string}>};hypothesis_manifests?:Array<{version_id:string;hypothesis_id:string;version:number;sha256:string;path:string}>;result:Record<string,unknown>;statistics:{passed:boolean;issues:string[];profile:string};manifest_sha256?:string;result_sha256?:string;failure_reason?:string;replay_of?:string;reproduced?:boolean;hypothesis_dependencies?:Array<{hypothesis_version_id:string;hypothesis_manifest_sha256:string;status:'current'|'stale';stale_reason?:string|null}>;integrity?:{passed:boolean;issues:string[];dependency_current:boolean}};
export type AgentTask={id:string;project_id:string;adapter:string;prompt:string;status:string;events:Array<{event:string;at:number;payload:Record<string,unknown>}>;result:{returncode?:number;stdout?:string;stderr?:string;final_text?:string;usage?:Record<string,unknown>;artifact_path?:string;artifact_sha256?:string;structured_events?:Array<Record<string,unknown>>};audit_path?:string;failure_reason?:string;retry_of?:string;cancellable:boolean};
export type AgentCollaborationStep={kind:string;role:string;status:string;error?:string|null;duration_seconds?:number;output?:string;output_sha256?:string|null;task_id?:string|null;audit_path?:string|null};
export type AgentCollaboration={id:string;project_id:string;status:string;goal:string;roles:string[];cli_adapters:string[];steps:AgentCollaborationStep[];report_path?:string|null;report_sha256?:string|null;failure_reason?:string|null;created_at?:string;updated_at?:string};
export type NarrativeMap={project_id?:string;question:string;tension:string;mechanism:string;hypotheses:string[];claims:string[];competing_explanations:string[];boundaries:string[];limitations:string[];approved?:boolean;approved_by?:string};
export type ClaimEvidenceLink={id:string;claim_id:string;evidence_card_id:string;relation:'supports'|'contradicts'|'context';passage:string;locator?:string;status:string;reviewed_by?:string;review_reason?:string};
export type ClaimExperimentLink={id:string;claim_id:string;experiment_run_id:string;relation:'supports'|'contradicts'|'context';result_locator:string;interpretation:string;evidence_card_ids:string[];result_sha256:string;manifest_sha256:string;status:string;reviewed_by?:string;review_reason?:string;result_value?:unknown;eligible:boolean;eligibility:Record<string,boolean>};
export type ClaimEvidenceGraph={format_version:string;project:{id:string;title:string};claims:Array<{id:string;supporting_link_ids:string[];supporting_experiment_link_ids?:string[];status:string}>;evidence_cards:Array<Pick<EvidenceCard,'id'|'title'|'canonical_url'|'citation_status'|'claim_support_status'>>;links:ClaimEvidenceLink[];experiments:Array<{id:string;status:string;analysis_mode?:'exploratory'|'confirmatory';dependency_status?:'current'|'stale';result:Record<string,unknown>;statistics:{passed:boolean;issues?:string[]};result_sha256?:string;manifest_sha256?:string;integrity?:{passed:boolean;issues:string[]}}> ;experiment_links:ClaimExperimentLink[];gate:{passed:boolean;total_claims:number;supported_claims:number;unsupported_claim_ids:string[];rule:string};artifact:{path:string;sha256:string}};
export type ModelProvider='openai_compatible'|'openai_responses'|'anthropic_messages'|'gemini_generate_content';
export type ModelProfile={role:'executor'|'reviewer'|'editor_ai';name:string;provider:ModelProvider;base_url:string;model_id:string;temperature:number;top_p:number;max_tokens:number;reasoning_effort:''|'minimal'|'low'|'medium'|'high';api_key_configured:boolean};
export type ModelProfileUpdate=Omit<ModelProfile,'role'|'name'|'api_key_configured'>&{api_key?:string;clear_api_key?:boolean};
export type ModelProfileTest={ok:boolean;message:string;agent:string};
export type AdversarialFinding={severity:'critical'|'major'|'minor'|'info';code:string;message:string;locator:string};
export type AdversarialReview={id:string;project_id:string;mode:'deterministic'|'model';reviewer_role:string;status:'running'|'completed'|'failed'|'interrupted';verdict:'pending'|'pass'|'block'|'error';inputs_sha256:string;findings:AdversarialFinding[];review_text:string;report_path?:string;report_sha256?:string;failure_reason?:string;created_at:string;updated_at:string};
export type AssuranceGate={id:string;label:string;status:'PASS'|'WARN'|'BLOCKED';findings:AdversarialFinding[]};
export type AssuranceFinding=AdversarialFinding;
export type AssuranceRepairAction={finding_code:string;action:string};
export type AssuranceEnvelope={format_version:string;status:'PASS'|'WARN'|'BLOCKED';submission_ready:boolean;input_hashes:{project_snapshot_sha256:string;latest_review_inputs_sha256:string|null;review_report_sha256:string|null};findings:AssuranceFinding[];repair_actions:AssuranceRepairAction[];verifier_version:string;independent_from_generator:boolean;gates:AssuranceGate[];current_review:AdversarialReview|null;latest_review:AdversarialReview|null};
export type InnovationClaim={id:string;text:string;source?:string;hypothesis_version_id?:string};
export type InnovationFinding={severity:'critical'|'major'|'minor'|'info';code:string;message:string;locator?:string;detail?:Record<string,unknown>};
export type InnovationPriorArt={kind?:string;id?:string;title?:string;doi?:string|null;url?:string|null;overlap?:number;claim_id?:string};
export type InnovationCheck={project_id?:string;id?:string;status:string;gate_passed?:boolean;gate:{passed:boolean;total_claims?:number;low_novelty_claim_ids?:string[];rule?:string};claims:InnovationClaim[];findings:InnovationFinding[];closest_prior_art:InnovationPriorArt[];overrides?:Record<string,string>;artifact?:{path:string;sha256:string}|null;report?:Record<string,unknown>|null;sources_version_sha256?:string;created_at?:string};
export type ScreeningProtocol={project_id:string;title:string;inclusion_criteria:string;exclusion_criteria:string;source_strategy:string;status:'draft'|'active';active:boolean;version:number;protocol_sha256:string;artifact_path:string;activated_by?:string;activated_at?:string};
export type ScreeningDecision={id:string;evidence_card_id:string;decision:'included'|'excluded'|'uncertain';reason:string;actor:string;created_at:string;title:string;canonical_url:string};
export type ScreeningState={protocol:ScreeningProtocol|null;decisions:ScreeningDecision[];prisma:{flow:{records_identified:number;records_screened:number;records_not_yet_screened:number;studies_included:number;records_excluded:number;records_uncertain:number};excluded_reasons:Array<{reason:string;count:number}>}|null;artifact:{path:string;sha256:string}|null};
export type ResearchRunStep={
  name:string;
  status:string;
  input?:Record<string,unknown>;
  output?:Record<string,unknown>;
  artifacts?:Array<Record<string,unknown>>;
  provenance?:Array<Record<string,unknown>>;
  gate?:Record<string,unknown>;
  failure_reason?:string|null;
  attempts?:number;
  updated_at?:string;
};
export type ResearchRun={
  id:string;
  project_id:string;
  status:string;
  current_step?:string|null;
  steps:ResearchRunStep[];
  created_at?:string;
  updated_at?:string;
};
export type ResearchRunAdvanceBody={
  input?:Record<string,unknown>;
  artifacts?:Array<Record<string,unknown>>;
  provenance?:Array<Record<string,unknown>>;
  gate_passed:boolean;
  failure_reason?:string|null;
};

declare global { interface Window { electronAPI?: { localSessionToken?:()=>Promise<string>; selectDataDirectory?:()=>Promise<{canceled:boolean;path?:string}> } } }

let desktopToken: string|undefined;
export async function localSessionToken():Promise<string>{
  if(desktopToken) return desktopToken;
  if(typeof window==='undefined') return '';
  const bridge=window.electronAPI?.localSessionToken;
  if(bridge){ desktopToken=await bridge(); return desktopToken; }
  const stored = window.localStorage.getItem('vibe-session-token');
  if(stored) return stored;
  // In source/dev mode the backend runs with IS_DESKTOP=False and skips token
  // verification entirely.  Return a non-empty placeholder so the UI treats
  // the session as live.  Has no effect in production (import.meta.env.DEV
  // is false in the Vite build output).
  if(import.meta.env.DEV) return 'dev-source-mode';
  return '';
}

export function formatApiError(payload:string,status:number,path:string):string{
  if(!payload) return `HTTP ${status} ${path}`;
  try{
    const body=JSON.parse(payload) as {detail?:unknown};
    const detail=body?.detail;
    if(typeof detail==='string') return detail;
    if(detail && typeof detail==='object'){
      const record=detail as Record<string,unknown>;
      const code=typeof record.code==='string'?record.code:'';
      const message=typeof record.message==='string'?record.message:'';
      const machine=record.machine && typeof record.machine==='object'
        ? record.machine as Record<string,unknown>
        : undefined;
      const machineBits=[
        machine?.verdict?`机器核验 ${String(machine.verdict)}`:'',
        machine?.lookup_layer||machine?.layer?`层 ${String(machine.lookup_layer||machine.layer)}`:'',
        machine?.detail?String(machine.detail):'',
      ].filter(Boolean);
      const parts=[code,message,...machineBits].filter(Boolean);
      if(parts.length) return parts.join(' · ');
    }
  }catch{/* keep raw payload */}
  return payload;
}

export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
  const token=await localSessionToken();
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Vibe-Session-Token':token,...(options.headers||{})}});
  const payload=await response.text();
  if(!response.ok) throw new Error(formatApiError(payload,response.status,path));
  const contentType=response.headers.get('content-type')||'';
  if(!contentType.includes('application/json')){
    throw new Error(`接口 ${path} 未返回 JSON（收到 ${contentType||'未知内容类型'}）。请检查本地后端是否已启动并包含该接口。`);
  }
  try{return JSON.parse(payload) as T}
  catch{throw new Error(`接口 ${path} 返回了无效 JSON。请重启本地后端后重试。`)}
}

export async function download(path:string,filename:string,options:RequestInit={}):Promise<void>{
  const token=await localSessionToken();
  const response=await fetch(path,{...options,headers:{'X-Vibe-Session-Token':token,...(options.headers||{})}});
  if(!response.ok) throw new Error((await response.text())||`${response.status}`);
  const url=URL.createObjectURL(await response.blob()); const anchor=document.createElement('a');
  anchor.href=url; anchor.download=filename; anchor.click(); URL.revokeObjectURL(url);
}

export const createProject=(title:string,question:string,criteria:string)=>api<Project>('/api/research-projects',{method:'POST',body:JSON.stringify({title,research_question:question,inclusion_criteria:criteria})});
export const deleteProject=(projectId:string)=>api<{deleted:boolean;id:string}>(`/api/research-projects/${projectId}`,{method:'DELETE'});
export type HypothesisWrite=Pick<HypothesisVersion,'statement'|'mechanism'|'prediction'|'falsification_criteria'|'boundary_conditions'>;
export const createHypothesis=(projectId:string,value:HypothesisWrite,changeReason:string)=>api<Project>(`/api/research-projects/${projectId}/hypotheses`,{method:'POST',body:JSON.stringify({...value,actor:'researcher',change_reason:changeReason})});
export const reviseHypothesis=(projectId:string,versionId:string,value:HypothesisWrite,changeReason:string)=>api<Project>(`/api/research-projects/${projectId}/hypotheses/${versionId}/revisions`,{method:'POST',body:JSON.stringify({...value,actor:'researcher',change_reason:changeReason})});
export const transitionHypothesis=(projectId:string,versionId:string,action:'freeze'|'unfreeze'|'falsify',reason:string)=>api<Project>(`/api/research-projects/${projectId}/hypotheses/${versionId}/${action}`,{method:'POST',body:JSON.stringify({actor:'researcher',reason})});
export const searchLiterature=(provider:string,query:string)=>api<{records:LiteratureRecord[]}>('/api/literature/search',{method:'POST',body:JSON.stringify({provider,query})});
export const saveEvidenceCard=(projectId:string,provider:string,query:string,sourceUrl:string,snapshotSha256:string)=>api<Project>(`/api/research-projects/${projectId}/evidence-cards`,{method:'POST',body:JSON.stringify({provider,query,source_url:sourceUrl,snapshot_sha256:snapshotSha256})});
export const reviewEvidenceCard=(projectId:string,cardId:string,decision:'approved'|'rejected',reason:string)=>api<Project>(`/api/research-projects/${projectId}/evidence-cards/${cardId}/review`,{method:'POST',body:JSON.stringify({actor:'researcher',decision,reason})});
export const reviewClaimSupport=(projectId:string,cardId:string,decision:'approved'|'rejected',reason:string)=>api<Project>(`/api/research-projects/${projectId}/evidence-cards/${cardId}/claim-support`,{method:'POST',body:JSON.stringify({actor:'researcher',decision,reason})});
export const getScreening=(projectId:string)=>api<ScreeningState>(`/api/research-projects/${projectId}/screening`);
export const saveScreeningProtocol=(projectId:string,value:{title:string;inclusion_criteria:string;exclusion_criteria:string;source_strategy:string})=>api<ScreeningState>(`/api/research-projects/${projectId}/screening/protocol`,{method:'PUT',body:JSON.stringify({...value,actor:'researcher'})});
export const activateScreeningProtocol=(projectId:string)=>api<ScreeningState>(`/api/research-projects/${projectId}/screening/activate`,{method:'POST',body:JSON.stringify({actor:'researcher'})});
export const recordScreeningDecision=(projectId:string,cardId:string,decision:'included'|'excluded'|'uncertain',reason:string)=>api<ScreeningState>(`/api/research-projects/${projectId}/screening/evidence-cards/${cardId}`,{method:'POST',body:JSON.stringify({decision,reason,actor:'researcher'})});
export const exportScreeningPrisma=(projectId:string)=>api<ScreeningState>(`/api/research-projects/${projectId}/screening/prisma`,{method:'POST'});
export const generateDraft=(projectId:string)=>api<{content:string;sha256:string;evidence_version_sha256:string}>(`/api/research-projects/${projectId}/draft`,{method:'POST'});
export const saveDraft=(projectId:string,content:string)=>api<{ok:boolean;sha256:string}>(`/api/research-projects/${projectId}/draft`,{method:'PUT',body:JSON.stringify({content})});
export const listExperiments=(projectId:string)=>api<ExperimentRun[]>(`/api/experiments/projects/${projectId}`);
export const executeExperiment=(projectId:string,control:number[],treatment:number[],seeds:number,metric:string,analysisMode:'exploratory'|'confirmatory',hypothesisVersionId?:string)=>api<ExperimentRun>(`/api/experiments/projects/${projectId}`,{method:'POST',body:JSON.stringify({control,treatment,seeds,metric,analysis_mode:analysisMode,hypothesis_version_id:hypothesisVersionId||null})});
export const replayExperiment=(runId:string)=>api<ExperimentRun>(`/api/experiments/${runId}/replay`,{method:'POST'});
export const listAgentTasks=(projectId:string)=>api<AgentTask[]>(`/api/agents/tasks?project_id=${encodeURIComponent(projectId)}`);
export const startAgentTask=(projectId:string,adapter:string,prompt:string)=>api<AgentTask>('/api/agents/tasks',{method:'POST',body:JSON.stringify({project_id:projectId,adapter,prompt})});
export const cancelAgentTask=(taskId:string)=>api<AgentTask>(`/api/agents/tasks/${taskId}/cancel`,{method:'POST'});
export const retryAgentTask=(taskId:string)=>api<AgentTask>(`/api/agents/tasks/${taskId}/retry`,{method:'POST'});
export const listAgentCollaborations=(projectId:string)=>api<AgentCollaboration[]>(`/api/agents/collaborations?project_id=${encodeURIComponent(projectId)}`);
export const startAgentCollaboration=(projectId:string,goal:string,roles:string[]=['executor','reviewer','editor_ai'],cliAdapters:string[]=[])=>api<AgentCollaboration>('/api/agents/collaborations',{method:'POST',body:JSON.stringify({project_id:projectId,goal,roles,cli_adapters:cliAdapters,timeout_seconds:120})});
export const getAgentCollaboration=(collabId:string)=>api<AgentCollaboration>(`/api/agents/collaborations/${encodeURIComponent(collabId)}`);
export const saveNarrativeMap=(projectId:string,value:NarrativeMap)=>api<NarrativeMap>(`/api/research-projects/${projectId}/narrative`,{method:'PUT',body:JSON.stringify(value)});
export const approveNarrativeMap=(projectId:string)=>api<NarrativeMap>(`/api/research-projects/${projectId}/narrative/approve`,{method:'POST',body:JSON.stringify({actor:'researcher'})});
export const getClaimEvidenceGraph=(projectId:string)=>api<ClaimEvidenceGraph>(`/api/research-projects/${projectId}/claim-evidence-graph`);
export const createClaimEvidenceLink=(projectId:string,value:{claim_id:string;evidence_card_id:string;relation:'supports'|'contradicts'|'context';passage:string;locator:string})=>api<ClaimEvidenceGraph>(`/api/research-projects/${projectId}/claim-evidence-links`,{method:'POST',body:JSON.stringify(value)});
export const reviewClaimEvidenceLink=(projectId:string,linkId:string,decision:'approved'|'rejected',reason:string)=>api<ClaimEvidenceGraph>(`/api/research-projects/${projectId}/claim-evidence-links/${linkId}/review`,{method:'POST',body:JSON.stringify({actor:'researcher',decision,reason})});
export const createClaimExperimentLink=(projectId:string,value:{claim_id:string;experiment_run_id:string;relation:'supports'|'contradicts'|'context';result_locator:string;interpretation:string;evidence_card_ids:string[]})=>api<ClaimEvidenceGraph>(`/api/research-projects/${projectId}/claim-experiment-links`,{method:'POST',body:JSON.stringify(value)});
export const reviewClaimExperimentLink=(projectId:string,linkId:string,decision:'approved'|'rejected',reason:string)=>api<ClaimEvidenceGraph>(`/api/research-projects/${projectId}/claim-experiment-links/${linkId}/review`,{method:'POST',body:JSON.stringify({actor:'researcher',decision,reason})});
export const getModelProfiles=()=>api<{profiles:ModelProfile[]}>('/api/settings/model-profiles');
export const saveModelProfile=(role:ModelProfile['role'],value:ModelProfileUpdate)=>api<ModelProfile>(`/api/settings/model-profiles/${role}`,{method:'PUT',body:JSON.stringify(value)});
export const testModelProfile=(role:ModelProfile['role'])=>api<ModelProfileTest>(`/api/settings/model-profiles/${role}/test`,{method:'POST'});
export const listAdversarialReviews=(projectId:string)=>api<AdversarialReview[]>(`/api/research-projects/${projectId}/adversarial-reviews`);
export const runAdversarialReview=(projectId:string,mode:'deterministic'|'model')=>api<AdversarialReview>(`/api/research-projects/${projectId}/adversarial-reviews`,{method:'POST',body:JSON.stringify({mode})});
export const getInnovationCheck=(projectId:string)=>api<InnovationCheck>(`/api/research-projects/${projectId}/innovation-check`);
export const runInnovationCheck=(projectId:string,value:{claims?:string[];overrides?:Record<string,string>;provider?:string|null}={})=>api<InnovationCheck>(`/api/research-projects/${projectId}/innovation-check`,{method:'POST',body:JSON.stringify({actor:'researcher',...value})});
export const getAssurance=(projectId:string)=>api<AssuranceEnvelope>(`/api/research-projects/${projectId}/assurance`);
export const listWorkflows=(projectId:string)=>api<Workflow[]>(`/api/workflows?project_id=${encodeURIComponent(projectId)}`);
export const getWorkflowRunCenter=(workflowId:string)=>api<WorkflowRunCenter>(`/api/workflows/${workflowId}/run-center`);
export const listWorkflowOperations=(filters:{project_id?:string;status?:string;limit?:number;offset?:number}={})=>{const query=new URLSearchParams(); if(filters.project_id)query.set('project_id',filters.project_id); if(filters.status)query.set('status',filters.status); query.set('limit',String(filters.limit??200)); query.set('offset',String(filters.offset??0)); return api<WorkflowOperationsSnapshot>(`/api/workflows/operations?${query.toString()}`)};
export const getWorkflowOperationsDetail=(workflowId:string)=>api<WorkflowOperationsDetail>(`/api/workflows/operations/${encodeURIComponent(workflowId)}`);
export const retryWorkflowStep=(workflowId:string,skillName:string,reason:string)=>api<{ok:boolean;operation_id:string;workflow_id:string;skill_name:string;status:'accepted'}>(`/api/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(skillName)}/retry`,{method:'POST',body:JSON.stringify({reason,requested_by:'researcher'})});
export const recoverWorkflow=(workflowId:string,reason:string)=>api<{ok:boolean;operation_id:string;workflow_id:string;skill_name:string;status:'accepted'}>(`/api/workflows/${encodeURIComponent(workflowId)}/recover`,{method:'POST',body:JSON.stringify({reason,requested_by:'researcher'})});
export async function streamWorkflowOperationsEvents(filters:{after_id?:number;project_id?:string;workflow_id?:string},onEvent:(event:WorkflowOperationsEvent)=>void,signal:AbortSignal):Promise<void>{
  const query=new URLSearchParams();
  if(filters.after_id)query.set('after_id',String(filters.after_id));
  if(filters.project_id)query.set('project_id',filters.project_id);
  if(filters.workflow_id)query.set('workflow_id',filters.workflow_id);
  const token=await localSessionToken();
  const response=await fetch(`/api/workflows/operations/events?${query.toString()}`,{headers:{Accept:'text/event-stream','X-Vibe-Session-Token':token},signal});
  if(!response.ok)throw new Error((await response.text())||`${response.status}`);
  if(!response.body)throw new Error('运行事件流没有可读取的响应体');
  onEvent({id:filters.after_id||0,event:'heartbeat',data:{connected:true}});
  const reader=response.body.getReader();
  const decoder=new TextDecoder();
  let buffer='';
  const deliver=(block:string)=>{
    let id=0; let event='message'; const data:string[]=[];
    for(const line of block.replace(/\r/g,'').split('\n')){
      if(line.startsWith('id:'))id=Number(line.slice(3).trim())||0;
      else if(line.startsWith('event:'))event=line.slice(6).trim()||'message';
      else if(line.startsWith('data:'))data.push(line.slice(5).trimStart());
    }
    if(!data.length){if(block.includes(': heartbeat'))onEvent({id,event:'heartbeat',data:{connected:true}});return;}
    const raw=data.join('\n');
    let parsed:unknown;
    try{parsed=JSON.parse(raw)}catch{parsed={message:raw}}
    onEvent({id,event,data:parsed&&typeof parsed==='object'&&!Array.isArray(parsed)?parsed as Record<string,unknown>:{value:parsed}});
  };
  while(true){
    const chunk=await reader.read();
    buffer+=decoder.decode(chunk.value||new Uint8Array(),{stream:!chunk.done});
    const normalized=buffer.replace(/\r\n/g,'\n');
    const blocks=normalized.split('\n\n');
    buffer=blocks.pop()||'';
    blocks.forEach(deliver);
    if(chunk.done){if(buffer.trim())deliver(buffer);break;}
  }
}
export const resolveWorkflowCheckpoint=(workflowId:string,action:'approve'|'feedback'|'stop',data:Record<string,unknown>={})=>api<{ok:boolean}>(`/api/workflows/${workflowId}/checkpoints/resolve`,{method:'POST',body:JSON.stringify({action,data})});
export const syncWorkflowEvidence=(workflowId:string)=>api<{imported:Array<{provider:string;title:string;url:string}>;count:number;errors:Array<{provider:string;url?:string;error:string}>;project_id:string}>(`/api/workflows/${encodeURIComponent(workflowId)}/sync-evidence`,{method:'POST'});
export type ResearchRunList={
  project_id:string;
  runs:Array<Pick<ResearchRun,'id'|'project_id'|'status'|'current_step'|'created_at'|'updated_at'>>;
  active:ResearchRun|null;
  count:number;
};
export const startResearchRun=(projectId:string)=>api<ResearchRun>(`/api/research-runs/projects/${projectId}`,{method:'POST'});
export const listResearchRuns=(projectId:string)=>api<ResearchRunList>(`/api/research-runs/projects/${projectId}`);
export const getResearchRun=(runId:string)=>api<ResearchRun>(`/api/research-runs/${runId}`);
export const advanceResearchRunStep=(runId:string,name:string,body:ResearchRunAdvanceBody)=>api<ResearchRun>(`/api/research-runs/${runId}/steps/${encodeURIComponent(name)}`,{method:'POST',body:JSON.stringify({
  input:body.input||{},
  artifacts:body.artifacts||[],
  provenance:body.provenance||[],
  gate_passed:body.gate_passed,
  failure_reason:body.failure_reason??null,
})});
export const retryResearchRunStep=(runId:string,name:string)=>api<ResearchRun>(`/api/research-runs/${runId}/steps/${encodeURIComponent(name)}/retry`,{method:'POST'});
export const resumeResearchRun=(runId:string)=>api<ResearchRun>(`/api/research-runs/${runId}/resume`,{method:'POST'});
export const cancelResearchRun=(runId:string,reason:string)=>api<ResearchRun>(`/api/research-runs/${runId}/cancel`,{method:'POST',body:JSON.stringify({reason})});
export const listWorkflowInputs=(workflowId:string)=>api<WorkflowInput[]>(`/api/workflows/${workflowId}/artifacts/inputs`);
export async function uploadWorkflowInputs(workflowId:string,files:File[],role='material'):Promise<{uploaded:string[]}> { const body=new FormData(); files.forEach(file=>{ body.append('files',file); body.append('relative_paths',(file as File&{webkitRelativePath?:string}).webkitRelativePath||file.name); }); body.append('role',role); const token=await localSessionToken(); const response=await fetch(`/api/workflows/${workflowId}/artifacts/inputs/upload`,{method:'POST',headers:{'X-Vibe-Session-Token':token},body}); const payload=await response.text(); if(!response.ok) throw new Error(payload||`${response.status}`); return JSON.parse(payload) as {uploaded:string[]}; }
export async function uploadWorkflowRequirements(workflowId:string,file:File):Promise<{ok:boolean;path:string;source:string;sha256:string}> { const body=new FormData(); body.append('file',file); const token=await localSessionToken(); const response=await fetch(`/api/workflows/${workflowId}/artifacts/custom-requirements`,{method:'POST',headers:{'X-Vibe-Session-Token':token},body}); const payload=await response.text(); if(!response.ok) throw new Error(payload||`${response.status}`); return JSON.parse(payload) as {ok:boolean;path:string;source:string;sha256:string}; }
