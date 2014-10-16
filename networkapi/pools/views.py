# -*- coding:utf-8 -*-

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from django.db.transaction import commit_on_success
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from networkapi.ip.models import IpEquipamento
from networkapi.equipamento.models import Equipamento
from networkapi.requisicaovips.models import ServerPool, ServerPoolMember, \
    VipPortToPool
from networkapi.pools.serializers import ServerPoolSerializer, HealthcheckSerializer, \
    ServerPoolMemberSerializer, ServerPoolDatatableSerializer, EquipamentoSerializer
from networkapi.healthcheckexpect.models import Healthcheck
from networkapi.ambiente.models import Ambiente
from networkapi.ip.models import Ip, Ipv6
from networkapi.infrastructure.datatable import build_query_to_datatable
from networkapi.api_rest import exceptions as api_exceptions
from networkapi.util import is_valid_list_int_greater_zero_param, \
    is_valid_int_greater_zero_param
from networkapi.log import Log
from networkapi.pools import exceptions
from networkapi.pools.permissions import Read, Write, ScriptRemovePermission, \
    ScriptCreatePermission, ScriptAlterPermission
from networkapi.infrastructure.script_utils import exec_script, ScriptError
from networkapi.settings import POOL_REMOVE, POOL_CREATE, POOL_REAL_CREATE, \
    POOL_REAL_REMOVE, POOL_REAL_ENABLE, POOL_REAL_DISABLE

log = Log(__name__)


@api_view(['POST'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def pool_list(request):
    """
    List all code snippets, or create a new snippet.
    """
    try:

        data = dict()

        environment_id = request.DATA.get("environment_id")
        start_record = request.DATA.get("start_record")
        end_record = request.DATA.get("end_record")
        asorting_cols = request.DATA.get("asorting_cols")
        searchable_columns = request.DATA.get("searchable_columns")
        custom_search = request.DATA.get("custom_search")

        if not is_valid_int_greater_zero_param(environment_id, False):
            raise api_exceptions.ValidationException('Environment id invalid.')

        query_pools = ServerPool.objects.all()

        if environment_id:
            query_pools = query_pools.filter(environment=environment_id)

        server_pools, total = build_query_to_datatable(
            query_pools,
            asorting_cols,
            custom_search,
            searchable_columns,
            start_record,
            end_record
        )

        serializer_pools = ServerPoolDatatableSerializer(
            server_pools,
            many=True
        )

        data["pools"] = serializer_pools.data
        data["total"] = total

        return Response(data)

    except api_exceptions.ValidationException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def list_all_members_by_pool(request, id_server_pool):

    try:

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        data = dict()
        start_record = request.DATA.get("start_record")
        end_record = request.DATA.get("end_record")
        asorting_cols = request.DATA.get("asorting_cols")
        searchable_columns = request.DATA.get("searchable_columns")
        custom_search = request.DATA.get("custom_search")

        query_pools = ServerPoolMember.objects.filter(server_pool=id_server_pool)

        server_pools, total = build_query_to_datatable(
            query_pools,
            asorting_cols,
            custom_search,
            searchable_columns,
            start_record,
            end_record
        )

        serializer_pools = ServerPoolMemberSerializer(server_pools, many=True)

        data["server_pool_members"] = serializer_pools.data
        data["total"] = total

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def get_equipamento_by_ip(request, id_ip):

    try:

        if not is_valid_int_greater_zero_param(id_ip):
            raise exceptions.InvalidIdPoolException()

        data = dict()

        ipequips_obj = IpEquipamento.objects.get(ip=id_ip)
        equip = Equipamento.get_by_pk(pk=ipequips_obj.equipamento_id)

        serializer_equipamento = EquipamentoSerializer(equip, many=False)

        data["equipamento"] = serializer_equipamento.data

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptAlterPermission))
@commit_on_success
def delete(request):
    """
    Delete Pools by list id.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:
            try:
                server_pool = ServerPool.objects.get(id=_id)

                if VipPortToPool.objects.filter(server_pool=_id):
                    raise exceptions.PoolConstraintVipException()

                for server_pool_member in server_pool.serverpoolmember_set.all():

                    ipv4 = server_pool_member.ip
                    ipv6 = server_pool_member.ipv6

                    id_pool = server_pool.id
                    id_ip = ipv4 and ipv4.id or ipv6 and ipv6.id
                    port_ip = server_pool_member.port_real

                    server_pool_member.delete(request.user)

                    command = POOL_REAL_REMOVE % (id_pool, id_ip, port_ip)

                    code, _, _ = exec_script(command)

                    if code != 0:
                        raise exceptions.ScriptDeletePoolException()

                server_pool.delete(request.user)

            except ServerPool.DoesNotExist:
                pass

        return Response(status=status.HTTP_204_NO_CONTENT)

    except exceptions.PoolConstraintVipException, exception:
        log.error(exception)
        raise exception

    except exceptions.ScriptDeletePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptDeletePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, ScriptRemovePermission))
@commit_on_success
def remove(request):
    """
    Remove Pools by list id running script and update to not created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:
            try:

                server_pool = ServerPool.objects.get(id=_id)

                code, _, _ = exec_script(POOL_REMOVE % _id)

                if code != 0:
                    raise exceptions.ScriptRemovePoolException()

                server_pool.pool_created = False
                server_pool.save(request.user)

            except ServerPool.DoesNotExist:
                pass

        return Response()

    except exceptions.ScriptRemovePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptRemovePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptCreatePermission))
