import logging
import pytest
import unittest

from tests.cook import reasons, util

@pytest.mark.multi_user
@unittest.skipUnless(util.multi_user_tests_enabled(), 'Requires using multi-user coniguration (e.g., BasicAuth) for Cook Scheduler')
@pytest.mark.timeout(util.DEFAULT_TEST_TIMEOUT_SECS)  # individual test timeout
class MultiUserCookTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cook_url = util.retrieve_cook_url()
        util.init_cook_session(cls.cook_url)

    def setUp(self):
        self.cook_url = type(self).cook_url
        self.logger = logging.getLogger(__name__)
        self.user_factory = util.UserFactory(self)

    def test_job_delete_permission(self):
        user1, user2 = self.user_factory.new_users(2)
        with user1:
            job_uuid, resp = util.submit_job(self.cook_url, command='sleep 30')
        try:
            self.assertEqual(resp.status_code, 201, resp.text)
            with user2:
                util.kill_jobs(self.cook_url, [job_uuid], expected_status_code=403)
            with user1:
                util.kill_jobs(self.cook_url, [job_uuid])
            job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
            self.assertEqual('failed', job['state'])
        finally:
            util.kill_jobs(self.cook_url, [job_uuid])

    def test_group_delete_permission(self):
        user1, user2 = self.user_factory.new_users(2)
        with user1:
            group_spec = util.minimal_group()
            group_uuid = group_spec['uuid']
            job_uuid, resp = util.submit_job(self.cook_url, command='sleep 30', group=group_uuid)
        try:
            self.assertEqual(resp.status_code, 201, resp.text)
            with user2:
                util.kill_groups(self.cook_url, [group_uuid], expected_status_code=403)
            with user1:
                util.kill_groups(self.cook_url, [group_uuid])
            job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
            self.assertEqual('failed', job['state'])
        finally:
            util.kill_jobs(self.cook_url, [job_uuid])

    def test_multi_user_usage(self):
        users = self.user_factory.new_users(6)
        job_resources = {'cpus': 0.1, 'mem': 123}
        all_job_uuids = []
        try:
            # Start jobs for several users
            for i, user in enumerate(users):
                with user:
                    for j in range(i):
                        job_uuid, resp = util.submit_job(self.cook_url, command='sleep 240', **job_resources)
                        self.assertEqual(resp.status_code, 201, resp.content)
                        all_job_uuids.append(job_uuid)
            # Don't query until the jobs are all running
            util.wait_for_jobs(self.cook_url, all_job_uuids, 'running')
            # Check the usage for each of our users
            for i, user in enumerate(users):
                with user:
                    # Get the current usage
                    resp = util.user_current_usage(self.cook_url, user=user.name)
                    self.assertEqual(resp.status_code, 200, resp.content)
                    usage_data = resp.json()
                    # Check that the response structure looks as expected
                    self.assertEqual(list(usage_data.keys()), ['total_usage'], usage_data)
                    self.assertEqual(len(usage_data['total_usage']), 4, usage_data)
                    # Check that each user's usage is as expected
                    self.assertEqual(usage_data['total_usage']['mem'], job_resources['mem'] * i, usage_data)
                    self.assertEqual(usage_data['total_usage']['cpus'], job_resources['cpus'] * i, usage_data)
                    self.assertEqual(usage_data['total_usage']['gpus'], 0, usage_data)
                    self.assertEqual(usage_data['total_usage']['jobs'], i, usage_data)
        finally:
            # Terminate all of the jobs
            if all_job_uuids:
                util.kill_jobs(self.cook_url, all_job_uuids)
