"""使用真实打包复制器和验包函数验证缓存边界，不启动桌面或浏览器。"""

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
DESKTOP = ROOT / 'app' / 'desktop'
VERIFIER = ROOT / 'scripts' / 'verify-desktop-package.ps1'
SHELL = shutil.which('powershell') or shutil.which('pwsh')
NODE = shutil.which('node')


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _run_clean_check(executable):
    assert SHELL, '需要 PowerShell 运行真实验包函数'
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        "$Tokens=$null; $ParseErrors=$null; "
        "$Tree=[Management.Automation.Language.Parser]::ParseFile("
        + _literal(VERIFIER)
        + ",[ref]$Tokens,[ref]$ParseErrors); "
        "if($ParseErrors.Count){throw 'VERIFIER_PARSE_FAILED'}; "
        "$Function=$Tree.Find({param($Node) "
        "$Node -is [Management.Automation.Language.FunctionDefinitionAst] "
        "-and $Node.Name -eq 'Assert-PackagedRuntimeClean'},$true); "
        "if(!$Function){throw 'VERIFIER_FUNCTION_MISSING'}; "
        "Invoke-Expression $Function.Extent.Text; "
        "Assert-PackagedRuntimeClean -ExePath " + _literal(executable)
    )
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)


def _package(tmp_path):
    package = tmp_path / 'synthetic-package'
    for relative in ('app/backend', 'tools/probes'):
        (package / 'resources' / relative).mkdir(parents=True)
    executable = package / 'DXM-Agent-Console.exe'
    executable.write_bytes(b'not-an-executable')
    return executable


@pytest.mark.parametrize('relative,directory', [
    ('app/backend/loose.pyc', False),
    ('app/backend/nested/__pycache__', True),
    ('tools/probes/loose.pyc', False),
    ('tools/probes/nested/__pycache__/probe.cpython-313.pyc', False),
    ('tools/probes/nested/empty/__pycache__', True),
])
def test_actual_verifier_rejects_bytecode_files_and_empty_cache_directories(tmp_path, relative, directory):
    executable = _package(tmp_path)
    artifact = executable.parent / 'resources' / relative
    if directory:
        artifact.mkdir(parents=True)
    else:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b'synthetic-cache-sentinel')
    result = _run_clean_check(executable)
    assert result.returncode != 0, f'真实验包函数错误放行 {relative}'
    assert 'Packaged runtime generated Python bytecode cache' in result.stderr
    assert artifact.exists(), '检查只能拒绝，不能自行删除候选包文件'


def test_actual_verifier_accepts_clean_sources_without_modifying_them(tmp_path):
    executable = _package(tmp_path)
    clean_source = '# 合成只读源码\n'.encode('utf-8')
    paths = [executable.parent / 'resources' / relative for relative in
        ('app/backend/src/main.py', 'tools/probes/l2_readonly_probe.py', 'tools/probes/nested/helper.py')]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(clean_source)
    result = _run_clean_check(executable)
    assert result.returncode == 0, result.stderr
    assert all(path.read_bytes() == clean_source for path in paths)


def test_builder_actual_extra_resource_copy_keeps_sources_and_excludes_probe_caches(tmp_path):
    assert NODE, '需要 Node 运行当前安装的 electron-builder 复制器'
    workspace = tmp_path / 'synthetic-workspace'
    desktop = workspace / 'app' / 'desktop'
    desktop.mkdir(parents=True)
    probes = workspace / 'tools' / 'probes'
    clean = ('l2_readonly_probe.py', 'nested/helper.py', 'metadata.json')
    cache = ('loose.pyc', '__pycache__/probe.cpython-313.pyc', 'nested/__pycache__/helper.pyc')
    for relative in clean + cache:
        path = probes / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic-resource-sentinel')
    (probes / 'nested' / 'empty' / '__pycache__').mkdir(parents=True)
    output = workspace / 'packaged-resources'
    script = r"""
const fs=require('node:fs'), path=require('node:path');
const realDesktop=process.argv[1], desktop=process.argv[2], output=process.argv[3];
const yaml=require(path.join(realDesktop,'node_modules','js-yaml'));
const {getFileMatchers,copyFiles}=require(path.join(realDesktop,'node_modules','app-builder-lib','out','fileMatcher'));
const config=yaml.load(fs.readFileSync(path.join(realDesktop,'electron-builder.yml'),'utf8'));
const matches=config.extraResources.filter(entry=>entry.from==='../../tools/probes');
if(matches.length!==1)throw Error('PROBE_RESOURCE_MAPPING_REQUIRED');
const matchers=getFileMatchers({extraResources:matches},'extraResources',output,{
  defaultSrc:desktop,macroExpander:value=>value,customBuildOptions:{},globalOutDir:output});
copyFiles(matchers,null,false).then(()=>{
  const files=[],directories=[];
  function walk(root,prefix=''){
    for(const entry of fs.readdirSync(root,{withFileTypes:true})){
      const relative=prefix+entry.name;
      if(entry.isDirectory()){directories.push(relative);walk(path.join(root,entry.name),relative+'/');}
      else files.push(relative);
    }
  }
  walk(path.join(output,'tools','probes'));
  process.stdout.write(JSON.stringify({files:files.sort(),directories:directories.sort()}));
}).catch(error=>{process.stderr.write(String(error.stack));process.exitCode=1;});
"""
    result = subprocess.run([NODE, '-e', script, str(DESKTOP), str(desktop), str(output)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual['files'] == sorted(clean)
    assert not any('__pycache__' in path.split('/') for path in actual['directories'])
    assert all((probes / path).read_bytes() == b'synthetic-resource-sentinel' for path in cache)
