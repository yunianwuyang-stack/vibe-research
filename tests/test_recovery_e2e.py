import asyncio
from pathlib import Path

def test_pause_cancels_running_task_before_marking_workflow_paused(monkeypatch):
    from routers import workflows
    calls = []
    class Task:
        def __init__(self): self.cancelled = False
        def done(self): return False
        def cancel(self): self.cancelled = True
    class Db:
        async def close(self): pass
    task = Task()
    workflows._tasks["wf-pause"] = task
    async def get_db(): return Db()
    async def update(db, wf_id, **kwargs): calls.append((wf_id, kwargs))
    monkeypatch.setattr('services.state_store._get_db', get_db)
    monkeypatch.setattr('services.state_store.update_workflow', update)
    try:
        assert asyncio.run(workflows.pause("wf-pause"))["ok"] is True
    finally:
        workflows._tasks.pop("wf-pause", None)
    assert task.cancelled is True
    assert calls == [("wf-pause", {"status": "paused"})]

def test_crash_recovery_and_rollback_preserve_explicit_truth(tmp_path):
    from application.staleness import DependencyLedger
    from services import state_store
    previous = state_store.DB_PATH
    try:
        state_store.DB_PATH = tmp_path / 'recovery.db'
        async def exercise():
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                await state_store.create_workflow(db, {'id':'crashed','template':'paper_writing','title':'crashed','status':'running'})
                await db.execute("INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status) VALUES (?,?,?,?,?)", ('crashed','step','Step',0,'running'))
                await db.commit()
            finally: await db.close()
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                row = await state_store.get_workflow(db, 'crashed')
                step = await (await db.execute("SELECT status FROM workflow_steps WHERE workflow_id=?", ('crashed',))).fetchone()
                return row['status'], step['status']
            finally: await db.close()
        assert asyncio.run(exercise()) == ('paused', 'pending')
    finally:
        state_store.DB_PATH = previous
        state_store._workflows_to_resume.clear()
    ledger = DependencyLedger(); ledger.add_node('result'); ledger.rollback('result', 'operator rollback')
    assert ledger.is_stale('result') is True
    assert ledger.events()[-1].kind == 'rollback'
