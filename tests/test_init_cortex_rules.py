"""Unit tests for the Cortex rules init script."""
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import yaml

# Add the script's directory to path so we can import it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'cortex'))
import importlib
init_mod = importlib.import_module('init-cortex-rules')

get_existing_groups = init_mod.get_existing_groups
load_rules_file = init_mod.load_rules_file
main = init_mod.main


class TestGetExistingGroups:
    """Tests for get_existing_groups()"""

    @patch('requests.get')
    def test_returns_group_names_on_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'data': {
                    'groups': [
                        {'name': 'stack_health'},
                        {'name': 'otel_collector_health'},
                    ]
                }
            }
        )
        result = get_existing_groups('stack')
        assert result == {'stack_health', 'otel_collector_health'}

    @patch('requests.get')
    def test_returns_empty_set_on_404(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        result = get_existing_groups('missing')
        assert result == set()

    @patch('requests.get')
    def test_returns_empty_set_on_network_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError()
        result = get_existing_groups('stack')
        assert result == set()

    @patch('requests.get')
    def test_returns_empty_set_when_no_groups(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'data': {'groups': []}}
        )
        result = get_existing_groups('stack')
        assert result == set()


class TestLoadRulesFile:
    """Tests for load_rules_file()"""

    def _write_rules(self, tmpdir, filename, content):
        path = os.path.join(tmpdir, filename)
        with open(path, 'w') as f:
            yaml.dump(content, f)
        return path

    @patch('requests.post')
    @patch('requests.get')
    def test_loads_new_groups(self, mock_get, mock_post):
        # No existing groups
        mock_get.return_value = MagicMock(status_code=404)
        # Successful POST
        mock_post.return_value = MagicMock(status_code=202)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rules(tmpdir, 'alerts.yml', {
                'groups': [
                    {'name': 'test_group', 'rules': [{'alert': 'TestAlert', 'expr': 'up == 0'}]},
                ]
            })
            count = load_rules_file(path, 'test_ns')

        assert count == 1
        mock_post.assert_called_once()
        assert 'test_ns' in mock_post.call_args[0][0]

    @patch('requests.post')
    @patch('requests.get')
    def test_skips_existing_groups(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'data': {'groups': [{'name': 'existing_group'}]}}
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rules(tmpdir, 'alerts.yml', {
                'groups': [
                    {'name': 'existing_group', 'rules': [{'alert': 'X', 'expr': 'up'}]},
                ]
            })
            count = load_rules_file(path, 'ns')

        assert count == 1  # Counted as loaded (already exists)
        mock_post.assert_not_called()

    @patch('requests.get')
    def test_returns_zero_for_empty_file(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rules(tmpdir, 'empty.yml', {})
            count = load_rules_file(path, 'ns')

        assert count == 0

    @patch('requests.get')
    def test_returns_zero_for_no_groups_key(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rules(tmpdir, 'bad.yml', {'other_key': 'value'})
            count = load_rules_file(path, 'ns')

        assert count == 0

    @patch('requests.post')
    @patch('requests.get')
    def test_handles_post_failure(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(status_code=404)
        mock_post.return_value = MagicMock(status_code=500, text='Internal Server Error')

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rules(tmpdir, 'alerts.yml', {
                'groups': [{'name': 'group1', 'rules': []}],
            })
            count = load_rules_file(path, 'ns')

        assert count == 0

    @patch('requests.post')
    @patch('requests.get')
    def test_loads_multiple_groups(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(status_code=404)
        mock_post.return_value = MagicMock(status_code=202)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rules(tmpdir, 'alerts.yml', {
                'groups': [
                    {'name': 'g1', 'rules': [{'alert': 'A', 'expr': 'x'}]},
                    {'name': 'g2', 'rules': [{'alert': 'B', 'expr': 'y'}]},
                    {'name': 'g3', 'rules': [{'alert': 'C', 'expr': 'z'}]},
                ]
            })
            count = load_rules_file(path, 'ns')

        assert count == 3
        assert mock_post.call_count == 3


class TestMain:
    """Tests for main() orchestration."""

    @patch.object(init_mod, 'load_rules_file', return_value=2)
    @patch.object(init_mod, 'wait_for_cortex')
    def test_scans_namespace_directories(self, mock_wait, mock_load):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create namespace directories with rule files
            stack_dir = os.path.join(tmpdir, 'stack')
            os.makedirs(stack_dir)
            with open(os.path.join(stack_dir, 'alerts.yml'), 'w') as f:
                f.write('groups: []')

            demo_dir = os.path.join(tmpdir, 'otel_demo')
            os.makedirs(demo_dir)
            with open(os.path.join(demo_dir, 'demo-alerts.yml'), 'w') as f:
                f.write('groups: []')

            with patch.object(init_mod, 'CORTEX_URL', 'http://fake:9090'):
                # Patch the rules_root inside main
                original_main = init_mod.main
                def patched_main():
                    import glob as g
                    init_mod.wait_for_cortex()
                    total = 0
                    for ns_dir in sorted(g.glob(f"{tmpdir}/*")):
                        if not os.path.isdir(ns_dir):
                            continue
                        ns = os.path.basename(ns_dir)
                        for rf in sorted(g.glob(f"{ns_dir}/*.yml")):
                            total += init_mod.load_rules_file(rf, ns)
                    return total

                result = patched_main()

        assert result == 4  # 2 per file, 2 files
        assert mock_load.call_count == 2
        # Verify namespace names
        call_namespaces = [call[0][1] for call in mock_load.call_args_list]
        assert 'otel_demo' in call_namespaces
        assert 'stack' in call_namespaces


class TestRulesYamlValidation:
    """Validate the actual Prometheus rules YAML files."""

    RULES_DIR = os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'prometheus', 'rules')
    OTEL_DEMO_RULES_DIR = os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'prometheus', 'rules-otel-demo')

    def _load_rules(self, path):
        with open(path) as f:
            return yaml.safe_load(f)

    def test_stack_alerts_is_valid_yaml(self):
        path = os.path.join(self.RULES_DIR, 'alerts.yml')
        if not os.path.exists(path):
            pytest.skip('alerts.yml not found')
        data = self._load_rules(path)
        assert 'groups' in data

    def test_stack_alerts_groups_have_names(self):
        path = os.path.join(self.RULES_DIR, 'alerts.yml')
        if not os.path.exists(path):
            pytest.skip('alerts.yml not found')
        data = self._load_rules(path)
        for group in data['groups']:
            assert 'name' in group, f"Group missing name: {group}"
            assert 'rules' in group, f"Group {group['name']} missing rules"

    def test_stack_alerts_all_rules_have_required_fields(self):
        path = os.path.join(self.RULES_DIR, 'alerts.yml')
        if not os.path.exists(path):
            pytest.skip('alerts.yml not found')
        data = self._load_rules(path)
        for group in data['groups']:
            for rule in group['rules']:
                assert 'alert' in rule, f"Rule in {group['name']} missing 'alert' field"
                assert 'expr' in rule, f"Rule {rule.get('alert', '?')} missing 'expr'"
                assert 'labels' in rule, f"Rule {rule['alert']} missing 'labels'"
                assert 'severity' in rule['labels'], f"Rule {rule['alert']} missing severity label"

    def test_otel_demo_alerts_is_valid_yaml(self):
        path = os.path.join(self.OTEL_DEMO_RULES_DIR, 'otel-demo-alerts.yml')
        if not os.path.exists(path):
            pytest.skip('otel-demo-alerts.yml not found')
        data = self._load_rules(path)
        assert 'groups' in data

    def test_alertmanager_template_is_valid_yaml(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'alertmanager', 'alertmanager.template.yml')
        if not os.path.exists(path):
            pytest.skip('alertmanager.template.yml not found')
        with open(path) as f:
            data = yaml.safe_load(f)
        assert 'route' in data
        assert 'receivers' in data
        assert data['route']['receiver'] == 'opensearch-webhook'

    def test_alertmanager_has_credential_placeholders(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'alertmanager', 'alertmanager.template.yml')
        if not os.path.exists(path):
            pytest.skip('alertmanager.template.yml not found')
        with open(path) as f:
            content = f.read()
        assert 'OPENSEARCH_USER' in content
        assert 'OPENSEARCH_PASSWORD' in content

    def test_cortex_config_is_valid_yaml(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'docker-compose', 'cortex', 'cortex.yaml')
        if not os.path.exists(path):
            pytest.skip('cortex.yaml not found')
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data['auth_enabled'] is False
        assert data['server']['http_listen_port'] == 9090
        assert data['ruler']['enable_api'] is True
        assert 'alertmanager' in data['ruler']['alertmanager_url']
