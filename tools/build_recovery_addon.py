"""Package the proven mesh code for the independent HAOS recovery app."""
import ast, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'addons/tuesly_recovery'
SOURCE=ROOT/'custom_components/tuesly'
HEADER='''# Generated from the tested integration by tools/build_recovery_addon.py.
from __future__ import annotations
import asyncio,copy,logging,secrets,struct
from tuesly_mesh.sig_mesh_device import SIGMeshDevice
from tuesly_mesh.exceptions import MeshConnectionError
from tuesly_mesh.sig_mesh_protocol import encrypt_network_pdu,decrypt_network_pdu,generic_onoff_get
from tuesly_mesh.sig_lighting import parse_element_models,select_lighting_channel,lightness_get,temperature_get,parse_lightness_status,parse_temperature_status
_LOGGER=logging.getLogger(__name__)
class MeshSetupError(Exception):pass
class MeshLinkClosedError(MeshConnectionError):pass
'''
def main():
    DEST.mkdir(parents=True,exist_ok=True)
    tree=ast.parse((SOURCE/'sig_controller.py').read_text())
    device=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ManagedMeshDevice')
    coordinator=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SIGLightCoordinator')
    methods=[n for n in coordinator.body if getattr(n,'name',None) in ('_request','_configure','_read')]
    if len(methods)!=3:raise RuntimeError('Shared node configuration methods changed; review the package builder')
    journal_tree=ast.parse((SOURCE/'mesh_store.py').read_text())
    journal=next(n for n in journal_tree.body if isinstance(n,ast.ClassDef) and n.name=='MeshJournal')
    code=HEADER+ast.unparse(journal)+'\n\n'+ast.unparse(device)+'''

class NodeConfigurator:
    def __init__(self,mac,journal,device):
        self.mac,self.journal,self.device=mac,journal,device
        self.node=journal.state['nodes'][mac]
        self.models=None
        self.product_type=None
        self.minimum_kelvin=self.maximum_kelvin=None
        self.relative_temperature=False
        self.stage='initializing'
'''
    for method in methods:
        code+='\n'+'\n'.join('    '+line for line in ast.unparse(method).splitlines())+'\n'
    compile(code,'mesh_core.py','exec')
    (DEST/'mesh_core.py').write_text(code,encoding='utf-8')
    library=DEST/'lib/tuesly_mesh'
    library.mkdir(parents=True,exist_ok=True)
    # Copy individual SIG modules; avoid unrelated Telink package initialization.
    for file in (SOURCE/'lib/tuesly_mesh').glob('*.py'):
        if file.name!='__init__.py':shutil.copyfile(file,library/file.name)
    (library/'__init__.py').write_text('"""Tuesly mesh protocol runtime for the recovery service."""\n')
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT/name,DEST/name)
    print('Recovery app bundled from current tested mesh source')
if __name__=='__main__':main()
