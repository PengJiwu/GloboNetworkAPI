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


from networkapi.admin_permission import AdminPermission
from networkapi.auth import has_perm
from networkapi.exception import InvalidValueError
from networkapi.rack.models import RackNumberNotFoundError, Rack , RackError, EnvironmentRack, RackAplError
from networkapi.infrastructure.xml_utils import dumps_networkapi
import logging
from networkapi.rest import RestResource, UserNotAuthorizedError
from networkapi.vlan.models import Vlan, VlanNetworkError, VlanInactiveError
from networkapi.ambiente.models import Ambiente, GrupoL3
from networkapi.distributedlock import distributedlock, LOCK_RACK
from networkapi import settings
import shutil
import glob
import commands



def desativar_vlan_rede(user, rack):

    nome = "_"+rack.nome
    vlans = Vlan.objects.all().filter(nome__contains=nome)

    for vlan in vlans:
        if nome in vlan.nome:
            network_errors = []

            for net4 in vlan.networkipv4_set.all():
                for ip in net4.ip_set.all():
                    ip.delete(user)

                if net4.active:
                    try:
                        net4.deactivate(user, True)
                    except Exception, e:
                        network_errors.append(str(net4.id))
                        pass

            for net6 in vlan.networkipv6_set.all():
                for ip6 in net6.ipv6_set.all():
                    ip6.delete(user)

                if net6.active:
                    try:
                        net6.deactivate(user, True)
                    except Exception, e:
                        network_errors.append(str(net6.id))
                        pass

            if network_errors:
                raise VlanNetworkError(None, message=', '.join(network_errors))

            if vlan.ativada:
                vlan.remove(user)

def remover_ambiente_rack(user, rack):

    lista_amb = []

    lista_amb_rack = EnvironmentRack.objects.all().filter(rack__exact=rack.id)

    for var in lista_amb_rack:
        lista_amb.append(var.ambiente)
        var.delete(user)

    return lista_amb

def remover_ambiente(user, lista_amb, rack):

    for amb in lista_amb:
        amb.remove(user, amb.id)
    grupo_l3 = GrupoL3()
    try:
        grupo_l3 = grupo_l3.get_by_name(rack.nome)
        grupo_l3.delete(user)
    except:
        pass

def aplicar(rack):

    path_config = settings.PATH_TO_CONFIG +'*'+rack.nome+'*'
    arquivos = glob.glob(path_config)
    for var in arquivos: 
        name_equipaments = var.split('/')[-1][:-4]      
        #Check if file is config relative to this rack
        for nome in name_equipaments:
            #Check if file is config relative to this rack
            if rack.nome in nome:
                #Apply config only in spines. Leaves already have all necessary config in startup
                if "DEL" in nome:
                    #Check if equipment in under maintenance. If so, does not aplly on it
                    try:
                        equip = Equipamento.get_by_name(nome)
                        if not equip.maintenance:
                            (erro, result) = commands.getstatusoutput("/usr/bin/backuper -T acl -b %s -e -i %s -w 300" % (var, nome))
                            if erro:
                                raise RackAplError(None, None, "Falha ao aplicar as configuracoes: %s" %(result))
                    except RackAplError, e:
                        raise e
                    except:
                        #Error equipment not found, do nothing
                        pass


def remover_vlan_so(user, rack):

    nome = "OOB_SO_"+rack.nome

    vlan = Vlan()
    try:
        vlan = vlan.get_by_name(nome)
        vlan.delete(user)
    except:
        pass

class RackDeleteResource(RestResource):

    log = logging.getLogger('RackDeleteResource')

    def handle_delete(self, request, user, *args, **kwargs):
        """Treat requests POST to delete Rack.

        URL: rack/id_rack/
        """
        try:
            self.log.info("Delete Rack")

            ########################################################                                     User permission
            if not has_perm(user, AdminPermission.SCRIPT_MANAGEMENT, AdminPermission.WRITE_OPERATION):
                self.log.error(
                    u'User does not have permission to perform the operation.')
                raise UserNotAuthorizedError(None)

            rack_id = kwargs.get('id_rack')
            rack = Rack()
            rack = rack.get_by_pk(rack_id)

            ######################################################## Mover os arquivos de configuracao que foram gerados
            try:
                for i in range(1,3):
                    nome_lf = settings.LEAF+"-"+rack.nome+"-0"+str(i)+settings.FORMATO
                    nome_lf_b = settings.PATH_TO_CONFIG+nome_lf
                    nome_lf_a = settings.PATH_TO_MV+nome_lf
                    shutil.move(nome_lf_b, nome_lf_a)
                    nome_oob = settings.OOB+"-0"+str(i)+"-ADD-"+rack.nome+settings.FORMATO
                    nome_oob_b = settings.PATH_TO_CONFIG+nome_oob
                    nome_oob_a = settings.PATH_TO_MV+nome_oob
                    shutil.move(nome_oob_b, nome_oob_a)
                for i in range(1,5):
                    nome_spn = settings.SPN+"-0"+str(i)+"-ADD-"+rack.nome+settings.FORMATO
                    nome_spn_b = settings.PATH_TO_CONFIG+nome_spn
                    nome_spn_a = settings.PATH_TO_MV+nome_spn
                    shutil.move(nome_spn_b, nome_spn_a)

                nome_oob = settings.OOB+"-"+rack.nome+"-01"+settings.FORMATO
                nome_oob_b = settings.PATH_TO_CONFIG+nome_oob
                nome_oob_a = settings.PATH_TO_MV+nome_oob
                shutil.move(nome_oob_b, nome_oob_a)
            except:
                pass

            ########################################################                 Remover as Vlans, redes e ambientes
            try:
                desativar_vlan_rede(user, rack)
                lista_amb = remover_ambiente_rack(user, rack)
                remover_ambiente(user, lista_amb, rack)
                remover_vlan_so(user, rack)
            except:
                raise RackError(None, u'Failed to remove the Vlans and Environments.')

            ########################################################         Remove rack config from spines and core oob
            aplicar(rack)

            ########################################################                                         Remove Rack
            with distributedlock(LOCK_RACK % rack_id):

                try:
                    rack.delete(user)
                except RackNumberNotFoundError, e:
                    raise e
                except Exception, e:
                    self.log.error(u'Failed to remove the Rack.')
                    raise RackError(e, u'Failed to remove the Rack.')                   

            return self.response(dumps_networkapi({}))

        except InvalidValueError, e:
            return self.response_error(269, e.param, e.value)

        except UserNotAuthorizedError:
            return self.not_authorized()

        except RackNumberNotFoundError:
            return self.response_error(379, rack_id)

        except RackError:
            return self.response_error(378)

        except VlanNetworkError, e:
            return self.response_error(369, e.message)

        except VlanInactiveError, e:
            return self.response_error(368)

        except RackAplError, e:
            return self.response_error(383, e.param, e.value)
