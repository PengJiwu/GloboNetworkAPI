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

from __future__ import with_statement
from networkapi.admin_permission import AdminPermission

from networkapi.auth import has_perm

from networkapi.equipamento.models import EquipamentoNotFoundError, EquipamentoError,\
    Equipamento

from networkapi.grupo.models import GrupoError

from networkapi.filterequiptype.models import FilterEquipType

from networkapi.infrastructure.xml_utils import loads, XMLError, dumps_networkapi

from networkapi.ip.models import NetworkIPv6, NetworkIPv6NotFoundError, Ipv6, IpNotAvailableError, IpError, NetworkIPv6Error, IpEquipmentAlreadyAssociation, Ipv6Equipament, IpEquipmentNotFoundError, IpNotFoundError, IpRangeAlreadyAssociation

import logging

from networkapi.rest import RestResource, UserNotAuthorizedError

from networkapi.exception import InvalidValueError

from networkapi.util import is_valid_int_greater_zero_param,\
    destroy_cache_function
from networkapi.vlan.models import VlanNumberNotAvailableError
from networkapi.distributedlock import distributedlock, LOCK_NETWORK_IPV6

from networkapi.equipamento.models import EquipamentoAmbiente, EquipamentoAmbienteDuplicatedError
from networkapi.infrastructure.ipaddr import AddressValueError


