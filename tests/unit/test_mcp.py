"""MCP protocol boundary and engagement calculations."""
import json
from pathlib import Path
import sys

import pytest

from sensai.core.ports import ToolCall
from sensai.mcp_client import Catalogue
from sensai.mcp_server import weekly_engagement
from sensai.tools import ToolRegistry


@pytest.fixture(autouse=True)
def trusted_config(monkeypatch):
    """These tests are about servers; the trust question has its own tests."""
    monkeypatch.setattr(Catalogue, "_trusted", lambda self, digest: True)


def test_real_packaged_server_roundtrip(tmp_path):
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'mcpServers': {'sensai': {
        'command': sys.executable, 'args': ['-m', 'sensai.mcp_server'],
        'env': {'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')}}}}))
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert [d.name for d in catalogue.definitions()] == ['sensai.weekly_engagement']
    registry = ToolRegistry(read=lambda _: 'yes')
    catalogue.register(registry)
    result = registry.execute(ToolCall('sensai.weekly_engagement', {'week_start': '2026-09-21'}))
    assert result.error is None
    assert json.loads(result.output)[0]['engagement_rate'] == 15
    result = registry.execute(ToolCall('sensai.weekly_engagement', {'week_start': 'not-a-date'}))
    assert result.error


def test_zero_reach_partial_demo(monkeypatch):
    monkeypatch.delenv('SENSAI_ENGAGEMENT_CSV', raising=False)
    result = json.loads(weekly_engagement('2026-09-28'))[0]
    assert result['engagement_rate'] == 'n/a'
    assert result['incomplete']
    assert len(result['missing_days']) == 6
    assert 'not unique' in result['basis']


def test_missing_week_and_non_monday(monkeypatch):
    monkeypatch.delenv('SENSAI_ENGAGEMENT_CSV', raising=False)
    with pytest.raises(ValueError):
        weekly_engagement('2026-09-22')
    with pytest.raises(ValueError, match='No engagement'):
        weekly_engagement('2026-10-12')


def test_channels_and_duplicate_rows(tmp_path, monkeypatch):
    path = tmp_path / 'data.csv'
    header = 'date,channel,accounts_reached,accounts_engaged\n'
    rows = '2026-09-21,Instagram,10,2\n2026-09-21,TikTok,20,5\n'
    path.write_text(header + rows)
    monkeypatch.setenv('SENSAI_ENGAGEMENT_CSV', str(path))
    values = json.loads(weekly_engagement('2026-09-21'))
    assert [r['engagement_rate'] for r in values] == [20, 25]
    path.write_text(header + rows + '2026-09-21,Instagram,10,2\n')
    with pytest.raises(ValueError, match='duplicate'):
        weekly_engagement('2026-09-21')
