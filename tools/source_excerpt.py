"""Bounded source excerpts for the local transport audit."""
import sys
from pathlib import Path
path=Path(sys.argv[1]);start=int(sys.argv[2]);stop=int(sys.argv[3])
for index,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
    if start<=index<=stop:print(f'{index}: {line}')
