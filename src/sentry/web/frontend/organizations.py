"""
sentry.web.frontend.generic
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010-2012 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_protect
from sentry.models import Organization, Team
from sentry.web.decorators import login_required
from sentry.web.forms.organizations import NewOrganizationForm
from sentry.web.helpers import render_to_response


@csrf_protect
@login_required
def migrate_to_organizations(request):
    """
    Assist a user in migrating their legacy projects/teams to the organizational
    structure introduced in Sentry 5.3.0.
    """
    form = NewOrganizationForm(request.POST or None)
    if form.is_valid():
        organization = form.save(commit=False)
        organization.owner = request.user
        organization.save()

        messages.add_message(request, messages.SUCCESS, 'Your organization (%s) was added.' % (organization.name,))

        return HttpResponseRedirect(request.path)

    organization_list = Organization.objects.get_for_user(request.user)
    team_list = Team.objects.get_for_user(request.user)

    return render_to_response('sentry/upgrade/migrate_to_organizations.html', {
        'form': form,
        'organization_list': organization_list.values(),
        'team_list': team_list.values(),
    }, request)
