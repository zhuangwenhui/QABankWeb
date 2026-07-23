"""采点判题:上传作答 → 评分 → 存档(判题引擎默认 Stub,不发真 API)。

- 端点流程用 StubGrader(强制 ANTHROPIC_API_KEY='');
- ClaudeVisionGrader 单测 monkeypatch _post 回罐装 JSON,验提示构造与解析裁剪;
- 属主隔离、删除清图、题不存在/坏扩展名/超额图的拒绝。
"""
from io import BytesIO

from conftest import get_csrf
from models import Question, AnswerSubmission, db


def _seed_question(app):
    with app.app_context():
        q = Question(subject='数学', source='东大 X', difficulty='中等',
                     question_latex='∫ 求值', solution_latex='中文解',
                     solution_ja='日本語詳解')
        q.solution_structured_dict = {'houshin': '先分部', 'model': '=2',
                                       'shitten': '漏项', 'haiten': '分部3分,代入2分'}
        db.session.add(q)
        db.session.commit()
        return q.id


def _img(name='ans.png', blob=b'\x89PNG\r\n\x1a\nfake'):
    return (BytesIO(blob), name)


def _post_submission(client, token, qid, images):
    return client.post(f'/api/questions/{qid}/submissions',
                       data={'images': images},
                       content_type='multipart/form-data',
                       headers={'X-CSRFToken': token})


# --------------------------------------------------------------- 端点流程(Stub)
def test_create_submission_stub_flow(app, client, login):
    app.config['ANTHROPIC_API_KEY'] = ''   # 强制 Stub,不发真请求
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    r = _post_submission(client, token, qid, [_img('a.png'), _img('b.jpg')])
    assert r.status_code == 201, r.get_data(as_text=True)
    sub = r.get_json()['data']['submission']
    assert sub['status'] == 'graded'
    assert sub['grader'] == 'stub' and sub['model'] == 'stub'
    assert len(sub['image_paths']) == 2 and len(sub['image_urls']) == 2
    assert sub['image_urls'][0].startswith('/uploads/answer_')
    assert '未配置' in sub['feedback']       # 诚实占位
    assert sub['total_score'] == 0.0


def test_create_submission_persists_row(app, client, login):
    app.config['ANTHROPIC_API_KEY'] = ''
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    _post_submission(client, token, qid, [_img()])
    with app.app_context():
        assert AnswerSubmission.query.count() == 1
        s = AnswerSubmission.query.first()
        assert s.question_id == qid and s.status == 'graded'


