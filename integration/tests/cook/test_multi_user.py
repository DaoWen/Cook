import itertools
import logging
import unittest

from tests.cook import cli, util

@unittest.skipUnless(util.multi_user_tests_enabled(),
                     "Requires using multi-user coniguration (e.g., BasicAuth) for Cook Scheduler")
class MultiUserCookTest(unittest.TestCase):
    _multiprocess_can_split_ = True

    @classmethod
    def setUpClass(cls):
        cls.cook_url = util.retrieve_cook_url()
        util.init_cook_session(cls.cook_url)

    def setUp(self):
        self.cook_url = type(self).cook_url
        self.logger = logging.getLogger(__name__)
        self.base_name = self.id().replace('.', '-').lower()
        self.base_name = self.id()[self.id().rindex('.test_')+6:]
        self.__user_generator = ( f'{self.base_name}_{i}' for i in range(1000) )

    def make_user(self):
        return util.User(next(self.__user_generator))

    def make_users(self, count):
        return map(util.User, itertools.islice(self.__user_generator, 0, count))

    def test_job_delete_permission(self):
        user1, user2 = self.make_users(2)
        with user1:
            job_uuid, resp = util.submit_job(self.cook_url, command='sleep 10')
        try:
            self.logger.debug(f"User 1: {user1.name}")
            self.assertEqual(resp.status_code, 201, resp.text)
            with user2:
                util.kill_jobs(self.cook_url, [job_uuid], expected_status_code=403)
            with user1:
                util.kill_jobs(self.cook_url, [job_uuid])
        finally:
            util.kill_jobs(self.cook_url, [job_uuid])
