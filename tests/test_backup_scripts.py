"""备份/容灾脚本护栏。

这些脚本没有单元测试却承担最高代价的失败(数据没了才发现),且历史上真踩过三个坑:
`&& echo` 吞掉异地推送失败、cron 读不到 env 文件、cron 精简 PATH 找不到 ~/bin 的二进制。
本文件把这几条不变量钉死,顺带对所有 shell 脚本做语法检查。
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHELL_SCRIPTS = sorted(ROOT.glob('deploy/*.sh')) + sorted(ROOT.glob('scripts/*.sh'))


def _read(p):
    return (ROOT / p).read_text(encoding='utf-8')


def _code(p):
    """去掉整行注释:护栏要断言的是脚本"做了什么",不能被解释坑位的注释误伤。"""
    return '\n'.join(ln for ln in _read(p).splitlines() if not ln.lstrip().startswith('#'))


def test_all_shell_scripts_parse():
    assert SHELL_SCRIPTS, '没找到任何 shell 脚本,glob 写错了'
    for p in SHELL_SCRIPTS:
        r = subprocess.run(['bash', '-n', str(p)], capture_output=True, text=True)
        assert r.returncode == 0, f'{p.name} 语法错误:{r.stderr}'


def test_no_head_in_pipeline_under_pipefail():
    """`set -o pipefail` + `cmd | head -n` = 上游收 SIGPIPE、流水线以 141 退出、脚本被中断。

    输出量小的时候常常侥幸不触发,所以是间歇性的 —— 恢复演练脚本上真踩过。取首行一律用 awk。
    """
    for p in SHELL_SCRIPTS:
        src = p.read_text(encoding='utf-8')
        if 'pipefail' not in src:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith('#'):
                continue
            assert '| head' not in line.replace('|head', '| head'), \
                f'{p.name}:{i} 在 pipefail 下用了 `| head`,改用 awk 取首行:{line.strip()}'


def test_backup_fails_loudly_on_offsite_error():
    """异地推送失败必须非零退出 —— 静默成功的容灾等于没有容灾。"""
    s = _read('deploy/backup.sh')
    assert 'exit 3' in s
    assert 'offsite_ok' in s


def test_backup_verifies_remote_bytes():
    """rclone copy 退出 0 不等于对象可读,必须回查远端字节数。"""
    s = _read('deploy/backup.sh')
    assert 'verify_remote_file' in s
    assert 'lsl' in s


def test_backup_prunes_remote():
    """本地 find -mtime 只清本地;远端不清会无界增长到超出 R2 免费额度。"""
    s = _read('deploy/backup.sh')
    assert 'QB_OFFSITE_KEEP_DAYS' in s
    assert '--min-age' in s
    # --include 双保险:桶里混有他用数据时也只删本脚本自己的产物
    assert "--include \"db_*.sqlite3\"" in s


def test_backup_resolves_rclone_explicitly():
    """deploy 无 sudo,rclone 在 ~/bin;cron 的 PATH 找不到,必须显式解析。"""
    s = _read('deploy/backup.sh')
    assert 'QB_RCLONE_BIN' in s
    assert 'bin/rclone' in s


def test_offsite_config_never_takes_secret_on_argv():
    """密钥走环境变量;`rclone config create` 会把 secret 摆进命令行让 ps 可见。"""
    s = _read('deploy/setup_offsite_r2.sh')
    assert 'rclone config create' not in _code('deploy/setup_offsite_r2.sh')
    assert 'R2_SECRET_ACCESS_KEY' in s
    assert 'chmod 600' in s
    assert 'umask 077' in s


def test_offsite_setup_verifies_before_wiring_cron():
    """往返验证失败必须在改 crontab 之前中止,不能留下一个假装能用的开关。"""
    s = _read('deploy/setup_offsite_r2.sh')
    probe_at = s.index('copyto')
    cron_at = s.index('crontab -')
    assert probe_at < cron_at, '往返验证必须排在写 crontab 之前'
    assert 'exit 4' in s


def test_restore_drill_is_read_only_and_self_cleaning():
    """演练不得改生产:只读打开生产库,临时目录 trap 清掉。"""
    s = _read('deploy/restore_drill.sh')
    assert 'sqlite3 -readonly "$LIVE_DB"' in s
    assert "trap 'rm -rf \"$WORK\"' EXIT" in s
    assert 'integrity_check' in s


def test_crontab_example_injects_env_natively():
    """不能回退到 `. /etc/question-bank.env`:该文件 600 root:deploy,且不带 export。"""
    s = _read('deploy/crontab.example')
    assert 'question-bank.env' not in _code('deploy/crontab.example')
    assert 'QB_OFFSITE_REMOTE=' in s
    assert 'QB_RCLONE_BIN=' in s
    # backup.sh 同样不许自己去 source 那个文件
    assert 'question-bank.env' not in _code('deploy/backup.sh')
