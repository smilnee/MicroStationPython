# MicroStation Python Script Revision Guide

This guide describes how to revise and maintain Python scripts in the `MSPythonSamples` directory.

---

## When to Revise a Script

Revise a script when:

- A MicroStation Python API method or class has been renamed, moved, or removed.
- A new MSPython module version introduces breaking changes.
- The script was written against an older Python version and needs modernization.
- The copyright year is out of date.
- The script uses deprecated patterns identified in release notes.

---

## File Header

Every script must begin with the encoding declaration and copyright block:

```python
# -*- coding: utf-8 -*-
'''
/*--------------------------------------------------------------------------------------+
| $Copyright: (c) <YEAR> Bentley Systems, Incorporated. All rights reserved. $
+--------------------------------------------------------------------------------------*/
'''
```

When revising a script, update `<YEAR>` to the current year.

---

## Standard Imports

Import only the MSPython modules the script actually uses. The available modules are:

| Module | Contents |
|---|---|
| `MSPyBentley` | Core Bentley types (`WString`, `BentleyStatus`, etc.) |
| `MSPyBentleyGeom` | Geometry types (`DPoint3d`, `DVec3d`, `Transform`, etc.) |
| `MSPyECObjects` | EC schema and instance classes |
| `MSPyDgnPlatform` | DGN file, model, and element classes |
| `MSPyDgnView` | View-related tool base classes (`DgnElementSetTool`, etc.) |
| `MSPyMstnPlatform` | MicroStation platform APIs (`ISessionMgr`, `PyCadInputQueue`, etc.) |

Wildcard imports (`from MSPyBentley import *`) are the established convention in this repo. Do not change to qualified imports unless a naming conflict requires it.

---

## API Changes

### Checking for Deprecated or Renamed APIs

1. Review the release notes or changelog for the target MSPython version.
2. Search the `PublicAPI` directory for the current binding signatures:
   ```
   grep -r "OldMethodName" PublicAPI/
   ```
3. If the method no longer exists, find its replacement in the same header or in the release notes.

### Updating a Method Call

Before:
```python
result = element.GetOldMethod(param)
```

After:
```python
result = element.GetNewMethod(param)
```

If the return type or tuple structure changed, update all call sites that unpack the result.

---

## Docstring Style

Older scripts use C++ Doxygen-style block comments embedded in Python triple-quoted strings:

```python
'''
/*=================================================================================**//**
* Description of the class.
* @bsiclass                                                               Bentley Systems
+===============+===============+===============+===============+===============+======*/
'''
class MyTool(DgnElementSetTool):
    '''
    /*---------------------------------------------------------------------------------**//**
    * @bsimethod                                                              Bentley Systems
    +---------------+---------------+---------------+---------------+---------------+------*/
    '''
    def __init__(self, toolId):
        ...
```

This style is acceptable and should be preserved when doing minor revisions to keep diffs small. When doing a full rewrite of a script, replace with standard Python docstrings:

```python
class MyTool(DgnElementSetTool):
    """Example showing how to use DgnElementSetTool."""

    def __init__(self, toolId):
        """Initialize the tool. C++ base __init__ must be called."""
        DgnElementSetTool.__init__(self, toolId)
        ...
```

---

## Common Patterns and How to Update Them

### Session and Model Access

```python
# Current pattern
ACTIVEMODEL = ISessionMgr.ActiveDgnModelRef
```

Always null-check the result before use:

```python
ACTIVEMODEL = ISessionMgr.ActiveDgnModelRef
if ACTIVEMODEL is None:
    return
```

### Return Tuple Unpacking

Many API methods return a `(status, value)` tuple. Check the status before using the value:

```python
ret = loadDgnFile.CreateNewModel(modelName, DgnModelType.eNormal, False)
if ret[1] != eDGNMODEL_STATUS_Success:
    return False
model = ret[0]
```

### Tool Entry Point

Scripts that install a `DgnTool` subclass must call `InstallNewInstance` from `__main__`:

```python
if __name__ == "__main__":
    MyTool.InstallNewInstance(toolId=1)
```

The `toolId` value must be unique within the MicroStation session. Use `1` for standalone sample scripts.

### Macro-style Scripts

Scripts that only send keyins and data points (no tool class) can call the input queue directly at module level:

```python
PyCadInputQueue.SendCommand("Place Line")
PyCadInputQueue.SendDataPoint(DPoint3d(x, y, z), 1)
PyCadInputQueue.SendReset()
```

---

## Testing a Revised Script

MicroStation Python scripts run inside MicroStation. To test after revision:

1. Open MicroStation with an appropriate `.dgn` file (see `MSPythonSamples/` for matching sample DGN files).
2. Open the Python script manager or use the key-in `python load <path-to-script.py>`.
3. Verify the expected behaviour manually.
4. Check the MicroStation output/message area for Python tracebacks.

There is no standalone unit test runner for scripts that require a live MicroStation session. For logic that can be isolated (pure geometry calculations, file parsing), use `pytest` with a separate test module under `MSPythonTests/`.

---

## Checklist Before Committing

- [ ] Copyright year updated.
- [ ] Only necessary modules imported.
- [ ] All return tuples checked before unpacking.
- [ ] Null/None checks on API objects before use.
- [ ] `__main__` guard present and correct.
- [ ] Script tested against a live MicroStation session or documented as untested.
- [ ] No debug dependencies (e.g., `debugpy`) left in production scripts unless the script is explicitly a debugging utility.
