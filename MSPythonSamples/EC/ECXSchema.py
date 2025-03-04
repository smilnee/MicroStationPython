# -*- coding: utf-8 -*-
'''
/*--------------------------------------------------------------------------------------+
| $Copyright: (c) 2024 Bentley Systems, Incorporated. All rights reserved. $
+--------------------------------------------------------------------------------------*/
'''
import os
import debugpy
import sys

from MSPyBentley import *
from MSPyECObjects import *
from MSPyDgnPlatform import *
from MSPyMstnPlatform import *


'''
Function to get list of schemas stored in
'''
def GetStoredSchemaList():
    #list to collect schema names
    schemaList = list()
    #Get dgnEC manager instance
    mgr = DgnECManager.GetManager()
    # Get the current DGN model
    ACTIVEMODEL = ISessionMgr.ActiveDgnModelRef
    dgnModel = ACTIVEMODEL.GetDgnModel()

    #iterate through all reachable models
    for modelRef in dgnModel.GetReachableModelRefs():
        #check for attachment, skip it if attached file is missing
        if modelRef.IsDgnAttachment():
            attachment = modelRef.AsDgnAttachment()
            if attachment.IsMissingFile():
                continue

        #get dgnFile from model
        dgnFile = modelRef.GetDgnFile()

        #discover schemas
        infos = SchemaInfoArray()
        mgr.DiscoverSchemas(infos, dgnFile)        
        infoContainer = SchemaInfoArray()
        for info in infos:
            infoContainer.append(info)
        
        if len(infoContainer) <= 0:
            continue
        
        #iterate container
        for info in infoContainer:
            #locate schema
            ecSchema = mgr.LocateSchemaInDgnFile(info, SchemaMatchType.eSCHEMAMATCHTYPE_Exact)
            if ecSchema is None:
                continue  
            #get schema name                  
            #schemaName = ecSchema.GetFullSchemaName()
            #add to list
            schemaList.append(ecSchema)
    #return schemaList
    return schemaList
'''
Function to list Schemas of active dgn file to a txt file
'''
def ListSchema ():
    print ('BEGIN: ListSchema() function called \n')
    #get list of stored schemas
    schemaList = GetStoredSchemaList()
    if (len(schemaList)) == 0:
        MessageCenter.ShowInfoMessage (f'No stored schemas', f'Could not found any stored schemas in this dgn', False)
        return    
    #write schemaNames to file
    currentPath = os.getcwd()
    filePath = currentPath + "\\" + "listschema.txt"
    f = open(filePath, "w")
    for ecSchema in schemaList:
        f.write(f'{ecSchema.GetFullSchemaName()}\n')
    f.close()
    #print message
    msgShort = f'Found {len(schemaList)} schems in dgn'
    msgLong = f'Schema list: {filePath}'
    MessageCenter.ShowInfoMessage (msgShort, msgLong, False)
        
'''
Function to export Schema files of active dgn file to current folder
'''
def ExportSchema ():

    print ('BEGIN: ExportSchema() function called \n')
    #get stored schema list
    schemaList = GetStoredSchemaList()
    if (len(schemaList)) == 0:
        MessageCenter.ShowInfoMessage (f'No stored schemas', f'Could not found any stored schemas in this dgn', False)
        return 

    #schema will be exported in ..\ECSchema\ folder
    currentPath = os.path.join(os.getcwd(), "ECSchema")
    if not os.path.exists(currentPath):
        os.mkdir(currentPath)

    expSchemaNames = list()
    expSchemaName = ''
    #export schemas
    argLength = len(sys.argv)
    if argLength == 0:
        #export all schemas
        for ecSchema in schemaList:
            schemaName = ecSchema.GetFullSchemaName()
            filePath = f'{currentPath}\\{schemaName.GetWCharCP()}.ecschema.xml'
            status = ecSchema.WriteToXmlFile(filePath)
            if SchemaWriteStatus.eSCHEMA_WRITE_STATUS_Success == status:
                expSchemaNames.append(schemaName)
    else:
        expSchemaName = str(sys.argv[0])
        for ecSchema in schemaList:
            schemaName = str(ecSchema.GetFullSchemaName().GetWCharCP())
            if expSchemaName == schemaName:
                filePath = f'{currentPath}\\{schemaName}.ecschema.xml'
                status = ecSchema.WriteToXmlFile(filePath)
                if SchemaWriteStatus.eSCHEMA_WRITE_STATUS_Success == status:
                    expSchemaNames.append(schemaName)
                break
    
    msgShort = 'Export succeeded'
    msgLong = 'long'

    if (len(expSchemaNames) == 0):
        msgShort = 'Export failed'
        msgLong = 'Could not export any schema'
    elif (len(expSchemaNames) == 1):
        msgLong = f'Exported \'{expSchemaName}\' at {currentPath}'
    else:
        msgLong = f'Exported {len(expSchemaNames)} schemas at {currentPath}'

    MessageCenter.ShowInfoMessage (msgShort, msgLong, False)

if __name__ == "__main__":
    keyinXml = os.path.dirname(__file__) + '/ECXSchema.commands.xml'
    PythonKeyinManager.GetManager ().LoadCommandTableFromXml (WString (__file__), WString (keyinXml))    


