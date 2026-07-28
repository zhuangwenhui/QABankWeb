"""用生产的**内容**刷新本地开发库,让本地看到的东西和线上一样。

为什么需要它:`instance/question_bank.db` 是很早的种子库,只有 37 道题、0 个题单、0 个标签,
而且**没有一道题带 `hints` 或 `solution_structured`**。后果是渐进提示、采点四段、题单页、
标签筛选这几块在本地**根本渲染不出来** —— 任何"本地看起来没问题"的结论对它们都不成立。
2026-07-27 那轮改动的渲染比对就吃了这个亏:两边都是空的,所以"逐字节一致"并不能说明什么。

只搬内容,不搬人:
    内容表(整表替换)  questions / tags / question_tags / question_lists / question_list_items
    用户表(一个都不读)users / error_book / feedback / generated_files / question_bookmarks
                       question_notes / question_progress / answer_submissions / view_logs

本地登录账号因此得以保留 —— 把 users 一起覆盖会把你知道的开发密码换成线上的哈希。

**本地引用题目的用户数据会被清空**(默认 error_book 与 view_logs 各若干行)。这不是图省事:
生产题目 id 是 1..360,本地是 1..37,两边有 35 个 id 重叠却指向**完全不同的题**。留着它们
不会报错,只会让错题本静默指向另一道题 —— 比悬空外键更难发现。脚本会先报数量再动手。

用法:
    scripts/refresh_dev_db.py                      # 试算:拉快照、报告将要做什么,不写库
    scripts/refresh_dev_db.py --apply              # 落库(写前自动备份本地库)
    scripts/refresh_dev_db.py --snapshot /tmp/x.db # 复用已有快照,不走 SSH
    scripts/refresh_dev_db.py --apply --no-images  # 跳过 196 张题面图的同步

环境变量:QB_DEPLOY_KEY(默认 ~/.ssh/qbank_deploy)、QB_DEPLOY_HOST(默认 deploy@161.34.33.67)
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 整表替换的内容表。顺序即**插入顺序**,保证父表先于子表;删除时反向走。
CONTENT_TABLES = [
    'questions',
    'tags',
    'question_tags',
    'question_lists',
    'question_list_items',
]

# 这些表里放的是人的东西,快照里的对应内容一概不读。
USER_TABLES = [
    'users', 'error_book', 'feedback', 'generated_files', 'question_bookmarks',
    'question_notes', 'question_progress', 'answer_submissions', 'view_logs',
]

# 本地这些表按 question_id 引用题目;换了内容就必须清空(见模块开头的理由)。
QUESTION_SCOPED_USER_TABLES = [
    'error_book', 'view_logs', 'question_progress', 'question_notes',
    'question_bookmarks', 'answer_submissions',
]

REMOTE_DB = '/srv/question-bank/instance/question_bank.db'
REMOTE_UPLOADS = '/srv/question-bank/uploads/'

# 服务器端取快照用的是 SQLite backup API:它只读源库,且快照包含 WAL 里尚未 checkpoint
# 的内容。直接 scp 那个 .db 文件会漏掉 WAL —— 2026-07-27 就这么丢过一行,导致比对出现假差异。
SNAPSHOT_SNIPPET = (
    'python3 -c \''
    'import sqlite3,os;'
    's=sqlite3.connect("file:%s?mode=ro",uri=True);'
    'd=sqlite3.connect("/tmp/_qb_refresh_snap.db");'
    's.backup(d);d.close();s.close();'
    'print(os.path.getsize("/tmp/_qb_refresh_snap.db"))\'' % REMOTE_DB
)


def ssh_base(key, host):
    return ['ssh', '-i', key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', host]


def pull_snapshot(key, host, dest):
    """在服务器上做一致快照并取回。全程只读生产库。"""
    print(f'[1/4] 从 {host} 取生产快照(backup API,只读)…')
    out = subprocess.run(ssh_base(key, host) + [SNAPSHOT_SNIPPET],
                         check=True, capture_output=True, text=True)
    print(f'      服务器侧快照 {out.stdout.strip()} 字节')
    subprocess.run(['scp', '-q', '-i', key, '-o', 'BatchMode=yes',
                    f'{host}:/tmp/_qb_refresh_snap.db', dest], check=True)
    subprocess.run(ssh_base(key, host) + ['rm -f /tmp/_qb_refresh_snap.db'], check=True)
    print(f'      已取回 {os.path.getsize(dest)} 字节')


def sync_images(key, host, apply_):
    """同步题面图。不加 --delete:本地多出来的文件(含 uploads/.gitkeep)不该被远端决定生死。"""
    local = os.path.join(ROOT, 'uploads') + '/'
    cmd = ['rsync', '-a', '--stats', '-e', f'ssh -i {key} -o BatchMode=yes',
           f'{host}:{REMOTE_UPLOADS}', local]
    if not apply_:
        cmd.insert(1, '--dry-run')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f'      ⚠ rsync 失败({r.returncode}):{r.stderr.strip()[:200]}')
        return False
    for key_line in ('Number of regular files transferred', 'Total file size'):
        for line in r.stdout.splitlines():
            if line.startswith(key_line):
                print('      ' + line.strip())
    return True


def table_counts(con, tables):
    return {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}


def restore(con, bak, db):
    """从备份回滚。必须先关连接:库在 WAL 模式下,盖着一个开着的连接换文件会读到混合状态。"""
    con.close()
    shutil.copy2(bak, db)
    for suffix in ('-wal', '-shm'):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)


def main():
    ap = argparse.ArgumentParser(description='用生产内容刷新本地开发库(只搬内容,不搬用户)')
    ap.add_argument('--db', default=os.path.join(ROOT, 'instance', 'question_bank.db'),
                    help='要刷新的本地库(默认 instance/question_bank.db)')
    ap.add_argument('--snapshot', help='已有的生产快照;不给则通过 SSH 现取')
    ap.add_argument('--apply', action='store_true', help='真正写库(默认只试算)')
    ap.add_argument('--no-images', action='store_true', help='跳过 uploads/ 同步')
    ap.add_argument('--key', default=os.environ.get('QB_DEPLOY_KEY',
                    os.path.expanduser('~/.ssh/qbank_deploy')))
    ap.add_argument('--host', default=os.environ.get('QB_DEPLOY_HOST', 'deploy@161.34.33.67'))
    a = ap.parse_args()

    # 防呆:这个脚本会 DELETE 整张表,绝不能对着生产库跑。
    if os.path.abspath(a.db).startswith('/srv/'):
        sys.exit('拒绝执行:--db 指向 /srv/,这是生产路径。本脚本只用于刷新本地开发库。')
    if not os.path.exists(a.db):
        sys.exit(f'本地库不存在:{a.db}(先跑 flask db upgrade 建表)')

    tmpdir = tempfile.mkdtemp(prefix='qb_refresh_')
    try:
        snap = a.snapshot
        if snap:
            print(f'[1/4] 使用已有快照 {snap}')
        else:
            snap = os.path.join(tmpdir, 'prod_snap.db')
            pull_snapshot(a.key, a.host, snap)

        src = sqlite3.connect(f'file:{snap}?mode=ro', uri=True)
        dst = sqlite3.connect(a.db)

        # 结构必须同版本。否则整表 INSERT ... SELECT * 会因列数不同而失败,
        # 或更糟——列数碰巧相同但语义错位,静默写进错的列。
        print('[2/4] 校验结构版本…')
        sv = src.execute('SELECT version_num FROM alembic_version').fetchone()[0]
        dv = dst.execute('SELECT version_num FROM alembic_version').fetchone()[0]
        print(f'      生产 {sv} / 本地 {dv}')
        if sv != dv:
            sys.exit(f'拒绝执行:结构版本不一致(生产 {sv},本地 {dv})。\n'
                     f'先在本地跑 flask db upgrade 追平,再重跑本脚本。')

        # 逐表比对列名,防止同一 revision 下本地手工改过表结构。
        for t in CONTENT_TABLES:
            sc = [r[1] for r in src.execute(f'PRAGMA table_info({t})')]
            dc = [r[1] for r in dst.execute(f'PRAGMA table_info({t})')]
            if sc != dc:
                sys.exit(f'拒绝执行:{t} 的列不一致\n  生产 {sc}\n  本地 {dc}')

        print('[3/4] 盘点改动…')
        before = table_counts(dst, CONTENT_TABLES)
        after = table_counts(src, CONTENT_TABLES)
        for t in CONTENT_TABLES:
            print(f'      {t:22s} {before[t]:>5} → {after[t]:<5}')

        wipe = {t: n for t, n in table_counts(dst, QUESTION_SCOPED_USER_TABLES).items() if n}
        if wipe:
            print('      将清空(引用旧题 id,换内容后会指向另一道题):')
            for t, n in wipe.items():
                print(f'        {t:20s} {n} 行')
        kept = table_counts(dst, ['users'])['users']
        print(f'      保留本地账号 users {kept} 行(不从快照读)')

        if not a.apply:
            print('\n(试算结束,未写库也未同步图片;加 --apply 才落盘)')
            if not a.no_images:
                print('[4/4] 图片同步试算…')
                sync_images(a.key, a.host, False)
            return 0

        # 用 backup API 而不是 cp:本地库跑在 WAL 模式下,单拷 .db 会漏掉 -wal 里
        # 尚未 checkpoint 的内容,备份出来的是个旧状态 —— 真要回滚时才发现不对就晚了。
        bak = a.db + '.bak'
        bakcon = sqlite3.connect(bak)
        dst.backup(bakcon)
        bakcon.close()
        print(f'      已备份本地库 → {bak}({os.path.getsize(bak)} 字节)')

        # 外键设 OFF:内容表是整表替换,过程中必然出现「子表指向已删父行」的中间态。
        # 换完之后再打开并跑 foreign_key_check 做全库校验 —— 这比全程 ON 更简单,
        # 也更严格(它会检查所有表,不只是本次动过的)。
        # ATTACH 必须在事务外执行,SQLite 不允许事务中挂库,所以先挂再开 with。
        dst.commit()
        dst.execute('PRAGMA foreign_keys=OFF')
        dst.execute('ATTACH DATABASE ? AS snap', (snap,))
        try:
            with dst:
                for t in QUESTION_SCOPED_USER_TABLES:
                    dst.execute(f'DELETE FROM {t}')
                for t in reversed(CONTENT_TABLES):
                    dst.execute(f'DELETE FROM {t}')
                for t in CONTENT_TABLES:
                    dst.execute(f'INSERT INTO {t} SELECT * FROM snap.{t}')
                # 题单的 owner 指向生产的 admin;本地 admin 未必是同一个 id。
                admin = dst.execute(
                    "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
                if admin:
                    dst.execute('UPDATE question_lists SET owner_id=?', (admin[0],))
                    print(f'      题单 owner_id 已改绑本地 admin(id={admin[0]})')
                else:
                    print('      ⚠ 本地无 admin 账号,题单 owner_id 保持生产原值')
        finally:
            dst.execute('DETACH DATABASE snap')
        dst.execute('PRAGMA foreign_keys=ON')

        bad = dst.execute('PRAGMA foreign_key_check').fetchall()
        if bad:
            restore(dst, bak, a.db)
            sys.exit(f'外键校验失败({len(bad)} 处),已从备份回滚:{bad[:5]}')
        print('      ✓ 全库外键校验通过')

        got = table_counts(dst, CONTENT_TABLES)
        for t in CONTENT_TABLES:
            if got[t] != after[t]:
                restore(dst, bak, a.db)
                sys.exit(f'写入行数对不上:{t} 期望 {after[t]},实际 {got[t]};已从备份回滚')
        print('      ✓ 行数与快照一致')
        dst.close()
        src.close()

        if not a.no_images:
            print('[4/4] 同步题面图 uploads/ …')
            sync_images(a.key, a.host, True)
        else:
            print('[4/4] 按 --no-images 跳过图片同步(题面图会显示为裂图)')

        print('\n✓ 完成。本地库现在与生产内容一致,登录账号未变。')
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
