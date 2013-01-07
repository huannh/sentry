# -*- coding: utf-8 -*-

from __future__ import absolute_import

import datetime
import mock

from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.utils import timezone

from raven import Client
from sentry.models import Group, Event, Project, Team, TeamProject
from sentry.testutils import TestCase


class RavenIntegrationTest(TestCase):
    """
    This mocks the test server and specifically tests behavior that would
    happen between Raven <--> Sentry over HTTP communication.
    """
    def setUp(self):
        self.user = User.objects.create(username='coreapi')
        self.project = Project.objects.create(owner=self.user, name='Foo')
        self.team = Team.objects.create(owner=self.user, name='Foo')
        TeamProject.objects.create(team=self.team, project=self.project)
        self.pm = self.team.member_set.get(user=self.user)
        self.pk = self.project.key_set.create(project=self.project, user=self.user)

    def sendRemote(self, url, data, headers={}):
        # TODO: make this install a temporary handler which raises an assertion error
        import logging
        sentry_errors = logging.getLogger('sentry.errors')
        sentry_errors.addHandler(logging.StreamHandler())
        sentry_errors.setLevel(logging.DEBUG)

        content_type = headers.pop('Content-Type', None)
        headers = dict(('HTTP_' + k.replace('-', '_').upper(), v) for k, v in headers.iteritems())
        resp = self.client.post(reverse('sentry-api-store', args=[self.pk.project_id]),
            data=data,
            content_type=content_type,
            **headers)
        self.assertEquals(resp.status_code, 200, resp.content)

    @mock.patch('raven.base.Client.send_remote')
    def test_basic(self, send_remote):
        send_remote.side_effect = self.sendRemote
        client = Client(
            project=self.pk.project_id,
            servers=['http://localhost:8000%s' % reverse('sentry-api-store', args=[self.pk.project_id])],
            public_key=self.pk.public_key,
            secret_key=self.pk.secret_key,
        )
        client.capture('Message', message='foo')

        send_remote.assert_called_once()
        self.assertEquals(Group.objects.count(), 1)
        group = Group.objects.get()
        self.assertEquals(group.event_set.count(), 1)
        instance = group.event_set.get()
        self.assertEquals(instance.message, 'foo')
