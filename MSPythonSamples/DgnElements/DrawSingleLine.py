# -*- coding: utf-8 -*-
'''
/*--------------------------------------------------------------------------------------+
| $Copyright: (c) 2024 Bentley Systems, Incorporated. All rights reserved. $
+--------------------------------------------------------------------------------------*/
'''

from MSPyBentley import *
from MSPyBentleyGeom import *
from MSPyECObjects import *
from MSPyDgnPlatform import *
from MSPyMstnPlatform import *


'''Draw a single line between two 3D points in the active model'''
def drawLine(startPoint, endPoint):
    ACTIVEMODEL = ISessionMgr.ActiveDgnModelRef
    if ACTIVEMODEL is None:
        print("No active model found.")
        return False

    seg = DSegment3d(startPoint, endPoint)
    eeh = EditElementHandle()

    status = LineHandler.CreateLineElement(eeh, None, seg, ACTIVEMODEL.Is3d(), ACTIVEMODEL)
    if BentleyStatus.eSUCCESS != status:
        print("Failed to create line element.")
        return False

    if BentleyStatus.eSUCCESS != eeh.AddToModel():
        print("Failed to add line element to model.")
        return False

    return True


if __name__ == "__main__":
    # Draw a line from (0, 0, 0) to (100, 100, 0)
    start = DPoint3d(0, 0, 0)
    end   = DPoint3d(100, 100, 0)
    if not drawLine(start, end):
        print("drawLine failed!")
    else:
        print("Line drawn successfully.")
