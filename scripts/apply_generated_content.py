"""把生成的渐进提示与采点四段幂等写入 Question.hints / Question.solution_structured。

输入 JSON:{ "<question_id>": {"hints":[...], "houshin":"...", "model":"...",
                              "shitten":"...", "haiten":"..."} , ... }
- hints → Question.hints(JSON 数组字符串)
- {houshin,model,shitten,haiten} → Question.solution_structured(JSON 对象字符串)
- 幂等:直接覆盖对应两列;跳过 DB 中不存在的 id;两列为 additive nullable,旧题不受影响。
- 不触碰 solution_latex / solution_ja(已验证的正文)。

用法:apply_generated_content.py --db instance/question_bank.db --content content.json
"""
import argparse
import json
import sqlite3

STRUCT_KEYS = ('houshin', 'model', 'shitten', 'haiten')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--content', required=True)
    a = ap.parse_args()

    content = json.load(open(a.content, encoding='utf-8'))
    con = sqlite3.connect(a.db)
    cur = con.cursor()
    existing = {r[0] for r in cur.execute('SELECT id FROM questions')}

    updated = 0
    skipped = 0
    for qid_s, c in content.items():
        qid = int(qid_s)
        if qid not in existing:
            skipped += 1
            continue
        hints = c.get('hints') or []
        struct = {k: (c.get(k) or '') for k in STRUCT_KEYS}
        cur.execute(
            'UPDATE questions SET hints=?, solution_structured=? WHERE id=?',
            (json.dumps(hints, ensure_ascii=False),
             json.dumps(struct, ensure_ascii=False),
             qid))
        updated += cur.rowcount

    con.commit()
    # 校验:随机看一条
    n_h = cur.execute("SELECT COUNT(*) FROM questions WHERE hints IS NOT NULL AND hints!='[]'").fetchone()[0]
    n_s = cur.execute("SELECT COUNT(*) FROM questions WHERE solution_structured IS NOT NULL AND solution_structured!='{}'").fetchone()[0]
    print(f'更新 {updated}  跳过(DB无此题) {skipped}')
    print(f'有提示的题 {n_h}  有采点的题 {n_s}')
    con.close()


if __name__ == '__main__':
    main()
