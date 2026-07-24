"""Auditable bounded adapters and typed Agent Broker contracts."""
from __future__ import annotations
import json,time,uuid,re
from dataclasses import dataclass,asdict,field
from enum import StrEnum
from pathlib import Path
from typing import Any,Mapping
from services.process_supervisor import ProcessSupervisor
class StopReason(StrEnum):
 COMPLETED="completed";FAILED="failed";CANCELLED="cancelled";INTERRUPTED="interrupted";TIMEOUT="timeout";SCHEMA_DRIFT="schema_drift";UNAVAILABLE="unavailable"
@dataclass(frozen=True)
class Capability:
 name:str;available:bool;authenticated:bool=False;reason:str|None=None
 def __post_init__(self):
  if not self.name.strip():raise ValueError("capability name required")
  if self.available and self.reason is not None:raise ValueError("available capability cannot carry an unavailable reason")
  if not self.available and not self.reason:raise ValueError("unavailable capability requires a reason")
@dataclass(frozen=True)
class ToolCall:
 name:str;input:Mapping[str,Any];call_id:str;result:Any|None=None;error:str|None=None
 def __post_init__(self):
  if not self.name.strip() or not self.call_id.strip():raise ValueError("tool name and call_id required")
  if self.result is not None and self.error is not None:raise ValueError("tool call cannot have both result and error")
@dataclass(frozen=True)
class Usage:
 input_tokens:int=0;output_tokens:int=0;cache_read_input_tokens:int=0;cache_creation_input_tokens:int=0
 def __post_init__(self):
  if any(value<0 for value in asdict(self).values()):raise ValueError("usage token counts must be non-negative")
@dataclass(frozen=True)
class AgentTask:
 task_id:str;adapter:str;prompt:str;workspace:str;schema_version:int=1;metadata:Mapping[str,Any]=field(default_factory=dict)
 def __post_init__(self):
  if self.schema_version!=1:raise ValueError("unsupported AgentTask schema version")
  if not self.task_id.strip() or not self.adapter.strip() or not self.prompt.strip():raise ValueError("task_id, adapter and prompt are required")
@dataclass(frozen=True)
class AgentResult:
 task_id:str;status:StopReason;final_text:str="";usage:Usage=field(default_factory=Usage);tool_calls:tuple[ToolCall,...]=();artifact_sha256:str|None=None;error:str|None=None;schema_version:int=1
 def __post_init__(self):
  if self.schema_version!=1:raise ValueError("unsupported AgentResult schema version")
  if self.status==StopReason.COMPLETED and not self.final_text.strip():raise ValueError("completed result requires final_text")
  if self.status in {StopReason.FAILED,StopReason.SCHEMA_DRIFT,StopReason.UNAVAILABLE,StopReason.TIMEOUT} and not self.error:raise ValueError("non-success result requires error")
  if self.artifact_sha256 is not None and (len(self.artifact_sha256)!=64 or any(c not in "0123456789abcdef" for c in self.artifact_sha256)):raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest")
@dataclass
class AgentEvent: event:str;run_id:str;at:float;payload:dict
class AdapterError(RuntimeError):pass
_SECRET=re.compile(r"(?i)\b([a-z0-9_]*(?:api[_-]?key|token|password|authorization))\s*[:=]\s*[^\s]+")
def _redact(value:str)->str:return _SECRET.sub(lambda m:m.group(1)+"=[REDACTED]",value)

def _usage(value: Any) -> Usage:
 if not isinstance(value,dict): raise ValueError("usage must be an object")
 fields={"input_tokens":0,"output_tokens":0,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}
 for key in fields:
  if key in value and (not isinstance(value[key],int) or isinstance(value[key],bool)):
   raise ValueError(f"usage.{key} must be an integer")
  fields[key]=value.get(key,0)
 return Usage(**fields)

def parse_agent_stream(adapter: str, stdout: str, task_id: str = "stream") -> AgentResult:
 events=[]; final_text=""; usage=Usage(); saw_final=False
 if adapter not in {"codex","claude"}: return AgentResult(task_id,StopReason.SCHEMA_DRIFT,error="unsupported stream adapter")
 for line_number,line in enumerate(stdout.splitlines(),1):
  try: value=json.loads(line)
  except json.JSONDecodeError: return AgentResult(task_id,StopReason.SCHEMA_DRIFT,error=f"invalid JSON at line {line_number}")
  if not isinstance(value,dict) or not isinstance(value.get("type"),str): return AgentResult(task_id,StopReason.SCHEMA_DRIFT,error=f"invalid event at line {line_number}")
  event_type=value["type"]; events.append(event_type)
  try:
   if adapter=="codex" and event_type=="item.completed":
    item=value.get("item")
    if not isinstance(item,dict): raise ValueError("item must be an object")
    if item.get("type")=="agent_message":
     if not isinstance(item.get("text"),str): raise ValueError("agent_message.text must be a string")
     final_text=item["text"]; saw_final=True
   elif adapter=="codex" and event_type=="turn.completed":
    usage=_usage(value.get("usage",{})); saw_final=saw_final
   elif adapter=="claude" and event_type=="result":
    if not isinstance(value.get("result"),str): raise ValueError("result must be a string")
    final_text=value["result"]; usage=_usage(value.get("usage",{})); saw_final=True
  except (TypeError,ValueError) as exc: return AgentResult(task_id,StopReason.SCHEMA_DRIFT,error=str(exc))
 if not saw_final or not final_text.strip(): return AgentResult(task_id,StopReason.SCHEMA_DRIFT,error="stream ended without a valid final response")
 return AgentResult(task_id,StopReason.COMPLETED,final_text=final_text.strip(),usage=usage)
class CliAdapter:
 def __init__(self,name:str,command:list[str],workspace:Path,audit_directory:Path):self.name=name;self.command=command;self.supervisor=ProcessSupervisor(workspace,{Path(command[0]).name});self.audit=audit_directory
 async def run(self,prompt:str,*,timeout:float=120,run_id:str|None=None,env:Mapping[str,str]|None=None)->dict:
  if not prompt.strip():raise AdapterError("prompt required")
  run_id=run_id or uuid.uuid4().hex;self.audit.mkdir(parents=True,exist_ok=True);events=[AgentEvent("started",run_id,time.time(),{"adapter":self.name,"command":self.command})]
  result=await self.supervisor.run(run_id,[*self.command,prompt],self.supervisor.workspace,timeout,env=env)
  events.append(AgentEvent("completed" if result["returncode"]==0 else "failed",run_id,time.time(),{"returncode":result["returncode"]}))
  audit_result={**result,"stdout":_redact(result["stdout"]),"stderr":_redact(result["stderr"])}
  (self.audit/f"{run_id}.json").write_text(json.dumps({"events":[asdict(e) for e in events],"result":audit_result},ensure_ascii=False),encoding="utf-8")
  return {"run_id":run_id,"events":[asdict(e) for e in events],"result":audit_result}
 async def cancel(self,run_id:str)->bool:return await self.supervisor.cancel(run_id)
