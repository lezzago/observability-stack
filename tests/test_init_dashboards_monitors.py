"""Unit tests for the alerting monitor functions in init-opensearch-dashboards.py."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'opensearch-dashboards', 'init'))
import importlib
init_mod = importlib.import_module('init-opensearch-dashboards')

get_existing_monitor = init_mod.get_existing_monitor
create_monitor = init_mod.create_monitor
create_alerting_monitors = init_mod.create_alerting_monitors


class TestGetExistingMonitor:
    """Tests for get_existing_monitor() in the dashboards init script."""

    @patch('requests.post')
    def test_returns_id_when_found(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'hits': {'hits': [{'_id': 'abc-123'}]}
            }
        )
        result = get_existing_monitor('Cluster Health - Red')
        assert result == 'abc-123'

    @patch('requests.post')
    def test_returns_none_when_empty(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'hits': {'hits': []}}
        )
        assert get_existing_monitor('Missing') is None

    @patch('requests.post')
    def test_returns_none_on_exception(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()
        assert get_existing_monitor('Timeout Monitor') is None


class TestCreateMonitor:
    """Tests for create_monitor() in the dashboards init script."""

    @patch.object(init_mod, 'get_existing_monitor', return_value=None)
    @patch('requests.post')
    def test_creates_monitor_on_201(self, mock_post, mock_existing):
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {'_id': 'new-id'}
        )
        result = create_monitor({'name': 'Test'})
        assert result == 'new-id'

    @patch.object(init_mod, 'get_existing_monitor', return_value='existing-id')
    def test_returns_existing_id_when_already_exists(self, mock_existing):
        result = create_monitor({'name': 'Already Exists'})
        assert result == 'existing-id'

    @patch.object(init_mod, 'get_existing_monitor', return_value=None)
    @patch('requests.post')
    def test_returns_none_on_error_status(self, mock_post, mock_existing):
        mock_post.return_value = MagicMock(status_code=500, text='Server Error')
        assert create_monitor({'name': 'Fail'}) is None


class TestCreateAlertingMonitors:
    """Tests for create_alerting_monitors() — validates pre-canned monitors."""

    @patch.object(init_mod, 'create_monitor')
    def test_creates_six_monitors(self, mock_create):
        mock_create.return_value = 'fake-id'
        result = create_alerting_monitors()
        assert mock_create.call_count == 6
        assert result == 6

    @patch.object(init_mod, 'create_monitor')
    def test_monitor_names(self, mock_create):
        mock_create.return_value = 'fake-id'
        create_alerting_monitors()

        names = [call[0][0]['name'] for call in mock_create.call_args_list]
        expected = [
            'OpenSearch Cluster Health - Red',
            'OpenSearch Cluster Health - Yellow',
            'Log Error Spike',
            'High Trace Error Rate',
            'Pipeline Health - No Logs Received',
            'Pipeline Health - No Traces Received',
        ]
        assert names == expected

    @patch.object(init_mod, 'create_monitor')
    def test_all_monitors_have_required_structure(self, mock_create):
        mock_create.return_value = 'fake-id'
        create_alerting_monitors()

        for call in mock_create.call_args_list:
            payload = call[0][0]
            assert payload['type'] == 'monitor'
            assert payload['monitor_type'] == 'query_level_monitor'
            assert payload['enabled'] is True
            assert 'schedule' in payload
            assert 'inputs' in payload
            assert 'triggers' in payload
            assert len(payload['triggers']) > 0

    @patch.object(init_mod, 'create_monitor')
    def test_cluster_health_monitors_use_cluster_api(self, mock_create):
        mock_create.return_value = 'fake-id'
        create_alerting_monitors()

        cluster_monitors = [
            call[0][0] for call in mock_create.call_args_list
            if 'Cluster Health' in call[0][0]['name']
        ]
        assert len(cluster_monitors) == 2
        for m in cluster_monitors:
            assert m['inputs'][0]['uri']['api_type'] == 'CLUSTER_HEALTH'

    @patch.object(init_mod, 'create_monitor')
    def test_data_monitors_use_search_inputs(self, mock_create):
        mock_create.return_value = 'fake-id'
        create_alerting_monitors()

        search_monitors = [
            call[0][0] for call in mock_create.call_args_list
            if 'Cluster Health' not in call[0][0]['name']
        ]
        for m in search_monitors:
            assert 'search' in m['inputs'][0], f"Monitor {m['name']} should use search input"

    @patch.object(init_mod, 'create_monitor')
    def test_counts_partial_failures(self, mock_create):
        # Simulate 3 successes and 3 failures
        mock_create.side_effect = ['id1', 'id2', 'id3', None, None, None]
        result = create_alerting_monitors()
        assert result == 3


class TestPrometheusDataource:
    """Test that the Prometheus datasource includes alertmanager.uri."""

    def test_init_script_has_alertmanager_in_datasource_properties(self):
        """Verify the init script sets alertmanager.uri in the Prometheus datasource."""
        script_path = os.path.join(
            os.path.dirname(__file__), '..', 'docker-compose',
            'opensearch-dashboards', 'init', 'init-opensearch-dashboards.py'
        )
        with open(script_path) as f:
            content = f.read()
        assert 'alertmanager.uri' in content
        assert 'ALERTMANAGER_HOST' in content
        assert 'ALERTMANAGER_PORT' in content