def test_create_submission_no_images(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    r = _post_submission(client, token, qid, [])
    assert r.status_code == 400
    assert r.get_json()['success'] is False


def test_create_submission_too_many(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    imgs = [_img(f'{i}.png') for i in range(5)]
    r = _post_submission(client, token, qid, imgs)
    assert r.status_code == 400


def test_create_submission_bad_ext(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    r = _post_submission(client, token, qid, [_img('a.txt')])
    assert r.status_code == 400


def test_create_submission_question_404(app, client, login):
    login('student', 'StudentPass123456')
    _seed_question(app)
    token = get_csrf(client)
    r = _post_submission(client, token, 999999, [_img()])
    assert r.status_code == 404


def test_list_submissions_history(app, client, login):
    app.config['ANTHROPIC_API_KEY'] = ''
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    _post_submission(client, token, qid, [_img('a.png')])
    _post_submission(client, token, qid, [_img('b.png')])
    r = client.get(f'/api/questions/{qid}/submissions')
    subs = r.get_json()['data']['submissions']
    assert len(subs) == 2
    # 倒序:最新在前
    assert subs[0]['created_at'] >= subs[1]['created_at']


def test_owner_isolation(app, client, login):
    app.config['ANTHROPIC_API_KEY'] = ''
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    r = _post_submission(client, token, qid, [_img()])
    sid = r.get_json()['data']['submission']['id']
    # 换到 admin,不应看到 student 的提交
    client.get('/logout')
    login('admin', 'AdminPass123456')
    r2 = client.get(f'/api/submissions/{sid}')
    assert r2.status_code == 404


def test_delete_submission_removes_files(app, client, login):
    import os
    app.config['ANTHROPIC_API_KEY'] = ''
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    token = get_csrf(client)
    r = _post_submission(client, token, qid, [_img()])
    sub = r.get_json()['data']['submission']
    sid, fname = sub['id'], sub['image_paths'][0]
    fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
    assert os.path.isfile(fpath)
    rd = client.delete(f'/api/submissions/{sid}', headers={'X-CSRFToken': token})
    assert rd.status_code == 200
    assert not os.path.isfile(fpath)          # 图已清
    with app.app_context():
        assert db.session.get(AnswerSubmission, sid) is None


# --------------------------------------------------------------- grading 引擎单测
def test_get_grader_selects():
    from grading import get_grader, StubGrader, ClaudeVisionGrader
    assert isinstance(get_grader({'ANTHROPIC_API_KEY': ''}), StubGrader)
    assert isinstance(get_grader(None), StubGrader)
    g = get_grader({'ANTHROPIC_API_KEY': 'k', 'ANTHROPIC_GRADER_MODEL': 'm',
                    'ANTHROPIC_BASE_URL': 'https://x'})
    assert isinstance(g, ClaudeVisionGrader) and g.model == 'm'


def test_stub_grader_placeholder():
    from grading import StubGrader
    res = StubGrader().grade(question_text='q', reference_solution='s',
                             rubric={}, image_paths=['x.png'])
    assert res['model'] == 'stub' and res['total_score'] == 0.0
    assert res['breakdown'] == [] and '未配置' in res['feedback']


def test_claude_grader_builds_images_and_parses(tmp_path, monkeypatch):
    from grading import ClaudeVisionGrader
    img = tmp_path / 'ans.png'
    img.write_bytes(b'\x89PNG\r\n\x1a\nfake-bytes')
    g = ClaudeVisionGrader('key', model='claude-test')
    captured = {}
    canned = {'content': [{'type': 'text', 'text':
        '```json\n{"transcription":"x=2","breakdown":['
        '{"label":"分部","awarded":3,"max":3,"comment":"正确"},'
        '{"label":"代入","awarded":1,"max":2,"comment":"算错"}],'
        '"feedback":"思路对,注意计算"}\n```'}]}

    def fake_post(body):
        captured.update(body)
        return canned

    monkeypatch.setattr(g, '_post', fake_post)
    res = g.grade(question_text='∫', reference_solution='ref',
                  rubric={'haiten': '分部3分,代入2分'}, image_paths=[str(img)])
    # 提示 + 图片块都进了 messages
    content = captured['messages'][0]['content']
    assert content[0]['type'] == 'text' and '采点标准' in content[0]['text']
    assert content[1]['type'] == 'image'
    assert content[1]['source']['media_type'] == 'image/png'
    # total/max 由 breakdown 求和(模型未显式给)
    assert res['total_score'] == 4.0 and res['max_score'] == 5.0
    assert res['transcription'] == 'x=2' and res['model'] == 'claude-test'
    assert res['breakdown'][0]['label'] == '分部'


def test_claude_grader_http_error(tmp_path, monkeypatch):
    from grading import ClaudeVisionGrader, GradingError
    img = tmp_path / 'a.png'
    img.write_bytes(b'x')
    g = ClaudeVisionGrader('key')

    def boom(body):
        raise GradingError('Anthropic API 401:bad key')

    monkeypatch.setattr(g, '_post', boom)
    try:
        g.grade(question_text='q', reference_solution='r', rubric={}, image_paths=[str(img)])
        assert False, '应抛 GradingError'
    except GradingError as e:
        assert '401' in str(e)


def test_extract_json_and_normalize():
    from grading import _extract_json, _normalize
    d = _extract_json('前言 {"a":1} 后语')
    assert d == {'a': 1}
    norm = _normalize({'breakdown': [{'label': 'L', 'awarded': 2, 'max': 4, 'comment': ''}]},
                      'mdl')
    assert norm['total_score'] == 2.0 and norm['max_score'] == 4.0 and norm['model'] == 'mdl'
