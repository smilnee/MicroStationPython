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


def draw_line(start_point, end_point, color=0, weight=2):
    '''Draw a single line element between two points in the active model.'''
    ACTIVEMODEL = ISessionMgr.ActiveDgnModelRef
    if ACTIVEMODEL is None:
        print("No active model found.")
        return False

    eeh = EditElementHandle()
    seg = DSegment3d(start_point, end_point)

    status = LineHandler.CreateLineElement(eeh, None, seg,
                                           ACTIVEMODEL.Is3d(),
                                           ACTIVEMODEL)
    if BentleyStatus.eSUCCESS != status:
        print("Failed to create line element.")
        return False

    props = ElementPropertiesSetter()
    props.SetColor(color)
    props.SetWeight(weight)
    props.Apply(eeh)

    if BentleyStatus.eSUCCESS != eeh.AddToModel():
        print("Failed to add line element to model.")
        return False

    return True


if __name__ == "__main__":
    start = DPoint3d(0, 0, 0)
    end   = DPoint3d(100, 100, 0)
    if not draw_line(start, end):
        print("draw_line failed.")
    else:
        print("Line drawn successfully.")