class Ipv6AssocEquipResource(RestResource):

    log = logging.getLogger('Ipv6AssocEquipResource')

    def handle_post(self, request, user, *args, **kwargs):
        '''Handles POST requests to associate and IPv6 to an equipment.

        URL: ipv6/assoc/
        '''

        self.log.info('Associate Ipv6 to an Equipment')

        try:
            # Load XML data
            xml_map, attrs_map = loads(request.raw_post_data)

            # XML data format
            networkapi_map = xml_map.get('networkapi')
            if networkapi_map is None:
                msg = u'There is no value to the networkapi tag of XML request.'
                self.log.error(msg)
                return self.response_error(3, msg)

            ip_map = networkapi_map.get('ip_map')
            if ip_map is None:
                msg = u'There is no value to the ip tag of XML request.'
                self.log.error(msg)
                return self.response_error(3, msg)

            # Get XML data
            ip_id = ip_map.get('id_ip')
            equip_id = ip_map.get('id_equip')
            network_ipv6_id = ip_map.get('id_net')

            # Valid ip_id
            if not is_valid_int_greater_zero_param(ip_id):
                self.log.error(
                    u'Parameter ip_id is invalid. Value: %s.', ip_id)
                raise InvalidValueError(None, 'ip_id', ip_id)

            # Valid equip_id
            if not is_valid_int_greater_zero_param(equip_id):
                self.log.error(
                    u'Parameter equip_id is invalid. Value: %s.', equip_id)
                raise InvalidValueError(None, 'equip_id', equip_id)

            # Valid network_ipv6_id
            if not is_valid_int_greater_zero_param(network_ipv6_id):
                self.log.error(
                    u'Parameter network_ipv6_id is invalid. Value: %s.', network_ipv6_id)
                raise InvalidValueError(
                    None, 'network_ipv6_id', network_ipv6_id)

            # User permission
            if not has_perm(user,
                            AdminPermission.IPS,
                            AdminPermission.WRITE_OPERATION,
                            None,
                            equip_id,
                            AdminPermission.EQUIP_WRITE_OPERATION):
                raise UserNotAuthorizedError(
                    None, u'User does not have permission to perform the operation.')

            # Business Rules

            # Get net
            net = NetworkIPv6.get_by_pk(network_ipv6_id)

            with distributedlock(LOCK_NETWORK_IPV6 % network_ipv6_id):

                # Get ip
                ip = Ipv6.get_by_pk(ip_id)
                # Get equipment
                equip = Equipamento.get_by_pk(equip_id)

                listaVlansDoEquip = []

                for ipequip in equip.ipequipamento_set.all():
                    vlan = ipequip.ip.networkipv4.vlan
                    if vlan not in listaVlansDoEquip:
                        listaVlansDoEquip.append(vlan)

                for ipequip in equip.ipv6equipament_set.all():
                    vlan = ipequip.ip.networkipv6.vlan
                    if vlan not in listaVlansDoEquip:
                        listaVlansDoEquip.append(vlan)

                vlan_atual = net.vlan
                vlan_aux = None
                ambiente_aux = None

                for vlan in listaVlansDoEquip:
                    if vlan.num_vlan == vlan_atual.num_vlan:
                        if vlan.id != vlan_atual.id:

                            # Filter case 3 - Vlans with same number cannot
                            # share equipments ##

                            flag_vlan_error = False
                            # Filter testing
                            if vlan.ambiente.filter is None or vlan_atual.ambiente.filter is None:
                                flag_vlan_error = True
                            else:
                                # Test both environment's filters
                                tp_equip_list_one = list()
                                for fet in FilterEquipType.objects.filter(filter=vlan_atual.ambiente.filter.id):
                                    tp_equip_list_one.append(fet.equiptype)

                                tp_equip_list_two = list()
                                for fet in FilterEquipType.objects.filter(filter=vlan.ambiente.filter.id):
                                    tp_equip_list_two.append(fet.equiptype)

                                if equip.tipo_equipamento not in tp_equip_list_one or equip.tipo_equipamento not in tp_equip_list_two:
                                    flag_vlan_error = True

                            ## Filter case 3 - end ##

                            if flag_vlan_error:
                                ambiente_aux = vlan.ambiente
                                vlan_aux = vlan
                                nome_ambiente = "%s - %s - %s" % (
                                    vlan.ambiente.divisao_dc.nome, vlan.ambiente.ambiente_logico.nome, vlan.ambiente.grupo_l3.nome)
                                raise VlanNumberNotAvailableError(None,
                                                                  '''O ip informado não pode ser cadastrado, pois o equipamento %s, faz parte do ambiente %s (id %s), 
                                                                    que possui a Vlan de id %s, que também possui o número %s, e não é permitido que vlans que compartilhem o mesmo ambiente 
                                                                    por meio de equipamentos, possuam o mesmo número, edite o número de uma das Vlans ou adicione um filtro no ambiente para efetuar o cadastro desse IP no Equipamento Informado.
                                                                    ''' % (equip.nome, nome_ambiente, ambiente_aux.id, vlan_aux.id, vlan_atual.num_vlan))

                # Persist
                try:

                    try:
                        ipEquip = Ipv6Equipament()
                        ipEquip.get_by_ip_equipment(ip.id, equip_id)

                        raise IpEquipmentAlreadyAssociation(None, u'Ipv6 %s:%s:%s:%s:%s:%s:%s:%s already has association with Equipament %s.' % (
                            ip.block1, ip.block2, ip.block3, ip.block4, ip.block5, ip.block6, ip.block7, ip.block8, equip_id))
                    except IpEquipmentNotFoundError, e:
                        pass

                    equipment = Equipamento().get_by_pk(equip_id)
                    ip_equipment = Ipv6Equipament()
                    ip_equipment.ip = ip

                    ip_equipment.equipamento = equipment

                    # Filter case 2 - Adding new IpEquip for a equip that
                    # already have ip in other network with the same range ##

                    # Get all Ipv6Equipament related to this equipment
                    ip_equips = Ipv6Equipament.objects.filter(
                        equipamento=equip_id)

                    for ip_test in [ip_equip.ip for ip_equip in ip_equips]:
                        if ip_test.networkipv6.block1 == ip.networkipv6.block1 and \
                                ip_test.networkipv6.block2 == ip.networkipv6.block2 and \
                                ip_test.networkipv6.block3 == ip.networkipv6.block3 and \
                                ip_test.networkipv6.block4 == ip.networkipv6.block4 and \
                                ip_test.networkipv6.block5 == ip.networkipv6.block5 and \
                                ip_test.networkipv6.block6 == ip.networkipv6.block6 and \
                                ip_test.networkipv6.block7 == ip.networkipv6.block7 and \
                                ip_test.networkipv6.block8 == ip.networkipv6.block8 and \
                                ip_test.networkipv6.block == ip.networkipv6.block and \
                                ip_test.networkipv6 != ip.networkipv6:

                            # Filter testing
                            if ip_test.networkipv6.vlan.ambiente.filter is None or ip.networkipv6.vlan.ambiente.filter is None:
                                raise IpRangeAlreadyAssociation(
                                    None, u'Equipment is already associated with another ip with the same ip range.')
                            else:
                                # Test both environment's filters
                                tp_equip_list_one = list()
                                for fet in FilterEquipType.objects.filter(filter=ip.networkipv6.vlan.ambiente.filter.id):
                                    tp_equip_list_one.append(fet.equiptype)

                                tp_equip_list_two = list()
                                for fet in FilterEquipType.objects.filter(filter=ip_test.networkipv6.vlan.ambiente.filter.id):
                                    tp_equip_list_two.append(fet.equiptype)

                                if equipment.tipo_equipamento not in tp_equip_list_one or equipment.tipo_equipamento not in tp_equip_list_two:
                                    raise IpRangeAlreadyAssociation(
                                        None, u'Equipment is already associated with another ip with the same ip range.')

                    ## Filter case 2 - end ##

                    # Delete vlan's cache
                    destroy_cache_function([net.vlan_id])
                    ip_equipment.save(user)

                    # Makes Environment Equipment association
                    try:
                        equipment_environment = EquipamentoAmbiente()
                        equipment_environment.equipamento = equipment
                        equipment_environment.ambiente = net.vlan.ambiente
                        equipment_environment.create(user)

                    except EquipamentoAmbienteDuplicatedError, e:
                        # If already exists, OK !
                        pass

                except IpRangeAlreadyAssociation, e:
                    raise IpRangeAlreadyAssociation(None, e.message)
                except IpEquipmentAlreadyAssociation, e:
                    raise IpEquipmentAlreadyAssociation(None, e.message)
                except AddressValueError, e:
                    self.log.error(e)
                    raise IpNotAvailableError(None, u'Ipv6 %s:%s:%s:%s:%s:%s:%s:%s is invalid' % (
                        ip.block1, ip.block2, ip.block3, ip.block4, ip.block5, ip.block6, ip.block7, ip.block8))
                except IpNotAvailableError, e:
                    raise IpNotAvailableError(None, u'Ipv6 %s:%s:%s:%s:%s:%s:%s:%s not available for network %s.' % (
                        ip.block1, ip.block2, ip.block3, ip.block4, ip.block5, ip.block6, ip.block7, ip.block8, net.id))
                except IpError, e:
                    self.log.error(
                        u'Error adding new IPv6 or relationship ip-equipment.')
                    raise IpError(
                        e, u'Error adding new IPv6 or relationship ip-equipment.')

                return self.response(dumps_networkapi({}))

        except IpRangeAlreadyAssociation, e:
            return self.response_error(347)
        except VlanNumberNotAvailableError, e:
            return self.response_error(314, e.message)
        except InvalidValueError, e:
            return self.response_error(269, e.param, e.value)
        except IpNotFoundError, e:
            return self.response_error(150, e.message)
        except NetworkIPv6NotFoundError:
            return self.response_error(286)
        except EquipamentoNotFoundError:
            return self.response_error(117, ip_map.get('id_equipment'))
        except IpNotAvailableError, e:
            return self.response_error(150, e.message)
        except IpEquipmentAlreadyAssociation, e:
            return self.response_error(150, e.message)
        except UserNotAuthorizedError:
            return self.not_authorized()
        except XMLError, x:
            self.log.error(u'Error reading the XML request.')
            return self.response_error(3, x)
        except (IpError, NetworkIPv6Error, EquipamentoError, GrupoError), e:
            self.log.error(e)
            return self.response_error(1)
