import asyncio,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
def test_adapter_executes_bounded_child_and_records_audit(tmp_path):
 from services.agent_adapters import CliAdapter
 script=tmp_path/"agent.py";script.write_text("import sys;print('api_key=secret-value answer:'+sys.argv[1])")
 adapter=CliAdapter("test",[sys.executable,str(script)],tmp_path,tmp_path/"audit")
 async def go():return await adapter.run("question",timeout=10)
 result=asyncio.run(go());assert result["result"]["returncode"]==0 and '[REDACTED]' in result['result']['stdout']
 saved=json.loads(next((tmp_path/"audit").glob("*.json")).read_text(encoding="utf-8"));assert [x["event"] for x in saved["events"]]==["started","completed"]

def test_codex_stream_schema_drift_is_fail_closed():
 from services.agent_adapters import StopReason, parse_agent_stream
 result=parse_agent_stream("codex", '{"type":"turn.completed","usage":{"input_tokens":-1}}\n')
 assert result.status is StopReason.SCHEMA_DRIFT
 assert result.error

def test_claude_stream_requires_valid_final_result():
 from services.agent_adapters import StopReason, parse_agent_stream
 result=parse_agent_stream("claude", '{"type":"message_start","message":{"content":[]}}\n')
 assert result.status is StopReason.SCHEMA_DRIFT
 assert result.error

def test_stream_parser_accepts_real_final_events():
 from services.agent_adapters import StopReason, parse_agent_stream
 codex='{"type":"item.completed","item":{"type":"agent_message","text":"answer"}}\n{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":3}}\n'
 result=parse_agent_stream("codex",codex)
 assert result.status is StopReason.COMPLETED
 assert result.final_text=="answer"
 assert result.usage.output_tokens==3
