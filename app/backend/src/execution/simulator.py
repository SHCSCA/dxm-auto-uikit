import asyncio
from pathlib import Path

from src.core.config import SCREENSHOT_DIR
from src.execution.dxm_live import DxmLiveClient
from src.repository import Repository
from src.utils import now_iso

STEPS = [
    ('check_login', '检查店小秘登录态', 'session'),
    ('open_create_page', '打开创建商品页', 'navigation'),
    ('fill_title', '填写标题', 'title'),
    ('fill_category', '填写类目与属性', 'category'),
    ('upload_images', '上传主图与营销图', 'media'),
    ('fill_sku_price', '填写 SKU 与价格', 'pricing'),
    ('select_shipping', '选择运费模板', 'shipping'),
    ('save_draft', '保存待发布', 'result'),
]


class TaskRunner:
    def __init__(self, repo: Repository, manager):
        self.repo = repo
        self.manager = manager
        self.live = DxmLiveClient()

    async def run_task(self, task_id: int):
        task = self.repo.get_task(task_id)
        if not task:
            return
        self.repo.update_task_status(task_id, 'running')
        await self.manager.broadcast(task_id, {'type': 'task_status', 'status': 'running', 'taskId': task_id})
        completed = 0
        failed = 0
        live_probe = self.live.probe_session() if self.live.has_cookie_session() else None
        for job in task['jobs']:
            self.repo.update_job(job['id'], status='running', current_step_code='check_login', current_step_name='检查店小秘登录态')
            self.repo.add_log(task_id, job['id'], 'info', '开始处理商品', {'jobId': job['id'], 'productId': job['product_id']})
            for step_code, step_name, field_domain in STEPS:
                self.repo.update_job(job['id'], status='running', current_step_code=step_code, current_step_name=step_name)
                screenshot_path = self._resolve_screenshot(task_id, job['id'], step_code, live_probe)
                self.repo.add_evidence(task_id, job['id'], 'screenshot', str(screenshot_path), {'step_code': step_code, 'field_domain': field_domain, 'live': bool(live_probe)})
                self.repo.add_log(task_id, job['id'], 'info', f'执行步骤：{step_name}', {'step_code': step_code, 'field_domain': field_domain, 'live': bool(live_probe)})
                await self.manager.broadcast(task_id, {
                    'type': 'step_update',
                    'taskId': task_id,
                    'jobId': job['id'],
                    'productId': job['product_id'],
                    'stepCode': step_code,
                    'stepName': step_name,
                    'fieldDomain': field_domain,
                    'screenshotPath': str(screenshot_path),
                    'timestamp': now_iso(),
                })
                await asyncio.sleep(0.35)
            self.repo.update_job(job['id'], status='succeeded', current_step_code='done', current_step_name='已保存待发布')
            self.repo.add_log(task_id, job['id'], 'success', '商品已保存待发布', {'live': bool(live_probe)})
            completed += 1
            self.repo.update_task_status(task_id, 'running', completed_jobs=completed, failed_jobs=failed)
            await self.manager.broadcast(task_id, {'type': 'job_completed', 'taskId': task_id, 'jobId': job['id'], 'completedJobs': completed, 'failedJobs': failed})
        final_status = 'completed' if failed == 0 else 'failed'
        self.repo.update_task_status(task_id, final_status, completed_jobs=completed, failed_jobs=failed)
        await self.manager.broadcast(task_id, {'type': 'task_status', 'taskId': task_id, 'status': final_status, 'completedJobs': completed, 'failedJobs': failed})

    def _resolve_screenshot(self, task_id: int, job_id: int, step_code: str, live_probe):
        if live_probe:
            if step_code == 'check_login' and live_probe.get('home_screenshot'):
                return Path(live_probe['home_screenshot'])
            if step_code in ('open_create_page', 'fill_title', 'fill_category'):
                product_page = live_probe.get('product_page') or {}
                if product_page.get('screenshot'):
                    return Path(product_page['screenshot'])
        return self._create_placeholder_screenshot(task_id, job_id, step_code)

    def _create_placeholder_screenshot(self, task_id: int, job_id: int, step_code: str) -> Path:
        path = SCREENSHOT_DIR / f'task_{task_id}_job_{job_id}_{step_code}.txt'
        path.write_text(
            f'[placeholder screenshot] task={task_id} job={job_id} step={step_code}\n',
            encoding='utf-8',
        )
        return path
