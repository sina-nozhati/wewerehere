import os
import tempfile
from pathlib import Path

_tmp = Path("F:/tmp")
_tmp.mkdir(exist_ok=True)
os.environ["TEMP"] = str(_tmp)
os.environ["TMP"] = str(_tmp)
tempfile.tempdir = str(_tmp)
