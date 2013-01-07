# -*- coding: utf-8 -*-

from __future__ import absolute_import

import mock

from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from sentry.constants import MEMBER_USER
from sentry.models import Project, Team, TeamProject
from sentry.web.helpers import get_project_list, get_login_url
from sentry.testutils import TestCase


class GetProjectListTEst(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="admin", email="admin@localhost")
        self.project = Project.objects.get()
        self.project.update(public=True)
        self.project2 = Project.objects.create(name='Test', owner=self.user, public=False)
        self.team1 = TeamProject.objects.get(project=self.project)
        self.team2 = Team.objects.create(name='Test', owner=self.user)
        TeamProject.objects.create(team=self.team2, project=self.project2)

    @mock.patch('sentry.models.Team.objects.get_for_user', mock.Mock(return_value={}))
    def test_includes_public_projects_without_access(self):
        project_list = get_project_list(None)
        assert self.project.id in project_list
        assert len(project_list) == 1

    @mock.patch('sentry.models.Team.objects.get_for_user', mock.Mock(return_value={}))
    def test_does_exclude_public_projects_without_access(self):
        project_list = get_project_list(self.user, MEMBER_USER)
        assert len(project_list) == 0

    @mock.patch('sentry.models.Team.objects.get_for_user')
    def test_does_include_private_projects_without_access(self, get_for_user):
        get_for_user.return_value = {self.project2.team.id: self.project2.team}
        project_list = get_project_list(self.user)
        get_for_user.assert_called_once_with(self.user, None)
        assert self.project.id in project_list
        assert self.project2.id in project_list
        assert len(project_list) == 2

    @mock.patch('sentry.models.Team.objects.get_for_user')
    def test_does_exclude_public_projects_but_include_private_with_access(self, get_for_user):
        get_for_user.return_value = {self.project2.team.id: self.project2.team}
        project_list = get_project_list(self.user, MEMBER_USER)
        get_for_user.assert_called_once_with(self.user, MEMBER_USER)
        assert self.project2.id in project_list
        assert len(project_list) == 1


class GetLoginUrlTest(TestCase):
    def test_as_path(self):
        with self.Settings(LOGIN_URL='/really-a-404'):
            url = get_login_url(True)
            self.assertEquals(url, reverse('sentry-login'))

    def test_as_lazy_url(self):
        with self.Settings(LOGIN_URL=reverse('sentry-fake-login')):
            url = get_login_url(True)
            self.assertEquals(url, reverse('sentry-fake-login'))

    def test_cached(self):
        # should still be cached
        with self.Settings(LOGIN_URL='/really-a-404'):
            url = get_login_url(False)
            self.assertNotEquals(url, '/really-a-404')

    def test_no_value(self):
        with self.Settings(SENTRY_LOGIN_URL=None):
            url = get_login_url(True)
            self.assertEquals(url, reverse('sentry-login'))
