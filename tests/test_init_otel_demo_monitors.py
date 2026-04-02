"""Unit tests for the OTel Demo monitors init script."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'opentelemetry-demo'))
import importlib
init_mod = importlib.import_module('init-otel-demo-monitors')

get_existing_monitor = init_mod.get_existing_monitor
create_monitor = init_mod.create_monitor


class TestGetExistingMonitor:
    """Tests for get_existing_monitor()"""

    @patch('requests.post')
    def test_returns_id_when_found(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'hits': {
                    'hits': [{'_id': 'monitor-abc-123'}]
                }
            }
        )
        result = get_existing_monitor('Test Monitor')
        assert result == 'monitor-abc-123'

    @patch('requests.post')
    def test_returns_none_when_not_found(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'hits': {'hits': []}}
        )
        result = get_existing_monitor('Missing Monitor')
        assert result is None

    @patch('requests.post')
    def test_returns_none_on_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError()
        result = get_existing_monitor('Any Monitor')
        assert result is None

    @patch('requests.post')
    def test_searches_by_monitor_name_keyword(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'hits': {'hits': []}}
        )
        get_existing_monitor('My Monitor')
        call_json = mock_post.call_args[1]['json']
        assert call_json['query']['term']['monitor.name.keyword'] == 'My Monitor'


class TestCreateMonitor:
    """Tests for create_monitor()"""

    @patch.object(init_mod, 'get_existing_monitor', return_value=None)
    @patch('requests.post')
    def test_creates_new_monitor(self, mock_post, mock_existing):
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {'_id': 'new-monitor-123'}
        )
        result = create_monitor({'name': 'New Monitor', 'type': 'monitor'})
        assert result == 'new-monitor-123'

    @patch.object(init_mod, 'get_existing_monitor', return_value='existing-id')
    def test_skips_existing_monitor(self, mock_existing):
        result = create_monitor({'name': 'Existing Monitor'})
        assert result == 'existing-id'

    @patch.object(init_mod, 'get_existing_monitor', return_value=None)
    @patch('requests.post')
    def test_returns_none_on_failure(self, mock_post, mock_existing):
        mock_post.return_value = MagicMock(
            status_code=400,
            text='Bad Request'
        )
        result = create_monitor({'name': 'Bad Monitor'})
        assert result is None

    @patch.object(init_mod, 'get_existing_monitor', return_value=None)
    @patch('requests.post')
    def test_returns_none_on_network_error(self, mock_post, mock_existing):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError()
        result = create_monitor({'name': 'Unreachable Monitor'})
        assert result is None

    @patch.object(init_mod, 'get_existing_monitor', return_value=None)
    @patch('requests.post')
    def test_accepts_200_status(self, mock_post, mock_existing):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'_id': 'id-200'}
        )
        result = create_monitor({'name': 'Monitor200'})
        assert result == 'id-200'


class TestCreateOtelDemoMonitors:
    """Tests for create_otel_demo_monitors() — validates the monitor definitions."""

    @patch.object(init_mod, 'create_monitor')
    def test_creates_expected_number_of_monitors(self, mock_create):
        mock_create.return_value = 'fake-id'
        init_mod.create_otel_demo_monitors()
        # The script creates 5 monitors for the demo
        assert mock_create.call_count == 5

    @patch.object(init_mod, 'create_monitor')
    def test_all_monitors_have_required_fields(self, mock_create):
        mock_create.return_value = 'fake-id'
        init_mod.create_otel_demo_monitors()

        for call in mock_create.call_args_list:
            payload = call[0][0]
            assert 'name' in payload, "Monitor missing 'name'"
            assert 'type' in payload, f"Monitor {payload['name']} missing 'type'"
            assert 'monitor_type' in payload, f"Monitor {payload['name']} missing 'monitor_type'"
            assert 'inputs' in payload, f"Monitor {payload['name']} missing 'inputs'"
            assert 'triggers' in payload, f"Monitor {payload['name']} missing 'triggers'"
            assert payload['type'] == 'monitor'
            assert payload['enabled'] is True

    @patch.object(init_mod, 'create_monitor')
    def test_monitor_names_are_prefixed(self, mock_create):
        mock_create.return_value = 'fake-id'
        init_mod.create_otel_demo_monitors()

        names = [call[0][0]['name'] for call in mock_create.call_args_list]
        for name in names:
            assert name.startswith('OTel Demo'), f"Monitor name '{name}' should start with 'OTel Demo'"
