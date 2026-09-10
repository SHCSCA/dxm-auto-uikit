"""Read-only Path B prerequisites, never SAVE authorization or release evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def finding(status, code, message, next_action):
    return dict(status=status, code=code, message=message, nextAction=next_action)


def resolve_data_dir(repo_root, explicit, env):
    return Path(explicit or env.get('DXM_DATA_DIR') or repo_root / 'data').expanduser().resolve()


def cookie_presence(data_dir):
    # File presence is not session validity. Never deserialize or hash credentials.
    exists = (data_dir / 'sessions' / 'dianxiaomi_cookies.json').is_file()
    return finding(
        'info' if exists else 'blocked', 'SESSION_FILE_PRESENT' if exists else 'SESSION_FILE_MISSING',
        '会话文件存在；未读取内容，也不能据此判定已登录。' if exists else '当前运行目录没有持久会话文件。',
        '使用本应用的可见登录入口；应用自行保存会话，不需要扩展导出 Cookie。',
    )


def validate_base_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', '::1'}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('诊断地址仅允许本机 HTTP 根地址，不能含凭证或其他路径。')
    if parsed.port is not None and parsed.port < 1:
        raise ValueError('无效的本机端口。')
    return value.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def local_json(base_url, path):
    # Ignore system proxies and never follow redirects out of the scoped app.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(base_url + path, timeout=3) as response:
        body = response.read(262145)
    if len(body) > 262144:
        raise ValueError('本机响应过大。')
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError('本机响应格式不正确。')
    return result


def git_head(repo_root):
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=repo_root,
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def backend_session(base_url, repo_root, data_dir):
    try:
        health = local_json(validate_base_url(base_url), '/health')
    except Exception:
        return finding('blocked', 'BACKEND_UNREACHABLE', '本应用 /health 尚不可达。',
                       '先确认应用启动权限和端口；不要杀掉其他应用或删除运行锁。')
    identity = health.get('runtimeIdentity') or {}
    current_head = git_head(repo_root)
    if (not isinstance(identity, dict) or health.get('status') != 'ok'
            or identity.get('schemaVersion') != 'dxm.runtime.identity.v1'
            or not identity.get('instanceId') or not current_head
            or identity.get('gitHead') != current_head
            or Path(str(identity.get('resourceRoot') or '')).resolve() != repo_root.resolve()
            or Path(str(identity.get('dataDir') or '')).resolve() != data_dir.resolve()):
        return finding('blocked', 'RUNTIME_IDENTITY_MISMATCH', '后端身份、代码版本或运行目录与本次诊断不一致。',
                       '核对本应用地址及 DXM_DATA_DIR；不查询其他实例的会话。')
    try:
        live = local_json(base_url.rstrip('/'), '/api/dxm/live-status')
        still_current = local_json(base_url.rstrip('/'), '/health')
        if still_current.get('runtimeIdentity') != identity:
            raise ValueError('Runtime changed during diagnostic')
    except Exception:
        return finding('blocked', 'LIVE_SESSION_UNAVAILABLE', '同一后端的实时浏览器状态尚不可核验。',
                       '等待应用当前操作完成，再使用应用内登录或状态刷新。')
    ready = live.get('logged_in') is True and live.get('reader_ready') is True
    return finding('pass' if ready else 'blocked', 'SESSION_READY' if ready else 'SESSION_NOT_READY',
                   '同一实例报告实时会话可读；不是保存授权。' if ready else '后端已启动，但实时会话尚不可读。',
                   '仅在当前可见应用内完成登录/验证码；不要把已打开页面当作已登录。')


def scope_counts(data_dir):
    database = data_dir / 'sqlite' / 'dxm_auto_uikit.db'
    if not database.is_file():
        return finding('blocked', 'DATABASE_MISSING', '当前目录尚无数据库，诊断不会创建。', '由本应用持有运行租约后初始化。')
    if Path(str(database) + '-wal').exists() and not Path(str(database) + '-shm').exists():
        return finding('unknown', 'DATABASE_WAL_REQUIRES_OWNER', '数据库 WAL 状态需由应用持有者核验。', '诊断不创建共享内存或恢复数据库。')
    tables = dict(scopes='real_dxm_write_scopes', discoveryAttempts='real_dxm_path_b_discovery_attempts',
                  discoveryReceipts='real_dxm_path_b_discovery_receipts')
    try:
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            connection.execute('PRAGMA query_only = ON')
            counts = {key: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for key, table in tables.items()}
        finally:
            connection.close()
    except sqlite3.Error:
        return finding('unknown', 'SCOPE_REGISTRY_UNAVAILABLE', '当前范围账本不可只读核验。', '通过本应用核对数据库版本；诊断不修复或迁移。')
    result = finding('unknown' if counts['scopes'] else 'blocked', 'SCOPE_COUNTS_ONLY',
                     '只统计范围及两类 Discovery 记录，不读取授权内容；存在记录不代表授权有效。',
                     '真实执行仍须当前冻结方案、有效 scope、当次人工批准和逐动作账本校验。')
    result['counts'] = counts
    return result


def l2_evidence(data_dir, max_age_seconds):
    expected = data_dir / 'l2_readonly_probe'
    if not expected.is_dir():
        return finding('blocked', 'L2_CURRENT_DIRECTORY_MISSING', '当前运行目录没有 L2 证据。',
                       '实时登录可用后，经批准使用现有只读采集流程；不借用旧目录证据。')
    try:
        sys.path.insert(0, str(ROOT / 'app' / 'backend'))
        from src.services import delivery_workspace as delivery
        if delivery.DATA_DIR.resolve() != data_dir.resolve():
            raise ValueError('Data directory mismatch')
        gate = delivery.l2_real_probe_gate()
        latest = gate.get('latest') or {}
        selected = latest.get('selectedProbeResultDir')
        if selected is not None and Path(selected).resolve() != expected.resolve():
            return finding('blocked', 'L2_OTHER_DIRECTORY', '正式检查找到的是其他目录证据，本次不采信。',
                           '在当前 DXM_DATA_DIR 下重新取得经批准的只读证据。')
        if gate.get('status') != 'passed':
            return finding('blocked', 'L2_CANONICAL_GATE_FAILED', '现有证据未通过正式 L2 检查（完整性、真实目标、网络计数或时效）。',
                           '查看应用内 L2 明细并补齐真实证据；不修改安全阈值。')
        current_head = git_head(ROOT)
        script_hash = hashlib.sha256((ROOT / 'tools' / 'probes' / 'l2_readonly_probe.py').read_bytes()).hexdigest()
        targets = latest.get('realTargets') or {}
        if not current_head or any(
            targets.get(target, {}).get('git_head') != current_head
            or str(targets.get(target, {}).get('script_sha256') or '').lower() != script_hash
            for target in delivery.REQUIRED_L2_TARGETS
        ):
            return finding('blocked', 'L2_CODE_VERSION_MISMATCH', '证据不属于当前代码和采集脚本。', '完成代码修复后重新取得真实 L2 证据。')
        age = (latest.get('timeWindow') or {}).get('ageSeconds')
        if not isinstance(age, int) or not 0 <= age <= min(max_age_seconds, delivery.L2_REAL_TARGET_MAX_AGE_SECONDS):
            return finding('blocked', 'L2_EXPIRED', '真实 L2 证据不在当前有效期内。', '保持同一可见会话，重新取得经批准的只读证据。')
        return finding('pass', 'L2_FILE_GATE_PASSED', '当前目录证据通过正式文件检查；未读取 Cookie，尚不证明会话与授权绑定。',
                       '真实 Runner 仍须核验当前 session/scope/approval，不能凭此诊断保存。')
    except Exception:
        return finding('unknown', 'L2_INSPECTION_FAILED', '正式 L2 检查暂不可运行；未采用简化规则放行。', '检查后端依赖及证据格式。')


def diagnose(base_url, data_dir, max_age_seconds):
    replay_requested = os.environ.get('DXM_PATH_B_CLOSED_LOOP', '').strip() == '1'
    checks = dict(
        sessionFile=cookie_presence(data_dir),
        runtimeLease=finding('info', 'LEASE_FILE_NOT_REPLAY_FLAG',
                            '运行锁文件存在。' if (data_dir / '.dxm-runtime.lock').exists() else '运行锁文件不存在。',
                            '文件存在不代表锁被占用，也不是回放开关；由应用检查 OS 租约，不删除文件。'),
        replay=finding('blocked' if replay_requested else 'unknown',
                       'REPLAY_REQUESTED' if replay_requested else 'LIVE_ADAPTER_NOT_ATTESTED',
                       '当前启动环境请求回放模式。' if replay_requested else '当前诊断环境未请求回放；不能据此证明运行后端使用真实适配器。',
                       '真实执行必须走正式适配器，不能把回放或单元测试收据作为网站保存证据。'),
        backendSession=backend_session(base_url, ROOT, data_dir),
        l2=l2_evidence(data_dir, max_age_seconds),
        scopeRegistry=scope_counts(data_dir),
        production=finding('unknown', 'PRODUCTION_FLOW_NOT_VERIFIED',
                           '本诊断不验证五项真实能力、完整方案和实际保存读回；不签发批准。',
                           '先处理 BLOCKED.md 的生产接线缺口，再按正式流程取证及申请当前范围批准。'),
    )
    return dict(schema='dxm.path_b.prerequisite_diagnostic.v1', dataDir=str(data_dir),
                productionReady=False, checks=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--data-dir')
    parser.add_argument('--max-age-seconds', type=int, default=7200)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        base_url = validate_base_url(args.base_url)
        if not 1 <= args.max_age_seconds <= 7200:
            raise ValueError('诊断不能放宽正式 L2 两小时上限。')
        data_dir = resolve_data_dir(ROOT, args.data_dir, os.environ)
        os.environ['DXM_DATA_DIR'] = str(data_dir)  # This diagnostic child process only.
        report = diagnose(base_url, data_dir, args.max_age_seconds)
    except Exception:
        print('诊断配置或路径无效；没有启动应用或执行写入。', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f'当前运行目录: {data_dir}')
        for name, check in report['checks'].items():
            print(f"\n[{check['status'].upper()}] {name}: {check['message']}")
            print(f"  下一步: {check['nextAction']}")
            if 'counts' in check:
                print('  仅数量: ' + json.dumps(check['counts']))
        print('\n结论: 尚不具备真实保存就绪证明。诊断不启动浏览器、不执行 SAVE、不发布。')
    return 2  # Prerequisite information is never an authorization/readiness PASS.


if __name__ == '__main__':
    raise SystemExit(main())
