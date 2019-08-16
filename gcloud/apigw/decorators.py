# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making 蓝鲸智云PaaS平台社区版 (BlueKing PaaS Community
Edition) available.
Copyright (C) 2017-2019 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

import sys
from functools import wraps

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.utils.decorators import available_attrs

from auth_backend.plugins.shortcuts import verify_or_raise_auth_failed

from gcloud.conf import settings
from gcloud.core.models import Project
from gcloud.apigw.exceptions import UserNotExistError

if not sys.argv[1:2] == ['test'] and settings.USE_BK_OAUTH:
    try:
        from bkoauth.decorators import apigw_required
    except ImportError:
        apigw_required = None
else:
    apigw_required = None

WHITE_APPS = {'bk_fta', 'bk_bcs'}
WHETHER_PREPARE_BIZ = getattr(settings, 'WHETHER_PREPARE_BIZ_IN_API_CALL', True)


def check_white_apps(request):
    if apigw_required is not None:
        app_code = request.jwt.app.app_code
    else:
        app_code = request.META.get('HTTP_BK_APP_CODE')
    if app_code in WHITE_APPS:
        return True
    return False


def inject_user(request):
    if apigw_required is not None:
        username = request.jwt.user.username
    else:
        username = request.META.get('HTTP_BK_USERNAME')
    user_model = get_user_model()
    try:
        user = user_model.objects.get(username=username)
    except user_model.DoesNotExist:
        if request.is_trust:
            user, _ = user_model.objects.get_or_create(username=username)
        else:
            raise UserNotExistError('user[username=%s] does not exist or has not logged in this APP' % username)

    setattr(request, 'user', user)


def mark_request_whether_is_trust(view_func):
    @wraps(view_func, assigned=available_attrs(view_func))
    def wrapper(request, *args, **kwargs):

        setattr(request, 'is_trust', check_white_apps(request))

        try:
            inject_user(request)
        except UserNotExistError as e:
            return JsonResponse({
                'result': False,
                'message': e.message
            })

        return view_func(request, *args, **kwargs)

    return wrapper


def project_existence_check(view_func):
    @wraps(view_func, assigned=available_attrs(view_func))
    def wrapper(request, *args, **kwargs):
        project_id = kwargs['project_id']

        if not Project.objects.filter(id=project_id, is_disable=False).exists():
            return JsonResponse({
                'result': False,
                'message': 'project(%s) does not exist.' % project_id
            })

        return view_func(request, *args, **kwargs)

    return wrapper


def api_verify_perms(auth_resource, actions, get_kwargs):
    def decorator(view_func):
        @wraps(view_func, assigned=available_attrs(view_func))
        def wrapper(request, *args, **kwargs):
            if not getattr(request, 'is_trust', False):
                get_filters = {}
                for kwarg, filter_arg in get_kwargs.items():
                    get_filters[filter_arg] = kwargs.get(kwarg)

                instance = auth_resource.resource_cls.objects.get(**get_filters)

                verify_or_raise_auth_failed(principal_type='user',
                                            principal_id=request.user.username,
                                            resource=auth_resource,
                                            action_ids=[act.id for act in actions],
                                            instance=instance,
                                            status=200)

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
