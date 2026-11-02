#!/usr/bin/env python3

import binascii
import logging

import hyx_kms_base
import hyx_kms_rpc_base
from hyx_kms_dcerpc import MSRPCRequestHeader, MSRPCRespHeader
from hyx_kms_format import justify, byterize, enco, deco, pretty_printer

#----------------------------------------------------------------------------------------------------------------------------------------------------------

loggersrv = logging.getLogger('logsrv')

class handler(hyx_kms_rpc_base.rpcBase):
        def parseRequest(self):
                request = MSRPCRequestHeader(self.data)
                pretty_printer(num_text = 14, where = "srv")
                request = byterize(request)
                loggersrv.debug("RPC Message Request Bytes: \n%s\n" % justify(binascii.b2a_hex(self.data).decode('utf-8')))
                loggersrv.debug("RPC Message Request: \n%s\n" % justify(request.dump(print_to_stdout = False)))
                                
                return request

        def generateResponse(self, request):
                responseData = hyx_kms_base.generateKmsResponseData(request['pduData'], self.srv_config)
                envelopeLength = len(responseData)

                response = MSRPCRespHeader()
                response['ver_major'] = request['ver_major']
                response['ver_minor'] = request['ver_minor']
                response['type'] = self.packetType['response']
                response['flags'] = self.packetFlags['firstFrag'] | self.packetFlags['lastFrag']
                response['representation'] = request['representation']
                response['call_id'] = request['call_id']

                response['alloc_hint'] = envelopeLength
                response['ctx_id'] = request['ctx_id']
                response['cancel_count'] = 0

                response['pduData'] = responseData

                pretty_printer(num_text = 17, where = "srv")
                response = byterize(response)
                loggersrv.debug("RPC Message Response: \n%s\n" % justify(response.dump(print_to_stdout = False)))
                loggersrv.debug("RPC Message Response Bytes: \n%s\n" % justify(deco(binascii.b2a_hex(enco(str(response), 'latin-1')), 'utf-8')))
                
                return response

        def generateRequest(self):
                request = MSRPCRequestHeader()

                request['ver_major'] = 5
                request['ver_minor'] = 0
                request['type'] = self.packetType['request']
                request['flags'] = self.packetFlags['firstFrag'] | self.packetFlags['lastFrag']
                request['representation'] = 0x10
                request['call_id'] = self.srv_config['call_id']
                request['alloc_hint'] = len(self.data)
                request['pduData'] = str(self.data)
                
                pretty_printer(num_text = 11, where = "clt")
                request = byterize(request)
                loggersrv.debug("RPC Message Request: \n%s\n" % justify(request.dump(print_to_stdout = False)))
                loggersrv.debug("RPC Message Request Bytes: \n%s\n" % justify(deco(binascii.b2a_hex(enco(str(request), 'latin-1')), 'utf-8')))
                
                return request

        def parseResponse(self):
                return byterize(MSRPCRespHeader(self.data))
