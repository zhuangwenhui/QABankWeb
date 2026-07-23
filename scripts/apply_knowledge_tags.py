"""把知识点分类结果(tagmap.json:{question_id: [tag, ...]})幂等写入 tags / question_tags。

- 幂等:标签按 (name, category) 去重复用;question_tags 按 (question_id, tag_id) 去重;
  DB 里已不在本轮 tagmap 的旧 (question,知识点tag) 关联可选清理(--prune)。
- 只处理 category='知识点';不碰 Question.tags 的 JSON 自由标签。
- 跳过 DB 中不存在的 question_id(如本地库题数少于生产)。

用法:apply_knowledge_tags.py --db instance/question_bank.db --tagmap tagmap.json [--prune]
"""
import argparse
import json
import sqlite3

CATEGORY = '知识点'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--tagmap', required=True)
    ap.add_argument('--prune', action='store_true',
                    help='删除本轮未覆盖的旧知识点关联(仅限本脚本处理到的题)')
    a = ap.parse_args()

    tagmap = json.load(open(a.tagmap, encoding='utf-8'))
    con = sqlite3.connect(a.db)
    con.execute('PRAGMA foreign_keys=ON')
    cur = con.cursor()

    existing_q = {r[0] for r in cur.execute('SELECT id FROM questions')}
    # 现有知识点标签 name->id
    tag_id = {}
    for tid, name in cur.execute(
            "SELECT id, name FROM tags WHERE category=?", (CATEGORY,)):
        tag_id[name] = tid

    def get_tag(name):
        if name in tag_id:
            return tag_id[name]
        cur.execute("INSERT INTO tags(name, category) VALUES(?, ?)", (name, CATEGORY))
        tag_id[name] = cur.lastrowid
        return tag_id[name]

    # 现有关联 (question_id, tag_id) 集合(仅知识点)
    have = set()
    for qid, tid in cur.execute(
            "SELECT qt.question_id, qt.tag_id FROM question_tags qt "
            "JOIN tags t ON t.id=qt.tag_id WHERE t.category=?", (CATEGORY,)):
        have.add((qid, tid))

    tags_created0 = len(tag_id)
    links_added = 0
    links_removed = 0
    skipped_q = 0
    touched_q = []

    for qid_s, names in tagmap.items():
        qid = int(qid_s)
        if qid not in existing_q:
            skipped_q += 1
            continue
        touched_q.append(qid)
        want_tids = {get_tag(n) for n in names}
        for tid in want_tids:
            if (qid, tid) not in have:
                cur.execute("INSERT INTO question_tags(question_id, tag_id) VALUES(?, ?)", (qid, tid))
                have.add((qid, tid))
                links_added += 1
        if a.prune:
            cur_tids = {tid for (q, tid) in have if q == qid}
            for tid in cur_tids - want_tids:
                cur.execute("DELETE FROM question_tags WHERE question_id=? AND tag_id=?", (qid, tid))
                have.discard((qid, tid))
                links_removed += 1

    con.commit()
    tags_created = len(tag_id) - tags_created0
    print(f"题目命中 {len(touched_q)}  跳过(DB无此题) {skipped_q}")
    print(f"新建标签 {tags_created}  新增关联 {links_added}  删除关联 {links_removed}")
    print(f"当前知识点标签总数 {len(tag_id)}  关联总数 {len(have)}")
    con.close()


if __name__ == '__main__':
    main()
