"""The scripted model must consume real catalogs and remediation results."""
import unittest
from pipeline_dependencies import incident_reply
from qualification_incident import incident_workflow


class IncidentFixtureTest(unittest.TestCase):
    def test_agent_catalog_is_a_ceiling(self):
        request = {'tools': [{'function': {'name': 'incidents_read'}}]}
        answer = incident_reply(request, [('incidents_remediate', {}), ('incidents_read', {})])
        self.assertEqual('incidents_read', answer['tool_calls'][0]['function']['name'])

    def test_verification_requires_the_real_result(self):
        request = {'tools': [{'function': {'name': 'incidents_verify'}}]}
        with self.assertRaisesRegex(ValueError, 'actual remediation'):
            incident_reply(request, [('incidents_verify', {'remediationId': 'REM-fake'})])
        request['messages'] = [{'role': 'tool', 'content': '{"remediationId":"REM-deadbeef"}'}]
        answer = incident_reply(request, [('incidents_verify', {})])
        self.assertEqual({'remediationId': 'REM-deadbeef'}, answer['tool_calls'][0]['function']['arguments'])

    def test_already_selected_operation_is_not_regenerated(self):
        request = {'tools': [{'function': {'name': 'incidents_remediate'}}], 'messages': [
            {'tool_calls': [{'function': {'name': 'incidents_remediate'}}]}]}
        self.assertNotIn('tool_calls', incident_reply(request, [('incidents_remediate', {})]))

    def test_new_workflow_has_explicit_agent_ceiling_and_no_legacy_tool_nodes(self):
        graph = incident_workflow()
        self.assertNotIn('tools', graph)
        self.assertEqual(['START', 'AGENT', 'AGENT', 'AGENT', 'AGENT', 'END'], [node['type'] for node in graph['nodes']])
        self.assertEqual(0, graph['nodes'][-2]['configuration']['maxToolRounds'])
        self.assertEqual(5, len(graph['edges']))


if __name__ == '__main__':
    unittest.main()
