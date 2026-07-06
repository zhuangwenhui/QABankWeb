"""PDF 生成:属主校验、TTL 清理、并发 429、N+1 修复后的行为不变性。"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pdf_gen
from models import ErrorBook, GeneratedFile, Question, User, db
from tests.conftest import get_csrf


def _seed_error_book(app, username='student'):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        q = Question(subject='线性代数', chapter='2019', difficulty='中等',
                     source='测试来源', question_latex=r'求 $A$ 的固有值',
                     solution_latex=r'$\lambda=1$')
        db.session.add(q)
        db.session.flush()
        db.session.add(ErrorBook(user_id=user.id, question_id=q.id, notes='粗心'))
        db.session.commit()
        return q.id


def _generate(client, csrf_token, **extra):
    payload = {'template': 'error_book_template', 'title': '测试卷',
               'include_solutions': True}
    payload.update(extra)
    return client.post('/api/error_book/generate_pdf', json=payload,
                       headers={'X-CSRFToken': csrf_token})


def _result_url(data):
    return data.get('pdf_url') or data.get('tex_url')


def test_generate_registers_owner_and_downloadable(app, client, login):
    import shutil as _shutil
    _seed_error_book(app)
    login('student', 'StudentPass123456')
    r = _generate(client, get_csrf(client))
    assert r.status_code == 200
    data = r.get_json()['data']
    if _shutil.which('xelatex') or _shutil.which('pdflatex'):
        assert 'pdf_url' in data
    else:
        assert data.get('engine_missing') is True
    url = _result_url(data)
    with app.app_context():
        rec = GeneratedFile.query.filter_by(filename=data['filename']).first()
        assert rec is not None
        assert User.query.get(rec.user_id).username == 'student'
    assert client.get(url).status_code == 200


def test_generated_file_not_accessible_by_other_user(app, client, login):
    _seed_error_book(app)
    login('student', 'StudentPass123456')
    data = _generate(client, get_csrf(client)).get_json()['data']
    url = _result_url(data)
    client.get('/logout')
    login('admin', 'AdminPass123456')
    assert client.get(url).status_code == 200
    with app.app_context():
        other = User(username='other', role='student')
        other.set_password('OtherPass1234567')
        db.session.add(other)
        db.session.commit()
    client.get('/logout')
    login('other', 'OtherPass1234567')
    assert client.get(url).status_code == 404


def test_unregistered_generated_file_404(app, client, login):
    login('student', 'StudentPass123456')
    assert client.get('/generated/deadbeef0000.tex').status_code == 404


def test_ttl_cleanup_removes_old_files(app, client, login):
    _seed_error_book(app)
    login('student', 'StudentPass123456')
    folder = app.config['GENERATED_PDF_FOLDER']
    old_path = os.path.join(folder, 'oldoldoldold.tex')
    with open(old_path, 'w') as f:
        f.write('%% old')
    with app.app_context():
        user = User.query.filter_by(username='student').first()
        db.session.add(GeneratedFile(filename='oldoldoldold.tex', user_id=user.id,
                                     created_at=datetime.now() - timedelta(hours=25)))
        db.session.commit()
    _generate(client, get_csrf(client))
    assert not os.path.exists(old_path)
    with app.app_context():
        assert GeneratedFile.query.filter_by(filename='oldoldoldold.tex').first() is None


def test_busy_returns_429(app, client, login, monkeypatch):
    _seed_error_book(app)
    login('student', 'StudentPass123456')
    monkeypatch.setattr(pdf_gen._compile_slot, 'acquire', lambda blocking=False: False)
    r = _generate(client, get_csrf(client))
    assert r.status_code == 429
    assert r.get_json()['code'] == 'BUSY'


def test_compile_failure_cleans_and_not_registered(app, client, login, monkeypatch):
    """引擎启动失败(OSError 分支):本次 .tex/.pdf 被清理、不登记、响应 500(spec §3.5)。"""
    _seed_error_book(app)
    login('student', 'StudentPass123456')
    monkeypatch.setattr(pdf_gen.shutil, 'which', lambda name: '/nonexistent/fake-latex')
    r = _generate(client, get_csrf(client))
    assert r.status_code == 500
    with app.app_context():
        assert GeneratedFile.query.count() == 0
    folder = app.config['GENERATED_PDF_FOLDER']
    leftovers = [n for n in os.listdir(folder) if n.endswith(('.tex', '.pdf'))]
    assert leftovers == []
