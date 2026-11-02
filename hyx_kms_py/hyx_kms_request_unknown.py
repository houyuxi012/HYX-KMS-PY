#!/usr/bin/env python3

import struct

from hyx_kms_base import kmsBase
from hyx_kms_misc import ErrorCodes

#---------------------------------------------------------------------------------------------------------------------------------------------------------

class kmsRequestUnknown(kmsBase):
        def executeRequestLogic(self):
                finalResponse = bytearray()
                finalResponse.extend(bytearray(struct.pack('<I', 0)))
                finalResponse.extend(bytearray(struct.pack('<I', 0)))
                finalResponse.extend(bytearray(struct.pack('<I', ErrorCodes['SL_E_VL_KEY_MANAGEMENT_SERVICE_ID_MISMATCH'][0])))
                return finalResponse.decode('latin-1')