@commit_on_success
def create(request):
    """
    Create Pools by list id running script and update to created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:

            server_pool = ServerPool.objects.get(id=_id)

            code, _, _ = exec_script(POOL_CREATE % _id)

            if code != 0:
                raise exceptions.ScriptCreatePoolException()

            server_pool.pool_created = True
            server_pool.save(request.user)

        return Response()

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except exceptions.ScriptCreatePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptCreatePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def healthcheck_list(request):

    try:
        data = dict()

        healthchecks = Healthcheck.objects.all()

        serializer_healthchecks = HealthcheckSerializer(
            healthchecks,
            many=True
        )

        data["healthchecks"] = serializer_healthchecks.data

        return Response(data)

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def get_by_pk(request, id_server_pool):

    try:

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        data = dict()

        server_pool = ServerPool.objects.get(pk=id_server_pool)

        server_pool_members = ServerPoolMember.objects.filter(
            server_pool=id_server_pool
        )

        serializer_server_pool = ServerPoolSerializer(server_pool)

        serializer_server_pool_member = ServerPoolMemberSerializer(
            server_pool_members,
            many=True
        )

        data["server_pool"] = serializer_server_pool.data
        data["server_pool_members"] = serializer_server_pool_member.data

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptAlterPermission))
@commit_on_success
def pool_insert(request):

    try:
        # TODO: ADD VALIDATION
        identifier = request.DATA.get('identifier')
        default_port = request.DATA.get('default_port')
        environment = request.DATA.get('environment')
        balancing = request.DATA.get('balancing')
        healthcheck = request.DATA.get('healthcheck')
        maxcom = request.DATA.get('maxcom')
        ip_list_full = request.DATA.get('ip_list_full')
        priorities = request.DATA.get('priorities')
        ports_reals = request.DATA.get('ports_reals')

        healthcheck_obj = Healthcheck.objects.get(id=healthcheck)
        ambiente_obj = Ambiente.get_by_pk(environment)

        sp = ServerPool(
            identifier=identifier,
            default_port=default_port,
            healthcheck=healthcheck_obj,
            environment=ambiente_obj,
            pool_created=False,
            lb_method=balancing
        )

        sp.save(request.user)

        ip_object = None
        ipv6_object = None

        for i in range(0, len(ip_list_full)):

            if len(ip_list_full[i]['ip']) <= 15:
                ip_object = Ip.get_by_pk(ip_list_full[i]['id'])
            else:
                ipv6_object = Ipv6.get_by_pk(ip_list_full[i]['id'])

            spm = ServerPoolMember(
                server_pool=sp,
                identifier=identifier,
                ip=ip_object,
                ipv6=ipv6_object,
                priority=priorities[i],
                weight=0,
                limit=maxcom,
                port_real=ports_reals[i],
                healthcheck=healthcheck_obj
            )

            spm.save(request.user)

            id_pool = sp.id
            id_ip = ip_object and ip_object.id or ipv6_object and ipv6_object.id
            port_ip = spm.port_real

            command = POOL_REAL_CREATE % (id_pool, id_ip, port_ip)

            code, _, _ = exec_script(command)

            if code != 0:
                raise exceptions.ScriptAddPoolException()

        return Response(status=status.HTTP_201_CREATED)

    except exceptions.ScriptAddPoolException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptAlterPermission))
@commit_on_success
def pool_edit(request):

    try:

        id_server_pool = request.DATA.get('id_server_pool')

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        identifier = request.DATA.get('identifier')
        default_port = request.DATA.get('default_port')
        environment = request.DATA.get('environment')
        balancing = request.DATA.get('balancing')
        healthcheck = request.DATA.get('healthcheck')
        maxcom = request.DATA.get('maxcom')
        ip_list_full = request.DATA.get('ip_list_full')
        priorities = request.DATA.get('priorities')
        ports_reals = request.DATA.get('ports_reals')

        healthcheck_obj = Healthcheck.objects.get(id=healthcheck)
        ambiente_obj = Ambiente.get_by_pk(environment)

        sp = ServerPool(
            id=id_server_pool,
            identifier=identifier,
            default_port=default_port,
            healthcheck=healthcheck_obj,
            environment=ambiente_obj,
            lb_method=balancing
        )

        sp.save(request.user)

        # Excludes all ServerPoolMembers of this ServerPool so we can re-add them
        spm_list = ServerPoolMember.objects.filter(server_pool=sp)

        for spm in spm_list:
            spm.delete(request.user)

        ip_object = None
        ipv6_object = None

        for i in range(0, len(ip_list_full)):
            if len(ip_list_full[i]['ip']) <= 15:
                ip_object = Ip.get_by_pk(ip_list_full[i]['id'])
            else:
                ipv6_object = Ipv6.get_by_pk(ip_list_full[i]['id'])

            spm = ServerPoolMember(
                server_pool=sp,
                identifier=identifier,
                ip=ip_object,
                ipv6=ipv6_object,
                priority=priorities[i],
                weight=0,
                limit=maxcom,
                port_real=ports_reals[i],
                healthcheck=healthcheck_obj
            )

            spm.save(request.user)

        return Response()

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, ScriptAlterPermission))
@commit_on_success
def enable(request):
    """
    Create Pools by list id running script and update to created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:

            server_pool_member = ServerPoolMember.objects.get(id=_id)

            ipv4 = server_pool_member.ip
            ipv6 = server_pool_member.ipv6

            id_pool = server_pool_member.server_pool.id
            id_ip = ipv4 and ipv4.id or ipv6 and ipv6.id
            port_ip = server_pool_member.port_real

            command = POOL_REAL_ENABLE % (id_pool, id_ip, port_ip)

            code, _, _ = exec_script(command)

            if code != 0:
                raise exceptions.ScriptEnablePoolException()

        return Response()

    except ServerPoolMember.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolMemberDoesNotExistException()

    except exceptions.ScriptEnablePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptEnablePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolMemberException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, ScriptAlterPermission))
@commit_on_success
def disable(request):
    """
    Create Pools by list id running script and update to created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:

            server_pool_member = ServerPoolMember.objects.get(id=_id)

            ipv4 = server_pool_member.ip
            ipv6 = server_pool_member.ipv6

            id_pool = server_pool_member.server_pool.id
            id_ip = ipv4 and ipv4.id or ipv6 and ipv6.id
            port_ip = server_pool_member.port_real

            command = POOL_REAL_DISABLE % (id_pool, id_ip, port_ip)

            code, _, _ = exec_script(command)

            if code != 0:
                raise exceptions.ScriptDisablePoolException()

        return Response()

    except ServerPoolMember.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolMemberDoesNotExistException()

    except exceptions.ScriptDisablePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptDisablePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolMemberException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()