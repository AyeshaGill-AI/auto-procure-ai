import sys
import pathlib

backend_dir = pathlib.Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app import app
from services.db import init

init()
