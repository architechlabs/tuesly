import ctypes,json,os
class Memory(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('physical_total',ctypes.c_ulonglong),('physical_available',ctypes.c_ulonglong),('page_total',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),('virtual_total',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),('extended_available',ctypes.c_ulonglong)]
memory=Memory();memory.length=ctypes.sizeof(memory)
ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
print(json.dumps({'logical_cpus':os.cpu_count(),'available_ram_gb':round(memory.physical_available/1024**3,2),'ram_used_percent':memory.load}))
