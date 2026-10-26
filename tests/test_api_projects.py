from fastapi.testclient import TestClient

from src.backend.api.workspace_files import get_index
from src.backend.main import create_app
from src.backend.services.app_config import AppConfigService
from src.backend.services.retrieval import RetrievalService
from tests.test_api_documents import FakeCoordinator


def test_remove_project_keeps_originals_and_does_not_resurrect_from_recents(tmp_path):
    root = tmp_path.resolve()
    first = root / 'first'; first.mkdir()
    second = root / 'second'; second.mkdir()
    file = first / 'original.txt'; file.write_text('original')
    config = AppConfigService(root / 'config.json')
    project1 = config.create_project('first', [str(first)])
    project2 = config.create_project('second', [str(second)])
    index = RetrievalService(root / 'index.sqlite3')
    app = create_app(FakeCoordinator(), config)
    app.dependency_overrides[get_index] = lambda: index
    with TestClient(app) as client:
        assert client.delete(f"/api/projects/{project2['id']}").status_code == 200
        assert [p['id'] for p in client.get('/api/projects').json()] == [project1['id']]
        assert config.workspace_info()['path'] == str(first)
        assert file.read_text() == 'original'
        reloaded = AppConfigService(config.path)
        assert [p['id'] for p in reloaded.projects()] == [project1['id']]
        assert client.delete(f"/api/projects/{project1['id']}").status_code == 200
        assert client.get('/api/projects').json() == []
        assert client.get('/api/workspace-files').json()['roots'] == []
        assert AppConfigService(config.path).projects() == []
        assert file.exists() and second.is_dir()


def test_project_removal_keeps_shared_source_for_remaining_project(tmp_path):
    root = tmp_path.resolve()
    a = root / 'a'; a.mkdir()
    b = root / 'b'; b.mkdir()
    shared = root / 'shared.txt'; shared.write_text('shared')
    config = AppConfigService(root / 'config.json')
    first = config.create_project('a', [str(a)])
    config.register_documents(str(a), first['id'], [{'path': str(shared), 'kind': 'file'}])
    second = config.create_project('b', [str(b)])
    config.register_documents(str(b), second['id'], [{'path': str(shared), 'kind': 'file'}])
    config.remove_document(str(b), second['id'], str(shared))
    assert config.document_retained(shared)
    assert not config.search_visible(shared, [b, shared])
    assert config.search_visible(shared, [a, shared])
    config.remove_project(first['id'])
    assert not config.document_retained(shared)
    assert shared.read_text() == 'shared'
